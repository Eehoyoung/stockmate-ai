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
public class S14OversoldBounceScanner extends DailyStrategySupport implements StrategyScanner {

    public S14OversoldBounceScanner(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        super(apiService, redisService, stockMasterRepository);
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<TradingSignalDto> results = new ArrayList<>();
        for (String stkCd : context.candidates()) {
            try {
                DailySeries series = fetchDailySeries(stkCd, 30);
                if (series == null || series.closes()[0] <= 0) {
                    continue;
                }
                double[] highs = series.highs();
                double[] lows = series.lows();
                double[] closes = series.closes();
                double[] vols = series.vols();

                double[] rsi = calcRsi(closes, 14);
                double rsiNow = rsi.length > 0 ? rsi[0] : 0;
                double rsiPrev = rsi.length > 1 ? rsi[1] : 0;
                if (rsiNow <= 0 || rsiNow > 38 || rsiNow < 20) {
                    continue;
                }

                if (series.size() >= 60) {
                    double ma60 = maAvg(closes, 0, 60);
                    if (closes[0] < ma60 * 0.88) {
                        continue;
                    }
                }

                double[] atr = calcAtr(highs, lows, closes, 14);
                double atrNow = atr.length > 0 ? atr[0] : 0;
                if (atrNow <= 0) {
                    continue;
                }
                double atrPct = atrNow / closes[0] * 100;
                if (atrPct > 4.0) {
                    continue;
                }

                double fluRt = closes[1] > 0 ? (closes[0] - closes[1]) / closes[1] * 100 : 0;
                if (fluRt < -5.0) {
                    continue;
                }

                double[][] stoch = calcSlowStoch(highs, lows, closes, 14, 3, 3);
                boolean condStoch = stoch[0].length > 1 && stoch[1].length > 1
                        && stoch[0][0] > stoch[1][0]
                        && stoch[0][1] <= stoch[1][1]
                        && stoch[0][1] < 25.0;

                double[] williamsR = calcWilliamsR(highs, lows, closes, 14);
                boolean condWr = williamsR.length > 1 && williamsR[1] < -80.0 && williamsR[0] > williamsR[1];

                double mfiNow = calcMfiLatest(highs, lows, closes, vols, 14);
                double mfiPrev = calcMfiAt(highs, lows, closes, vols, 14, 1);
                boolean condMfi = mfiNow > 0 && mfiNow < 30.0 && (mfiNow > mfiPrev || mfiNow > 25.0);

                int condCount = (condStoch ? 1 : 0) + (condWr ? 1 : 0) + (condMfi ? 1 : 0);
                if (condCount < 2) {
                    continue;
                }

                double volMa20 = maAvg(vols, 1, 20);
                double volRatio = volMa20 > 0 ? vols[0] / volMa20 : 1.0;
                var strengthData = entryStrength(stkCd, 5);
                double strength = neutralStrength(strengthData);
                double score = (38 - rsiNow) * 0.5
                        + condCount * 10
                        + (rsiPrev > 0 && rsiNow > rsiPrev ? 10 : 0)
                        + (condCount == 3 ? 15 : 0)
                        + (volRatio >= 1.5 ? 8 : 0)
                        + (strength >= 105 ? 8 : 0)
                        + Math.max(strength - 100, 0) * 0.1;

                double sl = round(closes[0] - atrNow * 2.0);
                double tp1 = round(closes[0] + atrNow * 5.0);
                double ma20 = series.size() >= 20 ? maAvg(closes, 0, 20) : 0;
                double tp2 = ma20 > tp1 ? round(ma20) : round(closes[0] + atrNow * 7.0);
                Map<String, Object> extra = new LinkedHashMap<>();
                addFreshnessExtra(extra, "strength", strengthData);

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(resolveStkNm(stkCd))
                        .strategy(type())
                        .signalScore(round(score))
                        .entryPrice(closes[0])
                        .gapPct(round(fluRt))
                        .cntrStrength(round(strength))
                        .volRatio(round(volRatio))
                        .rsi(round(rsiNow))
                        .atrPct(round(atrPct))
                        .condCount(condCount)
                        .entryType("oversold_bounce_daily")
                        .holdingDays("3~5 trading days")
                        .targetPct(round((tp1 - closes[0]) / closes[0] * 100))
                        .target2Pct(round((tp2 - closes[0]) / closes[0] * 100))
                        .stopPct(round((sl - closes[0]) / closes[0] * 100))
                        .tp1Price(tp1)
                        .tp2Price(tp2)
                        .slPrice(sl)
                        .extra(extra)
                        .build());
            } catch (Exception e) {
                log.debug("[S14] {} processing failed: {}", stkCd, e.getMessage());
            }
        }
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5)
                .collect(Collectors.toList());
    }
}
