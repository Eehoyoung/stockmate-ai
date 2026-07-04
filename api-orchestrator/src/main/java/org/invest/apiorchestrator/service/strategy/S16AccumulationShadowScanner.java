package org.invest.apiorchestrator.service.strategy;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.StockMaster;
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
import java.util.Optional;
import java.util.stream.Collectors;

@Slf4j
@Component
public class S16AccumulationShadowScanner extends DailyStrategySupport implements StrategyScanner {

    private static final double MIN_MARKET_CAP_EOK = 1_500.0;
    private static final double MAX_MARKET_CAP_EOK = 10_000.0;

    public S16AccumulationShadowScanner(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        super(apiService, redisService, stockMasterRepository);
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<TradingSignalDto> results = new ArrayList<>();
        for (String stkCd : context.candidates()) {
            try {
                DailySeries series = fetchDailySeries(stkCd, 60);
                if (series == null || series.closes()[0] <= 0) {
                    continue;
                }
                double marketCapEok = marketCapEok(stkCd);
                if (marketCapEok > 0 && (marketCapEok < MIN_MARKET_CAP_EOK || marketCapEok > MAX_MARKET_CAP_EOK)) {
                    continue;
                }
                double[] highs = series.highs();
                double[] lows = series.lows();
                double[] closes = series.closes();
                double[] vols = series.vols();
                double curPrice = closes[0];
                double boxHigh = recentHigh(highs, 40);
                double boxLow = recentLow(lows, 40);
                if (boxHigh <= 0 || boxLow <= 0 || boxHigh <= boxLow) {
                    continue;
                }
                double boxWidthPct = (boxHigh - boxLow) / curPrice * 100.0;
                if (boxWidthPct < 8.0 || boxWidthPct > 50.0) {
                    continue;
                }
                double rise5 = pct(curPrice, closes[5]);
                double rise20 = pct(curPrice, closes[20]);
                if (rise5 > 25.0 || rise20 > 35.0) {
                    continue;
                }

                double recentLow20 = recentLow(lows, 20);
                double previousLow20 = recentLow(slice(lows, 20, 40), 20);
                boolean lowRising = previousLow20 > 0 && recentLow20 > previousLow20 * 0.98;
                double volMa20 = maAvg(vols, 1, 20);
                double volRatio = volMa20 > 0 ? vols[0] / volMa20 : 0;
                double upDownVolRatio = upDownVolRatio(series);
                double avgTradingValueEok = avgTradingValueEok(series);
                if (avgTradingValueEok > 0 && avgTradingValueEok < 20.0) {
                    continue;
                }

                double strength = redisService.getAvgCntrStrength(stkCd, 5);
                double bidRatio = bidRatio(stkCd);
                SectorFlow sectorFlow = fetchSectorFlow(stkCd);
                MarketBreadth marketBreadth = fetchMarketBreadthForStock(stkCd);

                double accumulationScore = 0.0;
                accumulationScore += boxWidthPct <= 35.0 ? 18.0 : 10.0;
                accumulationScore += lowRising ? 12.0 : 0.0;
                accumulationScore += upDownVolRatio >= 1.4 ? 12.0 : upDownVolRatio >= 1.15 ? 8.0 : 0.0;
                accumulationScore += 0.8 <= volRatio && volRatio <= 3.0 ? 8.0 : volRatio > 3.0 ? 5.0 : 0.0;
                accumulationScore = Math.min(50.0, accumulationScore) / 50.0 * 30.0;

                double triggerScore = 0.0;
                triggerScore += strength >= 120.0 ? 8.0 : strength >= 110.0 ? 4.0 : 0.0;
                triggerScore += bidRatio >= 1.3 ? 5.0 : 0.0;
                triggerScore += volRatio >= 1.5 ? 4.0 : 0.0;
                double boxProximityPct = (curPrice - boxHigh) / boxHigh * 100.0;
                triggerScore += -4.0 <= boxProximityPct && boxProximityPct <= 3.0 ? 3.0 : 0.0;

                double totalScore = accumulationScore
                        + Math.max(0.0, sectorFlow.scoreBonus())
                        + Math.max(0.0, marketBreadth.scoreBonus())
                        + triggerScore
                        + 10.0;
                if (totalScore < 55.0) {
                    continue;
                }

                double sl = round(Math.max(boxLow, curPrice * 0.94));
                double boxRange = boxHigh - boxLow;
                double tp1 = round(Math.max(boxHigh + boxRange * 0.5, curPrice * 1.05));
                double tp2 = round(Math.max(boxHigh + boxRange, curPrice * 1.10));

                Map<String, Object> extra = new LinkedHashMap<>();
                extra.put("s16_box_low", round(boxLow));
                extra.put("s16_box_high", round(boxHigh));
                extra.put("s16_box_width_pct", round(boxWidthPct));
                extra.put("s16_market_cap_eok", round(marketCapEok));
                extra.put("s16_up_down_vol_ratio", round(upDownVolRatio));
                extra.put("s16_avg_trading_value_eok", round(avgTradingValueEok));
                extra.put("s16_low_rising", lowRising);
                extra.put("s16_sector_score_bonus", round(sectorFlow.scoreBonus()));
                extra.put("s16_market_breadth_score_bonus", round(marketBreadth.scoreBonus()));

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(resolveStkNm(stkCd))
                        .strategy(type())
                        .signalScore(round(totalScore))
                        .entryPrice(curPrice)
                        .volRatio(round(volRatio))
                        .cntrStrength(round(strength))
                        .bidRatio(round(bidRatio))
                        .entryType("accumulation_shadow_daily")
                        .holdingDays("10~20 trading days")
                        .targetPct(round((tp1 - curPrice) / curPrice * 100))
                        .target2Pct(round((tp2 - curPrice) / curPrice * 100))
                        .stopPct(round((sl - curPrice) / curPrice * 100))
                        .tp1Price(tp1)
                        .tp2Price(tp2)
                        .slPrice(sl)
                        .extra(extra)
                        .build());
            } catch (Exception e) {
                log.debug("[S16] {} processing failed: {}", stkCd, e.getMessage());
            }
        }
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5)
                .collect(Collectors.toList());
    }

    private double marketCapEok(String stkCd) {
        try {
            Optional<StockMaster> master = stockMasterRepository.findByStkCd(stkCd);
            return master.map(StockMaster::getMarketCap).map(v -> v / 100_000_000.0).orElse(0.0);
        } catch (Exception ignored) {
            return 0.0;
        }
    }

    private double bidRatio(String stkCd) {
        try {
            var hoga = redisService.getHogaData(stkCd);
            if (hoga.isEmpty()) {
                return 0.0;
            }
            double bid = parseDouble(hoga.get(), "total_buy_bid_req");
            double ask = parseDouble(hoga.get(), "total_sel_bid_req");
            return ask > 0 ? bid / ask : 0.0;
        } catch (Exception ignored) {
            return 0.0;
        }
    }

    private double upDownVolRatio(DailySeries series) {
        double upVol = 0.0;
        double downVol = 0.0;
        for (int i = 0; i < Math.min(20, series.size()); i++) {
            double open = parseDoubleStr(series.raw().get(i).getOpenPric());
            if (series.closes()[i] >= open) {
                upVol += series.vols()[i];
            } else {
                downVol += series.vols()[i];
            }
        }
        return downVol > 0 ? upVol / downVol : upVol > 0 ? 2.0 : 0.0;
    }

    private double avgTradingValueEok(DailySeries series) {
        double sum = 0.0;
        int count = 0;
        for (int i = 0; i < Math.min(20, series.size()); i++) {
            double amount = parseDoubleStr(series.raw().get(i).getTrdePrica());
            double value = amount > 0 ? amount / 100_000_000.0 : series.closes()[i] * series.vols()[i] / 100_000_000.0;
            if (value > 0) {
                sum += value;
                count++;
            }
        }
        return count > 0 ? sum / count : 0.0;
    }

    private double recentHigh(double[] highs, int days) {
        double value = 0.0;
        for (int i = 0; i < Math.min(days, highs.length); i++) {
            value = Math.max(value, highs[i]);
        }
        return value;
    }

    private double recentLow(double[] lows, int days) {
        double value = Double.MAX_VALUE;
        for (int i = 0; i < Math.min(days, lows.length); i++) {
            if (lows[i] > 0) {
                value = Math.min(value, lows[i]);
            }
        }
        return value == Double.MAX_VALUE ? 0.0 : value;
    }

    private double[] slice(double[] source, int start, int end) {
        int len = Math.max(0, Math.min(end, source.length) - start);
        double[] out = new double[len];
        for (int i = 0; i < len; i++) {
            out[i] = source[start + i];
        }
        return out;
    }

    private double pct(double current, double previous) {
        return previous > 0 ? (current - previous) / previous * 100.0 : 0.0;
    }
}
