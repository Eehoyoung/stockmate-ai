package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Component
@RequiredArgsConstructor
public class S1GapOpeningScanner implements StrategyScanner {

    private final RedisMarketDataService redisService;
    private final StockMasterRepository stockMasterRepository;
    private final KiwoomApiService kiwoomApiService;

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S1_GAP_OPEN;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<String> candidates = context.candidates();
        MDC.put("strategy", "S1_GAP_OPEN");
        log.info("[S1] gap opening scanner started - candidates={}", candidates.size());
        List<TradingSignalDto> results = new ArrayList<>();

        for (String stkCd : candidates) {
            try {
                double prevClose;
                double expPrice;
                var expectedData = redisService.getFreshExpected(
                        stkCd, RedisMarketDataService.ENTRY_EXPECTED_POLICY);
                if (expectedData != null && expectedData.usable()) {
                    Map<Object, Object> exp = expectedData.value();
                    prevClose = parseDouble(exp, "pred_pre_pric");
                    expPrice = parseDouble(exp, "exp_cntr_pric");
                } else {
                    var tickData = redisService.getFreshTick(
                            stkCd, RedisMarketDataService.ENTRY_TICK_POLICY);
                    if (tickData == null || !tickData.usable()) {
                        continue;
                    }
                    Map<Object, Object> tick = tickData.value();
                    prevClose = parseDouble(tick, "pred_pre");
                    expPrice = parseDouble(tick, "cur_prc");
                }
                if (prevClose <= 0 || expPrice <= 0) {
                    continue;
                }

                double gapPct = (expPrice - prevClose) / prevClose * 100;
                if (gapPct < 3.0 || gapPct > 15.0) {
                    continue;
                }

                var strengthData = redisService.getFreshStrength(
                        stkCd, 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
                double strength = 100.0;
                if (strengthData != null && strengthData.state() == RedisMarketDataService.FreshnessState.STALE) {
                    continue;
                }
                // S1 keeps the legacy neutral fallback when no strength samples exist.
                if (strengthData != null && strengthData.usable() && strengthData.value() != null) {
                    strength = strengthData.value();
                    if (strength < 130.0) {
                        continue;
                    }
                }

                var hogaData = redisService.getFreshHoga(
                        stkCd, RedisMarketDataService.ENTRY_HOGA_POLICY);
                if (hogaData == null || !hogaData.usable()) {
                    continue;
                }
                double bid = parseDouble(hogaData.value(), "total_buy_bid_req");
                double ask = parseDouble(hogaData.value(), "total_sel_bid_req");
                double bidRatio = ask > 0 ? bid / ask : 0;
                if (bidRatio < 1.3) {
                    continue;
                }

                double score = gapPct * 0.5 + (strength - 100) * 0.3 + bidRatio * 0.2;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(resolveStkNm(stkCd))
                        .strategy(TradingSignal.StrategyType.S1_GAP_OPEN)
                        .signalScore(round(score))
                        .entryPrice(expPrice)
                        .gapPct(round(gapPct))
                        .cntrStrength(round(strength))
                        .bidRatio(round(bidRatio))
                        .entryType("opening_expected_price")
                        .targetPct(5.0)
                        .target2Pct(9.0)
                        .stopPct(-2.0)
                        .tp1Price(round(expPrice * 1.05))
                        .tp2Price(round(expPrice * 1.09))
                        .slPrice(round(expPrice * 0.98))
                        .build());
            } catch (Exception e) {
                log.warn("[S1] {} processing failed: {}", stkCd, e.getMessage());
            }
        }

        MDC.remove("strategy");
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5)
                .collect(Collectors.toList());
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

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
