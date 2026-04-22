package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.util.MarketTimeUtil;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class PositionMonitorScheduler {

    private static final boolean JAVA_POSITION_MONITOR_ENABLED =
            Boolean.parseBoolean(System.getenv().getOrDefault("JAVA_POSITION_MONITOR_ENABLED", "false"));

    private final TradingSignalRepository tradingSignalRepository;
    private final RedisMarketDataService redisService;
    private final KiwoomApiService kiwoomApiService;
    private final ObjectMapper objectMapper;

    @Scheduled(fixedDelay = 30_000, initialDelay = 30_000)
    @Transactional
    public void checkPositions() {
        if (!JAVA_POSITION_MONITOR_ENABLED || !MarketTimeUtil.isMarketHours()) {
            return;
        }

        List<TradingSignal> positions = tradingSignalRepository.findAllActivePositions();
        if (positions.isEmpty()) {
            return;
        }

        for (TradingSignal signal : positions) {
            try {
                processPosition(signal);
            } catch (Exception e) {
                log.error("[PositionMonitor] position processing failed [id={} {}]: {}",
                        signal.getId(), signal.getStkCd(), e.getMessage(), e);
            }
        }
    }

    private void processPosition(TradingSignal signal) {
        BigDecimal curPrc = getCurrentPrice(signal.getStkCd());
        if (curPrc == null || curPrc.compareTo(BigDecimal.ZERO) <= 0) {
            return;
        }

        if (signal.getSlPrice() != null
                && curPrc.compareTo(BigDecimal.valueOf(signal.getSlPrice()).setScale(0, RoundingMode.HALF_UP)) <= 0) {
            closePosition(signal, "SL_HIT", curPrc, TradingSignal.SignalStatus.LOSS);
            return;
        }

        if ("ACTIVE".equals(signal.getPositionStatus()) && signal.getTp1Price() != null
                && curPrc.compareTo(BigDecimal.valueOf(signal.getTp1Price()).setScale(0, RoundingMode.HALF_UP)) >= 0) {
            markTp1Hit(signal, curPrc);
            return;
        }

        if ("PARTIAL_TP".equals(signal.getPositionStatus()) && signal.getTp2Price() != null
                && curPrc.compareTo(BigDecimal.valueOf(signal.getTp2Price()).setScale(0, RoundingMode.HALF_UP)) >= 0) {
            closePosition(signal, "TP2_HIT", curPrc, TradingSignal.SignalStatus.WIN);
        }
    }

    private void closePosition(TradingSignal signal, String exitType,
                               BigDecimal curPrc, TradingSignal.SignalStatus signalStatus) {
        BigDecimal pnlPct = calculatePnlPct(signal.getEntryPrice(), curPrc);
        int holdMin = calcHoldMin(signal.getEntryAt());

        signal.recordExit(exitType, curPrc, pnlPct, BigDecimal.ZERO, holdMin);
        signal.updateStatus(signalStatus);
        pushCloseNotification(signal, exitType, curPrc, pnlPct);
    }

    private void markTp1Hit(TradingSignal signal, BigDecimal curPrc) {
        signal.markTp1Hit(0, 0, curPrc);
        pushCloseNotification(signal, "TP1_HIT", curPrc, calculatePnlPct(signal.getEntryPrice(), curPrc));
    }

    private BigDecimal calculatePnlPct(Double entryPrice, BigDecimal curPrc) {
        if (entryPrice == null || entryPrice <= 0) {
            return BigDecimal.ZERO;
        }
        BigDecimal entry = BigDecimal.valueOf(entryPrice).setScale(0, RoundingMode.HALF_UP);
        return curPrc.subtract(entry)
                .divide(entry, 6, RoundingMode.HALF_UP)
                .multiply(BigDecimal.valueOf(100))
                .setScale(4, RoundingMode.HALF_UP);
    }

    private BigDecimal getCurrentPrice(String stkCd) {
        try {
            var tick = redisService.getTickData(stkCd);
            if (tick.isPresent()) {
                Object raw = tick.get().get("cur_prc");
                if (raw != null) {
                    String val = raw.toString().replace(",", "").replace("+", "").replace("-", "");
                    double prc = Double.parseDouble(val);
                    if (prc > 0) {
                        return BigDecimal.valueOf(prc).setScale(0, RoundingMode.HALF_UP);
                    }
                }
            }
        } catch (Exception e) {
            log.debug("[PositionMonitor] redis price lookup failed [{}]: {}", stkCd, e.getMessage());
        }

        try {
            String curPrcStr = kiwoomApiService.fetchKa10001(stkCd).getCurPrc();
            if (curPrcStr != null) {
                String val = curPrcStr.replace(",", "").replace("+", "").replace("-", "");
                double prc = Double.parseDouble(val);
                if (prc > 0) {
                    return BigDecimal.valueOf(prc).setScale(0, RoundingMode.HALF_UP);
                }
            }
        } catch (Exception e) {
            log.debug("[PositionMonitor] kiwoom price lookup failed [{}]: {}", stkCd, e.getMessage());
        }

        return null;
    }

    private void pushCloseNotification(TradingSignal signal, String exitType,
                                       BigDecimal curPrc, BigDecimal pnlPct) {
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("type", "SELL_SIGNAL");
            payload.put("stk_cd", signal.getStkCd());
            payload.put("stk_nm", signal.getStkNm());
            payload.put("strategy", signal.getStrategy().name());
            payload.put("exit_type", exitType);
            payload.put("cur_prc", curPrc != null ? curPrc.doubleValue() : 0);
            payload.put("entry_price", signal.getEntryPrice() != null ? signal.getEntryPrice() : 0);
            payload.put("realized_pnl_pct", pnlPct != null ? pnlPct.doubleValue() : 0);
            payload.put("hold_min", calcHoldMin(signal.getEntryAt()));
            payload.put("sl_price", signal.getSlPrice() != null ? signal.getSlPrice() : 0);
            redisService.pushScoredQueue(objectMapper.writeValueAsString(payload));
        } catch (Exception e) {
            log.warn("[PositionMonitor] close notification failed [{}]: {}", signal.getStkCd(), e.getMessage());
        }
    }

    private int calcHoldMin(OffsetDateTime entryAt) {
        if (entryAt == null) {
            return 0;
        }
        return (int) ChronoUnit.MINUTES.between(entryAt, OffsetDateTime.now());
    }
}
