package org.invest.apiorchestrator.service.strategy;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Component
public class S8GoldenCrossScanner extends DailyStrategySupport implements StrategyScanner {

    public S8GoldenCrossScanner(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        super(apiService, redisService, stockMasterRepository);
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S8_GOLDEN_CROSS;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<TradingSignalDto> results = new ArrayList<>();
        for (String stkCd : context.candidates()) {
            try {
                DailySeries series = fetchDailySeries(stkCd, 26);
                if (series == null || series.closes()[0] <= 0) {
                    continue;
                }
                double[] closes = series.closes();
                double[] vols = series.vols();

                double ma5 = maAvg(closes, 0, 5);
                double ma20 = maAvg(closes, 0, 20);
                double ma5Prev = maAvg(closes, 1, 5);
                double ma20Prev = maAvg(closes, 1, 20);
                if (!(ma5 >= ma20 && ma5Prev < ma20Prev) || closes[0] < ma5) {
                    continue;
                }

                double fluRt = closes[1] > 0 ? (closes[0] - closes[1]) / closes[1] * 100 : 0;
                if (fluRt <= 0 || fluRt > 12.0) {
                    continue;
                }

                double[] rsi = calcRsi(closes, 14);
                double rsiNow = rsi.length > 0 ? rsi[0] : 0;
                if (rsiNow > 75) {
                    continue;
                }

                double volMa20 = maAvg(vols, 1, 20);
                double volRatio = volMa20 > 0 ? vols[0] / volMa20 : 1.0;
                if (volRatio < 1.2) {
                    continue;
                }

                double[][] macd = calcMacd(closes, 12, 26, 9);
                boolean macdAccel = macd[2].length > 1 && macd[2][0] > 0 && macd[2][0] > macd[2][1];
                double strength = redisService.getAvgCntrStrength(stkCd, 5);
                MarketBreadth marketBreadth = fetchMarketBreadthForStock(stkCd);
                double score = fluRt * 1.5 + volRatio * 5
                        + (rsiNow >= 45 && rsiNow <= 65 ? 12 : 0)
                        + (macdAccel ? 10 : 0)
                        + Math.max(strength - 100, 0) * 0.2
                        + marketBreadth.scoreBonus();

                double slPrice = ma20 > 0 ? round(Math.max(ma20 * 0.98, closes[0] * 0.96)) : round(closes[0] * 0.96);
                double stopPct = Math.max((slPrice - closes[0]) / closes[0] * 100, -4.0);
                double recentHigh10 = closes[0];
                for (int i = 1; i <= 10 && i < series.size(); i++) {
                    recentHigh10 = Math.max(recentHigh10, parseDoubleStr(series.raw().get(i).getHighPric()));
                }
                double tp1 = round(Math.max(recentHigh10, closes[0] * 1.08));
                double tp2 = round(tp1 * 1.05);
                Map<String, Object> extra = marketBreadthExtra(marketBreadth);

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(resolveStkNm(stkCd))
                        .strategy(type())
                        .signalScore(round(score))
                        .entryPrice(closes[0])
                        .gapPct(round(fluRt))
                        .volRatio(round(volRatio))
                        .cntrStrength(round(strength))
                        .rsi(rsiNow > 0 ? round(rsiNow) : null)
                        .entryType("golden_cross_daily")
                        .holdingDays("5~10 trading days")
                        .targetPct(round((tp1 - closes[0]) / closes[0] * 100))
                        .target2Pct(round((tp2 - closes[0]) / closes[0] * 100))
                        .stopPct(round(stopPct))
                        .tp1Price(tp1)
                        .tp2Price(tp2)
                        .slPrice(slPrice)
                        .extra(extra)
                        .build());
            } catch (Exception e) {
                log.debug("[S8] {} processing failed: {}", stkCd, e.getMessage());
            }
        }
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5)
                .collect(Collectors.toList());
    }

    private Map<String, Object> marketBreadthExtra(MarketBreadth marketBreadth) {
        Map<String, Object> extra = new LinkedHashMap<>();
        if (marketBreadth.present()) {
            extra.put("market_breadth_code", marketBreadth.marketCode());
            extra.put("market_breadth_name", marketBreadth.marketName());
            extra.put("market_breadth_flu_rt", marketBreadth.fluRt());
            extra.put("market_breadth_rising", marketBreadth.rising());
            extra.put("market_breadth_falling", marketBreadth.falling());
            extra.put("market_breadth_score_bonus", round(marketBreadth.scoreBonus()));
        }
        return extra;
    }
}
