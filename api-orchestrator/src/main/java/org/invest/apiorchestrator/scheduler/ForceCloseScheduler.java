package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.service.OvernightScoringService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.SignalService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class ForceCloseScheduler {

    private final SignalService signalService;
    private final RedisMarketDataService redisService;
    private final OvernightScoringService overnightScoringService;
    private final ObjectMapper objectMapper;

    /**
     * 14:50 – 장마감 30분 전 미청산 포지션 처리.
     *
     * 흐름:
     *   1) 오버나잇 규칙 점수 계산 (OvernightScoringService)
     *   2) 점수 >= 65 → overnight_eval_queue 로 발행 → Python overnight_worker → Claude 최종 판단
     *   3) 점수 < 65  → 즉시 FORCE_CLOSE (기존 동작)
     */
    @Scheduled(cron = "0 50 14 * * MON-FRI")
    public void notifyForceClose() {
        log.info("=== 강제 청산 / 오버나잇 평가 시작 (14:50) ===");
        try {
            List<TradingSignal> activeSignals =
                    signalService.getTodaySignals().stream()
                            .filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.SENT
                                    || s.getSignalStatus() == TradingSignal.SignalStatus.EXECUTED)
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

    /** 즉시 강제 청산 알림 → telegram_queue */
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
    }
}
