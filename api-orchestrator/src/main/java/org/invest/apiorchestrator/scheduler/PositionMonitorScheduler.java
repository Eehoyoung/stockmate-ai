package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.OpenPosition;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.OpenPositionRepository;
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

/**
 * 30초 주기로 활성 포지션의 SL/TP 터치 여부를 체크하고 자동 청산한다.
 * <p>
 * 청산 조건 우선순위:
 * <ol>
 *   <li>SL 터치 → trading_signals LOSS + open_positions DELETE</li>
 *   <li>TP1 터치 (ACTIVE 상태) → PARTIAL_TP (부분 청산)</li>
 *   <li>TP2 터치 (PARTIAL_TP 상태) → trading_signals WIN + open_positions DELETE</li>
 * </ol>
 * NOTE: 14:50 강제 청산(FORCE_CLOSE)은 비활성화 상태. 포지션 종료는 TP/SL/trailing stop에 의해서만 발생한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PositionMonitorScheduler {

    private final OpenPositionRepository openPositionRepository;
    private final RedisMarketDataService redisService;
    private final KiwoomApiService kiwoomApiService;
    private final ObjectMapper objectMapper;

    @Scheduled(fixedDelay = 30_000, initialDelay = 30_000)
    @Transactional
    public void checkPositions() {
        if (!MarketTimeUtil.isMarketHours()) return;

        List<OpenPosition> positions = openPositionRepository.findAllActivePositions();
        if (positions.isEmpty()) return;

        log.debug("[PositionMonitor] 활성 포지션 {}개 점검", positions.size());

        for (OpenPosition pos : positions) {
            try {
                processPosition(pos);
            } catch (Exception e) {
                log.error("[PositionMonitor] 포지션 처리 오류 [id={} {}] – {}",
                        pos.getId(), pos.getStkCd(), e.getMessage(), e);
            }
        }
    }

    private void processPosition(OpenPosition pos) {
        BigDecimal curPrc = getCurrentPrice(pos.getStkCd());
        if (curPrc == null || curPrc.compareTo(BigDecimal.ZERO) <= 0) {
            log.debug("[PositionMonitor] 현재가 조회 실패 – 건너뜀 [{}]", pos.getStkCd());
            return;
        }

        // 1. SL 체크 (14:50 강제 청산 비활성화 — 포지션은 TP/SL에 의해서만 종료)
        if (pos.getSlPrice() != null && curPrc.compareTo(pos.getSlPrice()) <= 0) {
            log.info("[PositionMonitor] SL 청산 [{} {}] curPrc={} sl={}",
                    pos.getStkCd(), pos.getStrategy(), curPrc, pos.getSlPrice());
            closePosition(pos, "SL_HIT", curPrc, TradingSignal.SignalStatus.LOSS);
            return;
        }

        // 2. TP1 체크 (ACTIVE 상태만)
        if ("ACTIVE".equals(pos.getStatus()) && pos.getTp1Price() != null
                && curPrc.compareTo(pos.getTp1Price()) >= 0) {
            log.info("[PositionMonitor] TP1 도달 [{} {}] curPrc={} tp1={}",
                    pos.getStkCd(), pos.getStrategy(), curPrc, pos.getTp1Price());
            markTp1Hit(pos, curPrc);
            return;
        }

        // 3. TP2 체크 (PARTIAL_TP 상태만)
        if ("PARTIAL_TP".equals(pos.getStatus()) && pos.getTp2Price() != null
                && curPrc.compareTo(pos.getTp2Price()) >= 0) {
            log.info("[PositionMonitor] TP2 청산 [{} {}] curPrc={} tp2={}",
                    pos.getStkCd(), pos.getStrategy(), curPrc, pos.getTp2Price());
            closePosition(pos, "TP2_HIT", curPrc, TradingSignal.SignalStatus.WIN);
        }
    }

    // ──── 청산 처리 ────────────────────────────────────────────────────────────

    /**
     * 포지션 청산: open_positions DELETE + trading_signals WIN/LOSS UPDATE.
     * open_positions에는 closed_at/exit_type/exit_price/realized_pnl_pct를 쓰지 않는다.
     */
    private void closePosition(OpenPosition pos, String exitType,
                               BigDecimal curPrc, TradingSignal.SignalStatus signalStatus) {
        BigDecimal entry  = pos.getEntryPrice();
        BigDecimal pnlPct = BigDecimal.ZERO;
        if (entry != null && entry.compareTo(BigDecimal.ZERO) > 0) {
            pnlPct = curPrc.subtract(entry)
                    .divide(entry, 6, RoundingMode.HALF_UP)
                    .multiply(BigDecimal.valueOf(100))
                    .setScale(4, RoundingMode.HALF_UP);
        }
        int holdMin = calcHoldMin(pos.getEntryAt());

        // trading_signals 상태 갱신 (exit 정보 기록)
        TradingSignal signal = pos.getSignal();
        if (signal != null) {
            signal.recordExit(exitType, curPrc, pnlPct, BigDecimal.ZERO, holdMin);
            // recordExit이 내부적으로 signalStatus를 설정하지만,
            // 호출자가 명시한 signalStatus로 덮어쓴다 (예: FORCE_CLOSE → LOSS 명시)
            signal.updateStatus(signalStatus);
        }

        // Telegram 청산 알림 (DELETE 전에 알림 발행)
        pushCloseNotification(pos, exitType, curPrc, pnlPct);

        // open_positions에서 삭제 (CLOSED 상태로 UPDATE하지 않음)
        openPositionRepository.delete(pos);
        log.info("[PositionMonitor] 포지션 DELETE [{} {} {}] exitType={} pnl={}%",
                pos.getId(), pos.getStkCd(), pos.getStrategy(), exitType, pnlPct);
    }

    private void markTp1Hit(OpenPosition pos, BigDecimal curPrc) {
        pos.markTp1Hit(0, 0);

        // TP1 부분 청산 알림
        BigDecimal entry  = pos.getEntryPrice();
        BigDecimal pnlPct = BigDecimal.ZERO;
        if (entry != null && entry.compareTo(BigDecimal.ZERO) > 0) {
            pnlPct = curPrc.subtract(entry)
                    .divide(entry, 6, RoundingMode.HALF_UP)
                    .multiply(BigDecimal.valueOf(100))
                    .setScale(4, RoundingMode.HALF_UP);
        }
        pushCloseNotification(pos, "TP1_HIT", curPrc, pnlPct);
    }

    // ──── 현재가 조회 ──────────────────────────────────────────────────────────

    private BigDecimal getCurrentPrice(String stkCd) {
        // 1차: Redis ws:tick:{stkCd} → cur_prc
        try {
            var tick = redisService.getTickData(stkCd);
            if (tick.isPresent()) {
                Object raw = tick.get().get("cur_prc");
                if (raw != null) {
                    String val = raw.toString().replace(",", "").replace("+", "").replace("-", "");
                    double prc = Double.parseDouble(val);
                    if (prc > 0) return BigDecimal.valueOf(prc).setScale(0, RoundingMode.HALF_UP);
                }
            }
        } catch (Exception e) {
            log.debug("[PositionMonitor] Redis 현재가 파싱 실패 [{}]: {}", stkCd, e.getMessage());
        }

        // 2차: Kiwoom API ka10001
        try {
            String curPrcStr = kiwoomApiService.fetchKa10001(stkCd).getCurPrc();
            if (curPrcStr != null) {
                String val = curPrcStr.replace(",", "").replace("+", "").replace("-", "");
                double prc = Double.parseDouble(val);
                if (prc > 0) return BigDecimal.valueOf(prc).setScale(0, RoundingMode.HALF_UP);
            }
        } catch (Exception e) {
            log.debug("[PositionMonitor] Kiwoom 현재가 조회 실패 [{}]: {}", stkCd, e.getMessage());
        }

        return null;
    }

    // ──── 알림 발행 ────────────────────────────────────────────────────────────

    private void pushCloseNotification(OpenPosition pos, String exitType,
                                       BigDecimal curPrc, BigDecimal pnlPct) {
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("type",            "SELL_SIGNAL");
            payload.put("stk_cd",          pos.getStkCd());
            payload.put("stk_nm",          pos.getStkNm());
            payload.put("strategy",        pos.getStrategy());
            payload.put("exit_type",       exitType);
            payload.put("cur_prc",         curPrc != null ? curPrc.doubleValue() : 0);
            payload.put("entry_price",     pos.getEntryPrice() != null ? pos.getEntryPrice().doubleValue() : 0);
            payload.put("realized_pnl_pct", pnlPct != null ? pnlPct.doubleValue() : 0);
            payload.put("hold_min",        calcHoldMin(pos.getEntryAt()));
            payload.put("sl_price",        pos.getSlPrice() != null ? pos.getSlPrice().doubleValue() : 0);

            redisService.pushScoredQueue(objectMapper.writeValueAsString(payload));
        } catch (Exception e) {
            log.warn("[PositionMonitor] 청산 알림 발행 실패 [{}]: {}", pos.getStkCd(), e.getMessage());
        }
    }

    // ──── 유틸 ─────────────────────────────────────────────────────────────────

    private int calcHoldMin(OffsetDateTime entryAt) {
        if (entryAt == null) return 0;
        return (int) ChronoUnit.MINUTES.between(entryAt, OffsetDateTime.now());
    }
}
