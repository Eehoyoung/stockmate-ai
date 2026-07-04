package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.Optional;

@Slf4j
@Component
@RequiredArgsConstructor
public class S10NewHighEvaluator {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;
    private final StockMasterRepository stockMasterRepository;

    public Optional<TradingSignalDto> evaluate(String stkCd) {
        try {
            var resp = apiService.fetchKa10081(stkCd);
            if (resp.getCandles() == null || resp.getCandles().size() < 20) {
                return Optional.empty();
            }

            var candles = resp.getCandles();
            var today = candles.get(0);

            double todayHigh = parseDoubleStr(today.getHighPric());
            double todayClose = parseDoubleStr(today.getCurPrc());
            double todayOpen = parseDoubleStr(today.getOpenPric());
            long todayVol = parseLongStr(today.getTrdeQty());

            if (todayHigh <= 0 || todayClose <= 0 || todayOpen <= 0 || todayClose <= todayOpen) {
                return Optional.empty();
            }

            int historyDays = Math.min(250, candles.size() - 1);
            double yearHigh = candles.subList(1, historyDays + 1).stream()
                    .mapToDouble(c -> parseDoubleStr(c.getHighPric()))
                    .max().orElse(0);
            if (yearHigh <= 0 || todayHigh < yearHigh * 0.999) {
                return Optional.empty();
            }

            double prevClose = parseDoubleStr(candles.get(1).getCurPrc());
            if (prevClose <= 0) {
                return Optional.empty();
            }
            double fluRt = (todayClose - prevClose) / prevClose * 100;
            if (fluRt < 0.5 || fluRt > 15.0) {
                return Optional.empty();
            }

            double avgVol = candles.subList(1, Math.min(21, candles.size())).stream()
                    .mapToLong(c -> parseLongStr(c.getTrdeQty()))
                    .average().orElse(1);
            double volRatio = avgVol > 0 ? (double) todayVol / avgVol : 0;
            if (volRatio < 1.5) {
                return Optional.empty();
            }

            if (candles.size() >= 21) {
                double ma20 = candles.subList(0, 20).stream()
                        .mapToDouble(c -> parseDoubleStr(c.getCurPrc()))
                        .filter(p -> p > 0)
                        .average().orElse(0);
                if (ma20 > 0 && todayClose > ma20 * 1.25) {
                    return Optional.empty();
                }
            }

            double strength = redisService.getAvgCntrStrength(stkCd, 5);
            double volSurgePct = Math.max(0.0, (volRatio - 1.0) * 100.0);
            double score = fluRt * 2 + volRatio * 3
                    + (strength > 100 ? (strength - 100) * 0.2 : 0)
                    + (todayHigh >= yearHigh ? 20 : 10);

            double sl = round(yearHigh * 0.99);
            double tp1 = round(todayClose * 1.08);
            double tp2 = round(todayClose * 1.15);

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S10_NEW_HIGH)
                    .signalScore(round(score))
                    .entryPrice(todayClose)
                    .gapPct(round(fluRt))
                    .volRatio(round(volRatio))
                    .volSurgeRt(round(volSurgePct))
                    .cntrStrength(round(strength))
                    .isNewHigh(true)
                    .entryType("new_high_daily")
                    .targetPct(8.0)
                    .target2Pct(15.0)
                    .stopPct(round((sl - todayClose) / todayClose * 100))
                    .tp1Price(tp1)
                    .tp2Price(tp2)
                    .slPrice(sl)
                    .build());
        } catch (Exception e) {
            log.warn("[S10] {} processing failed: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    private String resolveStkNm(String stkCd) {
        try {
            var response = apiService.fetchKa10001(stkCd);
            if (response != null && response.getStkNm() != null && !response.getStkNm().trim().isEmpty()) {
                return response.getStkNm().trim();
            }
        } catch (Exception ignored) {
        }
        try {
            return stockMasterRepository.findByStkCd(stkCd)
                    .map(m -> m.getStkNm() != null ? m.getStkNm().trim() : "")
                    .orElse("");
        } catch (Exception ignored) {
        }
        return "";
    }

    private double parseDoubleStr(String value) {
        try {
            return value == null ? 0 : Double.parseDouble(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private long parseLongStr(String value) {
        try {
            return value == null ? 0 : Long.parseLong(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
