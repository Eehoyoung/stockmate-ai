package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.OpenPosition;
import org.invest.apiorchestrator.domain.RiskEvent;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.OpenPositionRepository;
import org.invest.apiorchestrator.repository.RiskEventRepository;
import org.invest.apiorchestrator.service.OvernightScoringService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.SignalService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Slf4j
@Component
@RequiredArgsConstructor
public class ForceCloseScheduler {

    private final SignalService signalService;
    private final RedisMarketDataService redisService;
    private final OvernightScoringService overnightScoringService;
    private final ObjectMapper objectMapper;
    private final RiskEventRepository riskEventRepository;
    private final OpenPositionRepository openPositionRepository;

    /**
     * 스윙/종가 전략: 14:50 강제청산 제외 대상.
     * Python strategy_runner.py _SWING_STRATEGIES 와 동기화 유지.
     */
    private static final Set<TradingSignal.StrategyType> SWING_STRATEGIES = EnumSet.of(
            TradingSignal.StrategyType.S8_GOLDEN_CROSS,    // 중기 추세 (5~10일)
            TradingSignal.StrategyType.S9_PULLBACK_SWING,  // 스윙 눌림목 (5~10일)
            TradingSignal.StrategyType.S10_NEW_HIGH,        // 신고가 스윙 (익일 갭업 기대)
            TradingSignal.StrategyType.S11_FRGN_CONT,       // 외인 연속 매수 스윙
            TradingSignal.StrategyType.S12_CLOSING,         // 종가 전략: 15:20 진입 → 장마감 자동청산
            TradingSignal.StrategyType.S13_BOX_BREAKOUT,    // 박스권 돌파 스윙 (1~3일)
            TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE, // 과매도 반등 스윙
            TradingSignal.StrategyType.S15_MOMENTUM_ALIGN   // 다중 모멘텀 정렬 (5~10일)
    );

    /**
     * 14:50 – 장마감 30분 전 당일 전략 포지션 처리.
     *
     * 흐름:
     *   1) 스윙/종가 전략 제외 (당일 강제청산 대상 아님)
     *   2) 오버나잇 규칙 점수 계산 (OvernightScoringService)
     *   3) 점수 >= 65 → overnight_eval_queue 로 발행 → Python overnight_worker → Claude 최종 판단
     *   4) 점수 < 65  → 즉시 FORCE_CLOSE
     */
    @Scheduled(cron = "0 50 14 * * MON-FRI")
    @Transactional
    public void notifyForceClose() {
        log.info("=== 강제 청산 / 오버나잇 평가 시작 (14:50) ===");
        try {
            List<TradingSignal> activeSignals =
                    signalService.getTodaySignals().stream()
                            .filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.SENT
                                    || s.getSignalStatus() == TradingSignal.SignalStatus.EXECUTED)
                            .filter(s -> !SWING_STRATEGIES.contains(s.getStrategy()))
                            .toList();

            if (activeSignals.isEmpty()) {
                log.info("청산/오버나잇 평가 대상 없음");
                return;
            }

            int forceCloseCount  = 0;
            int overnightCount   = 0;

            for (TradingSignal signal : activeSignals) {
                try {
                    double overnightScore = overnightScoringService.calcOvernightScore(signal);
                    log.info("[오버나잇스코어] {} {} score={}",
                            signal.getStkCd(), signal.getStrategy(), overnightScore);

                    if (overnightScore >= OvernightScoringService.OVERNIGHT_EVAL_THRESHOLD) {
                        pushOvernightEvalQueue(signal, overnightScore);
                        overnightCount++;
                    } else {
                        pushForceClose(signal);
                        forceCloseCount++;
                    }
                } catch (Exception e) {
                    log.error("처리 실패 [{}] – 강제청산으로 처리: {}", signal.getStkCd(), e.getMessage());
                    try {
                        pushForceClose(signal);
                    } catch (Exception ex) {
                        log.error("강제청산 알림 실패 [{}]: {}", signal.getStkCd(), ex.getMessage());
                    }
                    forceCloseCount++;
                }
            }

            log.warn("=== 결과: 즉시강제청산={}건, Claude오버나잇평가={}건 ===",
                    forceCloseCount, overnightCount);

        } catch (Exception e) {
            log.error("강제 청산 스케줄 오류: {}", e.getMessage());
        }
    }

    // ──── 내부 헬퍼 ────────────────────────────────────────────────

    /** 즉시 강제 청산 알림 → telegram_queue + OpenPosition 청산 + RiskEvent 기록 */
    private void pushForceClose(TradingSignal signal) throws Exception {
        String msg = objectMapper.writeValueAsString(Map.of(
                "type",     "FORCE_CLOSE",
                "stk_cd",   signal.getStkCd(),
                "stk_nm",   signal.getStkNm() != null ? signal.getStkNm() : "",
                "strategy", signal.getStrategy().name(),
                "message",  String.format(
                        "⚠️ 강제 청산 [%s] %s %s\n장마감 30분 전 전량 시장가 청산",
                        signal.getStrategy().name(),
                        signal.getStkCd(),
                        signal.getStkNm() != null ? signal.getStkNm() : "")
        ));
        redisService.pushTelegramQueue(msg);
        log.info("[ForceClose] 알림 발행 [{}]", signal.getStkCd());

        // OpenPosition 청산 처리
        closeOpenPosition(signal);

        // RiskEvent 감사 로그
        logRiskEvent("FORCE_CLOSE_ISSUED", signal.getStkCd(), signal.getStrategy().name(),
                signal.getId(), null, null, "오버나잇 점수 미달 – 강제청산", "FORCE_CLOSE 알림 발행");
    }

    /** OpenPosition 청산 처리 – 보유 포지션이 있으면 FORCE_CLOSE 로 마킹 */
    private void closeOpenPosition(TradingSignal signal) {
        try {
            openPositionRepository.findBySignalId(signal.getId()).ifPresent(pos -> {
                if (pos.isActive()) {
                    int holdMin = signal.getCreatedAt() != null
                            ? (int) Duration.between(signal.getCreatedAt(), java.time.LocalDateTime.now()).toMinutes()
                            : 0;
                    pos.close("FORCE_CLOSE", null, null, null, holdMin);
                    openPositionRepository.save(pos);
                    log.info("[ForceClose] OpenPosition 청산 완료 [{}]", signal.getStkCd());
                }
            });
        } catch (Exception e) {
            log.warn("[ForceClose] OpenPosition 청산 실패 (무시): {}", e.getMessage());
        }
    }

    /** RiskEvent 감사 로그 저장 */
    private void logRiskEvent(String eventType, String stkCd, String strategy,
                               Long signalId, BigDecimal threshold, BigDecimal actual,
                               String description, String actionTaken) {
        try {
            riskEventRepository.save(RiskEvent.builder()
                    .eventType(eventType)
                    .stkCd(stkCd)
                    .strategy(strategy)
                    .signalId(signalId)
                    .thresholdValue(threshold)
                    .actualValue(actual)
                    .description(description)
                    .actionTaken(actionTaken)
                    .build());
        } catch (Exception e) {
            log.warn("[RiskEvent] 저장 실패 (무시): {}", e.getMessage());
        }
    }

    /** Claude 오버나잇 평가 큐에 발행 → overnight_eval_queue */
    private void pushOvernightEvalQueue(TradingSignal signal, double overnightScore) throws Exception {
        Map<String, Object> payload = new HashMap<>();
        payload.put("type",            "OVERNIGHT_EVAL");
        payload.put("signal_id",       signal.getId());
        payload.put("stk_cd",          signal.getStkCd());
        payload.put("stk_nm",          signal.getStkNm() != null ? signal.getStkNm() : "");
        payload.put("strategy",        signal.getStrategy().name());
        payload.put("overnight_score", overnightScore);
        payload.put("entry_price",     signal.getEntryPrice());
        payload.put("target_price",    signal.getTargetPrice());
        payload.put("stop_price",      signal.getStopPrice());
        payload.put("signal_score",    signal.getSignalScore());
        payload.put("gap_pct",         signal.getGapPct());
        payload.put("cntr_strength",   signal.getCntrStrength());
        payload.put("vol_ratio",       signal.getVolRatio());
        payload.put("theme_name",      signal.getThemeName());

        String msg = objectMapper.writeValueAsString(payload);
        redisService.pushOvernightEvalQueue(msg);
        log.info("[OvernightEval] Claude 평가 큐 발행 [{}] score={}", signal.getStkCd(), overnightScore);

        // OpenPosition 오버나잇 마킹
        try {
            openPositionRepository.findBySignalId(signal.getId()).ifPresent(pos -> {
                if (pos.isActive()) {
                    pos.markOvernight("PENDING", BigDecimal.valueOf(overnightScore));
                    openPositionRepository.save(pos);
                }
            });
        } catch (Exception e) {
            log.warn("[OvernightEval] OpenPosition 오버나잇 마킹 실패 (무시): {}", e.getMessage());
        }
    }
}
