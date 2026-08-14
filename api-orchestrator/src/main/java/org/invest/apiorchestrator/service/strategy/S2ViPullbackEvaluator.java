package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Optional;

@Slf4j
@Component
@RequiredArgsConstructor
public class S2ViPullbackEvaluator {

    private final RedisMarketDataService redisService;
    private final StockMasterRepository stockMasterRepository;
    private final KiwoomApiService kiwoomApiService;

    public Optional<TradingSignalDto> evaluate(String stkCd, double viPrice, boolean isDynamic) {
        try {
            var tickData = redisService.getFreshTick(
                    stkCd, RedisMarketDataService.ENTRY_TICK_POLICY);
            if (tickData == null || !tickData.usable()) {
                return Optional.empty();
            }

            double curPrice = parseDouble(tickData.value(), "cur_prc");
            if (curPrice <= 0 || viPrice <= 0) {
                return Optional.empty();
            }

            double pullbackPct = (curPrice - viPrice) / viPrice * 100;
            if (pullbackPct < -3.0 || pullbackPct > -1.0) {
                return Optional.empty();
            }

            var strengthData = redisService.getFreshStrength(
                    stkCd, 3, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
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
            if (bidRatio < 1.3) {
                return Optional.empty();
            }

            double score = Math.abs(pullbackPct) * 10 + (strength - 100) * 0.3
                    + bidRatio * 5 + (isDynamic ? 10 : 0);

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S2_VI_PULLBACK)
                    .signalScore(round(score))
                    .entryPrice(curPrice)
                    .pullbackPct(round(pullbackPct))
                    .cntrStrength(round(strength))
                    .bidRatio(round(bidRatio))
                    .entryType("vi_pullback")
                    .targetPct(6.5)
                    .target2Pct(9.5)
                    .stopPct(-2.0)
                    .tp1Price(round(curPrice * 1.065))
                    .tp2Price(round(curPrice * 1.095))
                    .slPrice(round(curPrice * 0.98))
                    .build());
        } catch (Exception e) {
            log.warn("[S2] {} processing failed: {}", stkCd, e.getMessage());
            return Optional.empty();
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

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
