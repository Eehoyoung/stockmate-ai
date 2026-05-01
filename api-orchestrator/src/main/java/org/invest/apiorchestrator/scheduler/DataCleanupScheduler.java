package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.repository.KiwoomTokenRepository;
import org.invest.apiorchestrator.repository.OvernightEvaluationRepository;
import org.invest.apiorchestrator.repository.WsTickDataRepository;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataCleanupScheduler {

    private final WsTickDataRepository tickDataRepository;
    private final KiwoomTokenRepository kiwoomTokenRepository;
    private final OvernightEvaluationRepository overnightEvaluationRepository;
    private final JdbcTemplate jdbcTemplate;

    @Value("${cleanup.ws-tick-data.delete-enabled:false}")
    private boolean wsTickDataDeleteEnabled;

    /**
     * 매일 23:30 - 오래된 데이터 일괄 정리
     * 1) ws_tick_data  3일 이상
     * 2) ai_cancel_signal    30일 이상
     * 3) rule_cancel_signal  30일 이상
     * 4) overnight_evaluations 90일 이상
     * 5) kiwoom_tokens is_active=false 이고 7일 이상 된 토큰
     */
    @Scheduled(cron = "0 30 23 * * *", zone = "Asia/Seoul")
    @Transactional
    public void cleanupOldData() {
        cleanupOldTickData();
        cleanupAiCancelSignal();
        cleanupRuleCancelSignal();
        cleanupOvernightEvaluations();
        cleanupInactiveKiwoomTokens();
    }

    private void cleanupOldTickData() {
        if (!wsTickDataDeleteEnabled) {
            log.info("[DataCleanup] ws_tick_data delete skipped: cleanup.ws-tick-data.delete-enabled=false");
            return;
        }
        LocalDateTime cutoff = KstClock.now().minusDays(3);
        try {
            int deleted = tickDataRepository.deleteOldTickData(cutoff);
            log.info("[DataCleanup] ws_tick_data 정리: {}건", deleted);
        } catch (Exception e) {
            log.error("[DataCleanup] ws_tick_data 정리 실패: {}", e.getMessage());
        }
    }

    private void cleanupAiCancelSignal() {
        try {
            int deleted = jdbcTemplate.update(
                    "DELETE FROM ai_cancel_signal WHERE created_at < NOW() - INTERVAL '30 days'"
            );
            log.info("[DataCleanup] ai_cancel_signal 정리: {}건", deleted);
        } catch (Exception e) {
            log.error("[DataCleanup] ai_cancel_signal 정리 실패: {}", e.getMessage());
        }
    }

    private void cleanupRuleCancelSignal() {
        try {
            int deleted = jdbcTemplate.update(
                    "DELETE FROM rule_cancel_signal WHERE created_at < NOW() - INTERVAL '30 days'"
            );
            log.info("[DataCleanup] rule_cancel_signal 정리: {}건", deleted);
        } catch (Exception e) {
            log.error("[DataCleanup] rule_cancel_signal 정리 실패: {}", e.getMessage());
        }
    }

    private void cleanupOvernightEvaluations() {
        OffsetDateTime cutoff = KstClock.nowOffset().minusDays(90);
        try {
            int deleted = overnightEvaluationRepository.deleteOldEvaluations(cutoff);
            log.info("[DataCleanup] overnight_evaluations 정리: {}건", deleted);
        } catch (Exception e) {
            log.error("[DataCleanup] overnight_evaluations 정리 실패: {}", e.getMessage());
        }
    }

    private void cleanupInactiveKiwoomTokens() {
        LocalDateTime cutoff = KstClock.now().minusDays(7);
        try {
            int deleted = kiwoomTokenRepository.deleteOldInactiveTokens(cutoff);
            log.info("[DataCleanup] kiwoom_tokens(inactive) 정리: {}건", deleted);
        } catch (Exception e) {
            log.error("[DataCleanup] kiwoom_tokens 정리 실패: {}", e.getMessage());
        }
    }
}
