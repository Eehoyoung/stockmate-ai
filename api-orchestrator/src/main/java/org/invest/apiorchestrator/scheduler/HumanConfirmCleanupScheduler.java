package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class HumanConfirmCleanupScheduler {

    private final JdbcTemplate jdbcTemplate;

    @Scheduled(cron = "0 */10 * * * *", zone = "Asia/Seoul")
    public void deleteExpiredHumanConfirmRequests() {
        Integer deleted = jdbcTemplate.queryForObject(
                """
                WITH expired AS (
                    DELETE FROM human_confirm_requests
                    WHERE expires_at <= NOW()
                    RETURNING id
                )
                SELECT COUNT(*) FROM expired
                """,
                Integer.class
        );

        if (deleted != null && deleted > 0) {
            log.info("[HumanConfirmCleanup] expired rows deleted={}", deleted);
        }
    }
}
