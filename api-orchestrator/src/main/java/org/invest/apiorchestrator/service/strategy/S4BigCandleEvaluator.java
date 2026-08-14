package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.KiwoomRestFallbackService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Component
@RequiredArgsConstructor
public class S4BigCandleEvaluator {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;
    private final StockMasterRepository stockMasterRepository;
    private final KiwoomApiService kiwoomApiService;
    private final KiwoomRestFallbackService restFallbackService;

    public Optional<TradingSignalDto> evaluate(String stkCd) {
        try {
            var resp = apiService.fetchKa10080(stkCd, "5", KstClock.today());

            if (resp.getCandles() == null || resp.getCandles().size() < 10) {
                return Optional.empty();
            }

            var candles = resp.getCandles();
            var cur = candles.get(0);

            double o = parseDoubleStr(cur.getOpenPric());
            double h = parseDoubleStr(cur.getHighPric());
            double l = parseDoubleStr(cur.getLowPric());
            double c = parseDoubleStr(cur.getCurPrc());
            long vol = parseLongStr(cur.getTrdeQty());

            if (o <= 0 || h <= l || c <= o) {
                return Optional.empty();
            }

            double candleRange = h - l;
            double body = c - o;
            double bodyRatio = candleRange > 0 ? body / candleRange : 0;
            double gainPct = (c - o) / o * 100;

            if (bodyRatio < 0.7 || gainPct < 3.0) {
                return Optional.empty();
            }

            double avgPrevVol = candles.subList(1, Math.min(6, candles.size())).stream()
                    .mapToLong(can -> parseLongStr(can.getTrdeQty()))
                    .average().orElse(0);
            double volRatio = avgPrevVol > 0 ? vol / avgPrevVol : 0;
            if (volRatio < 5.0) {
                return Optional.empty();
            }

            var freshStrength = redisService.getFreshStrength(
                    stkCd, 3, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
            Double strength = freshStrength.usable() ? freshStrength.value() : null;
            String strengthSource = strength != null ? "REDIS_FRESH" : null;
            if (strength == null) {
                var fallback = restFallbackService.fetchStrengthDetailed(stkCd);
                strengthSource = fallback.status().name();
                strength = fallback.value()
                        .map(KiwoomRestFallbackService.StrengthSnapshot::effectiveStrength)
                        .orElse(null);
            }
            if (strength == null || strength < 120.0) {
                return Optional.empty();
            }

            double max20d = candles.subList(1, Math.min(97, candles.size())).stream()
                    .mapToDouble(can -> parseDoubleStr(can.getHighPric()))
                    .max().orElse(0);
            boolean isNewHigh = h >= max20d;

            ExitFlow exitFlow = fetchExitFlow(stkCd);
            if (exitFlow.isHeavySellExit()) {
                return Optional.empty();
            }

            double score = gainPct * 3 + bodyRatio * 10 + volRatio * 0.5
                    + (strength - 100) * 0.2 + (isNewHigh ? 20 : 0);
            if (exitFlow.sellExitQty > exitFlow.buyExitQty && exitFlow.sellExitQty > 0) {
                score -= Math.min(10.0, exitFlow.sellExitQty / Math.max(exitFlow.buyExitQty, 1.0));
            }

            Map<String, Object> extra = new LinkedHashMap<>();
            extra.put("s4_strength_source", strengthSource);
            if (exitFlow.hasData()) {
                extra.put("s4_exit_sell_qty", exitFlow.sellExitQty);
                extra.put("s4_exit_buy_qty", exitFlow.buyExitQty);
                extra.put("s4_exit_sell_broker", exitFlow.sellBroker);
                extra.put("s4_exit_buy_broker", exitFlow.buyBroker);
            }

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S4_BIG_CANDLE)
                    .signalScore(round(score))
                    .entryPrice(c)
                    .gapPct(round(gainPct))
                    .volRatio(round(volRatio))
                    .cntrStrength(round(strength))
                    .bodyRatio(round(bodyRatio))
                    .isNewHigh(isNewHigh)
                    .entryType("big_candle_breakout")
                    .targetPct(6.0)
                    .target2Pct(9.0)
                    .stopPct(-3.0)
                    .tp1Price(round(c * 1.06))
                    .tp2Price(round(c * 1.09))
                    .slPrice(l > 0 ? round(Math.max(l * 0.99, c * 0.97)) : round(c * 0.97))
                    .extra(extra)
                    .build());
        } catch (Exception e) {
            log.warn("[S4] {} processing failed: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    private ExitFlow fetchExitFlow(String stkCd) {
        try {
            var response = apiService.fetchKa10053(stkCd);
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return ExitFlow.empty();
            }
            long sellQty = 0;
            long buyQty = 0;
            String sellBroker = "";
            String buyBroker = "";
            for (var item : response.getItems()) {
                long itemSell = parseLongStr(item.getSellQty());
                long itemBuy = parseLongStr(item.getBuyQty());
                sellQty += itemSell;
                buyQty += itemBuy;
                if (sellBroker.isEmpty() && item.getSelUpperScesnOri() != null) {
                    sellBroker = item.getSelUpperScesnOri();
                }
                if (buyBroker.isEmpty() && item.getBuyUpperScesnOri() != null) {
                    buyBroker = item.getBuyUpperScesnOri();
                }
            }
            return new ExitFlow(sellQty, buyQty, sellBroker, buyBroker);
        } catch (Exception ignored) {
            return ExitFlow.empty();
        }
    }

    private String resolveStkNm(String stkCd) {
        try {
            var tickOpt = redisService.getTickData(stkCd);
            if (tickOpt.isPresent()) {
                Object nm = tickOpt.get().get("stk_nm");
                if (nm != null && !nm.toString().trim().isEmpty()) {
                    return nm.toString().trim();
                }
            }
        } catch (Exception ignored) {
        }
        try {
            var response = kiwoomApiService.fetchKa10001(stkCd);
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

    private record ExitFlow(long sellExitQty, long buyExitQty, String sellBroker, String buyBroker) {
        static ExitFlow empty() {
            return new ExitFlow(0, 0, "", "");
        }

        boolean hasData() {
            return sellExitQty > 0 || buyExitQty > 0;
        }

        boolean isHeavySellExit() {
            return sellExitQty >= 100 && sellExitQty > Math.max(buyExitQty * 5, 50);
        }
    }
}
