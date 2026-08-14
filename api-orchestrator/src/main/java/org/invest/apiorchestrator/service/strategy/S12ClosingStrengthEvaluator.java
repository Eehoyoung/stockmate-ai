package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Component
@RequiredArgsConstructor
public class S12ClosingStrengthEvaluator {

    private final RedisMarketDataService redisService;
    private final StockMasterRepository stockMasterRepository;
    private final KiwoomApiService kiwoomApiService;

    public Optional<TradingSignalDto> evaluate(String stkCd) {
        try {
            var tickData = redisService.getFreshTick(
                    stkCd, RedisMarketDataService.ENTRY_TICK_POLICY);
            if (tickData == null || !tickData.usable()) {
                return Optional.empty();
            }
            Map<Object, Object> tick = tickData.value();

            double fluRt = parseDouble(tick, "flu_rt");
            double curPrc = parseDouble(tick, "cur_prc");
            if (curPrc <= 0 || fluRt < 4.0 || fluRt > 15.0) {
                return Optional.empty();
            }

            var strengthData = redisService.getFreshStrength(
                    stkCd, 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
            if (strengthData == null || !strengthData.usable() || strengthData.value() == null) {
                return Optional.empty();
            }
            double strength = strengthData.value();
            if (strength < 110.0) return Optional.empty();

            var hogaData = redisService.getFreshHoga(
                    stkCd, RedisMarketDataService.ENTRY_HOGA_POLICY);
            if (hogaData == null || !hogaData.usable()) {
                return Optional.empty();
            }
            double bid = parseDouble(hogaData.value(), "total_buy_bid_req");
            double ask = parseDouble(hogaData.value(), "total_sel_bid_req");
            double bidRatio = ask > 0 ? bid / ask : 0;
            if (bidRatio < 1.5) {
                return Optional.empty();
            }

            ExitFlow exitFlow = fetchExitFlow(stkCd);
            if (exitFlow.isHeavySellExit()) {
                return Optional.empty();
            }

            double score = fluRt * 3 + (strength - 100) * 0.3 + bidRatio * 5;
            if (exitFlow.sellExitQty > exitFlow.buyExitQty && exitFlow.sellExitQty > 0) {
                score -= Math.min(8.0, exitFlow.sellExitQty / Math.max(exitFlow.buyExitQty, 1.0));
            }

            Map<String, Object> extra = new LinkedHashMap<>();
            if (exitFlow.hasData()) {
                extra.put("s12_exit_sell_qty", exitFlow.sellExitQty);
                extra.put("s12_exit_buy_qty", exitFlow.buyExitQty);
            }

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S12_CLOSING)
                    .signalScore(round(score))
                    .entryPrice(curPrc)
                    .gapPct(round(fluRt))
                    .cntrStrength(round(strength))
                    .bidRatio(round(bidRatio))
                    .entryType("closing_strength")
                    .targetPct(6.0)
                    .target2Pct(10.0)
                    .stopPct(-3.0)
                    .tp1Price(round(curPrc * 1.06))
                    .tp2Price(round(curPrc * 1.10))
                    .slPrice(round(curPrc * 0.97))
                    .extra(extra)
                    .build());
        } catch (Exception e) {
            log.warn("[S12] {} processing failed: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    private ExitFlow fetchExitFlow(String stkCd) {
        try {
            var response = kiwoomApiService.fetchKa10053(stkCd);
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return ExitFlow.empty();
            }
            long sellQty = 0;
            long buyQty = 0;
            for (var item : response.getItems()) {
                sellQty += parseLong(item.getSellQty());
                buyQty += parseLong(item.getBuyQty());
            }
            return new ExitFlow(sellQty, buyQty);
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

    private double parseDouble(Map<Object, Object> map, String key) {
        try {
            return Double.parseDouble(map.getOrDefault(key, "0").toString()
                    .replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private long parseLong(String value) {
        try {
            return value == null ? 0 : Long.parseLong(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private record ExitFlow(long sellExitQty, long buyExitQty) {
        static ExitFlow empty() {
            return new ExitFlow(0, 0);
        }

        boolean hasData() {
            return sellExitQty > 0 || buyExitQty > 0;
        }

        boolean isHeavySellExit() {
            return sellExitQty >= 100 && sellExitQty > Math.max(buyExitQty * 5, 50);
        }
    }
}
