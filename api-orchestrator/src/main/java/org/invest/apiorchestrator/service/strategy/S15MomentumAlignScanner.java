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
public class S15MomentumAlignScanner extends DailyStrategySupport implements StrategyScanner {

    public S15MomentumAlignScanner(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        super(apiService, redisService, stockMasterRepository);
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S15_MOMENTUM_ALIGN;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<TradingSignalDto> results = new ArrayList<>();
        for (String stkCd : context.candidates()) {
            try {
                DailySeries series = fetchDailySeries(stkCd, 35);
                if (series == null || series.closes()[0] <= 0) {
                    continue;
                }
                double[] highs = series.highs();
                double[] lows = series.lows();
                double[] closes = series.closes();
                double[] vols = series.vols();

                double ma20 = maAvg(closes, 0, 20);
                if (closes[0] < ma20) {
                    continue;
                }

                double fluRt = closes[1] > 0 ? (closes[0] - closes[1]) / closes[1] * 100 : 0;
                if (fluRt <= 0 || fluRt > 12.0) {
                    continue;
                }

                double[] rsi = calcRsi(closes, 14);
                double rsiNow = rsi.length > 0 ? rsi[0] : 0;
                double rsiPrev = rsi.length > 1 ? rsi[1] : 0;
                if (rsiNow > 72) {
                    continue;
                }

                double[][] macd = calcMacd(closes, 12, 26, 9);
                boolean macdGcToday = macd[0].length > 1 && macd[1].length > 1
                        && macd[0][0] > macd[1][0] && macd[0][1] <= macd[1][1];
                boolean histExpand = macd[2].length > 2
                        && macd[2][0] > 0 && macd[2][0] > macd[2][1] && macd[2][1] > macd[2][2];
                boolean condMacd = macdGcToday || (macd[0].length > 0 && macd[0][0] > 0 && histExpand);
                boolean condRsi = rsiNow >= 48 && rsiNow <= 68;
                double pctB = calcBollingerPctB(closes, 20);
                boolean condBoll = pctB >= 0.45 && pctB <= 0.82;
                double volMa20 = maAvg(vols, 1, 20);
                double volRatio = volMa20 > 0 ? vols[0] / volMa20 : 1.0;
                boolean condVol = volRatio >= 1.3;
                int condCount = (condMacd ? 1 : 0) + (condRsi ? 1 : 0)
                        + (condBoll ? 1 : 0) + (condVol ? 1 : 0);
                if (condCount < 3) {
                    continue;
                }

                double[] atr = calcAtr(highs, lows, closes, 14);
                double atrNow = atr.length > 0 ? atr[0] : 0;
                double atrPct = atrNow > 0 ? atrNow / closes[0] * 100 : 0;
                boolean atrOk = atrPct >= 1.0 && atrPct <= 3.0;
                var strengthData = entryStrength(stkCd, 5);
                double strength = neutralStrength(strengthData);
                MarketBreadth marketBreadth = fetchMarketBreadthForStock(stkCd);
                double score = fluRt * 0.6
                        + Math.max(strength - 100, 0) * 0.2
                        + condCount * 8
                        + (condCount == 4 ? 20 : 0)
                        + (atrOk ? 8 : 0)
                        + (strength >= 105 ? 8 : 0)
                        + (rsiPrev > 0 && rsiNow > rsiPrev ? 5 : 0)
                        + marketBreadth.scoreBonus();

                double sl = atrNow > 0 ? round(closes[0] - atrNow * 1.5) : round(closes[0] * 0.95);
                double bbu = calcBollingerUpper(closes, 20);
                double tp1 = bbu > closes[0] ? round(Math.max(bbu, closes[0] * 1.06)) : round(closes[0] * 1.08);
                double tp2 = atrNow > 0 ? round(tp1 + atrNow * 0.5) : round(closes[0] * 1.15);
                Map<String, Object> extra = marketBreadthExtra(marketBreadth);
                addFreshnessExtra(extra, "strength", strengthData);

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
                        .atrPct(atrPct > 0 ? round(atrPct) : null)
                        .condCount(condCount)
                        .entryType("momentum_align_daily")
                        .holdingDays("5~10 trading days")
                        .targetPct(round((tp1 - closes[0]) / closes[0] * 100))
                        .target2Pct(round((tp2 - closes[0]) / closes[0] * 100))
                        .stopPct(round((sl - closes[0]) / closes[0] * 100))
                        .tp1Price(tp1)
                        .tp2Price(tp2)
                        .slPrice(sl)
                        .extra(extra)
                        .build());
            } catch (Exception e) {
                log.debug("[S15] {} processing failed: {}", stkCd, e.getMessage());
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
