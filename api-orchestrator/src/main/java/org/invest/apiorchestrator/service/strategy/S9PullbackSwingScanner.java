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
public class S9PullbackSwingScanner extends DailyStrategySupport implements StrategyScanner {

    public S9PullbackSwingScanner(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        super(apiService, redisService, stockMasterRepository);
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S9_PULLBACK_SWING;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<TradingSignalDto> results = new ArrayList<>();
        for (String stkCd : context.candidates()) {
            try {
                DailySeries series = fetchDailySeries(stkCd, 21);
                if (series == null || series.closes()[0] <= 0) {
                    continue;
                }
                double[] highs = series.highs();
                double[] lows = series.lows();
                double[] closes = series.closes();
                double[] vols = series.vols();

                double ma5 = maAvg(closes, 0, 5);
                double ma20 = maAvg(closes, 0, 20);
                if (!(closes[0] > ma5 && ma5 > ma20)) {
                    continue;
                }

                boolean hasPullback = false;
                for (int i = 0; i < 3 && i < series.size(); i++) {
                    if (lows[i] <= ma5 * 1.01 && closes[i] >= ma5 * 0.99) {
                        hasPullback = true;
                        break;
                    }
                }
                if (!hasPullback) {
                    continue;
                }

                double fluRt = closes[1] > 0 ? (closes[0] - closes[1]) / closes[1] * 100 : 0;
                if (fluRt <= 0 || fluRt > 8.0) {
                    continue;
                }

                double[] rsi = calcRsi(closes, 14);
                double rsiNow = rsi.length > 0 ? rsi[0] : 0;
                if (rsiNow > 68) {
                    continue;
                }

                double[][] stoch = calcSlowStoch(highs, lows, closes, 14, 3, 3);
                boolean stochGc = stoch[0].length > 1 && stoch[1].length > 1
                        && stoch[0][0] > stoch[1][0]
                        && stoch[0][1] <= stoch[1][1]
                        && stoch[0][1] < 25.0;

                double volMa20 = maAvg(vols, 1, 20);
                double volRatio = volMa20 > 0 ? vols[0] / volMa20 : 1.0;
                double strength = redisService.getAvgCntrStrength(stkCd, 5);
                MarketBreadth marketBreadth = fetchMarketBreadthForStock(stkCd);
                double score = fluRt * 2 + volRatio * 4
                        + (stochGc ? 12 : 0)
                        + (rsiNow >= 40 && rsiNow <= 58 ? 8 : 0)
                        + Math.max(strength - 100, 0) * 0.2
                        + marketBreadth.scoreBonus();

                double slPrice = ma20 > 0 ? round(Math.max(ma20 * 0.97, closes[0] * 0.96)) : round(closes[0] * 0.96);
                double stopPct = Math.max((slPrice - closes[0]) / closes[0] * 100, -4.0);
                double recentHigh10 = closes[0];
                for (int i = 1; i <= 10 && i < series.size(); i++) {
                    recentHigh10 = Math.max(recentHigh10, highs[i]);
                }
                double tp1 = round(Math.max(recentHigh10, closes[0] * 1.08));
                double recentHigh20 = tp1;
                for (int i = 1; i <= 20 && i < series.size(); i++) {
                    recentHigh20 = Math.max(recentHigh20, highs[i]);
                }
                double tp2 = round(Math.max(recentHigh20, tp1 * 1.03));
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
                        .entryType("pullback_swing_daily")
                        .holdingDays("5~8 trading days")
                        .targetPct(round((tp1 - closes[0]) / closes[0] * 100))
                        .target2Pct(round((tp2 - closes[0]) / closes[0] * 100))
                        .stopPct(round(stopPct))
                        .tp1Price(tp1)
                        .tp2Price(tp2)
                        .slPrice(slPrice)
                        .extra(extra)
                        .build());
            } catch (Exception e) {
                log.debug("[S9] {} processing failed: {}", stkCd, e.getMessage());
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
