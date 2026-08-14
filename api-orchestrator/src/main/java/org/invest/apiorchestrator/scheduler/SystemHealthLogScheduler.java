package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.SystemHealthSnapshotService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalTime;
import java.util.LinkedHashMap;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class SystemHealthLogScheduler {

    private static final LocalTime START_TIME = LocalTime.of(7, 0);
    private static final LocalTime END_TIME   = LocalTime.of(20, 10);

    private final SystemHealthSnapshotService systemHealthSnapshotService;
    private final ObjectMapper objectMapper;

    @Scheduled(cron = "0 */5 7-20 * * MON-FRI", zone = "Asia/Seoul")
    public void collectAndLogSystemHealth() {
        LocalTime now = KstClock.nowTime();
        if (now.isBefore(START_TIME) || now.isAfter(END_TIME)) {
            return;
        }

        try {
            Map<String, Object> snapshot = systemHealthSnapshotService.buildSnapshot();
            String overall = String.valueOf(snapshot.get("overall"));

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("ts", KstClock.nowOffset().toString());
            payload.put("module", "system_health");
            payload.put("level", "INFO");
            payload.putAll(snapshot);

            String json = objectMapper.writeValueAsString(payload);
            log.info("{}", json);

            if ("CRITICAL".equals(overall)) {
                log.warn("[SystemHealth] CRITICAL — Redis 또는 PostgreSQL DOWN overall={}", overall);
            } else if ("DEGRADED".equals(overall)) {
                log.warn("[SystemHealth] DEGRADED — 일부 서비스 DOWN overall={}", overall);
            }

        } catch (Exception e) {
            log.error("[SystemHealth] 헬스 수집 중 예외 발생: {}", e.getMessage(), e);
        }
    }
}
