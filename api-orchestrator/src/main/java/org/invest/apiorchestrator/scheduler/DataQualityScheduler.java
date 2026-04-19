package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.util.MarketTimeUtil;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataQualityScheduler {

    private static final int QUEUE_DEPTH_WARN = 50;
    private static final int ERROR_QUEUE_WARN = 5;
    private static final long WS_ALERT_COOLDOWN_MS = 10 * 60 * 1000L;
    private static final long HEARTBEAT_STALE_SEC = 60L;
    private static final LocalTime WS_GRACE_END = LocalTime.of(9, 10);
    private static final String KEY_WS_RECONNECT_COUNT = "monitor:ws_reconnect_count";

    private final AtomicLong lastWsAlertMs = new AtomicLong(0);

    private final RedisMarketDataService redisService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    @Scheduled(fixedDelay = 60_000, initialDelay = 120_000)
    public void checkDataQuality() {
        List<String> alerts = new ArrayList<>();

        try {
            checkWebSocketHealth(alerts);
        } catch (Exception e) {
            log.debug("[DataQuality] WS health check failed: {}", e.getMessage());
        }

        try {
            long qDepth = redisService.getTelegramQueueDepth();
            if (qDepth > QUEUE_DEPTH_WARN) {
                alerts.add(String.format("telegram_queue backlog: %d", qDepth));
                log.warn("[DataQuality] telegram_queue backlog {}", qDepth);
            }
        } catch (Exception e) {
            log.debug("[DataQuality] telegram queue check failed: {}", e.getMessage());
        }

        try {
            long errCount = redisService.getErrorQueueDepth();
            if (errCount > ERROR_QUEUE_WARN) {
                alerts.add(String.format("AI error_queue accumulated: %d", errCount));
                log.warn("[DataQuality] error_queue accumulated {}", errCount);
            }
        } catch (Exception e) {
            log.debug("[DataQuality] error_queue check failed: {}", e.getMessage());
        }

        if (!alerts.isEmpty()) {
            publishSystemAlert(alerts);
        }
    }

    private void checkWebSocketHealth(List<String> alerts) {
        LocalTime now = LocalTime.now();
        if (now.isBefore(WS_GRACE_END)) {
            log.debug("[DataQuality] skip tick check before grace end {}", WS_GRACE_END);
            return;
        }

        Map<Object, Object> pyHeartbeat = redis.opsForHash().entries("ws:py_heartbeat");
        boolean heartbeatMissing = pyHeartbeat.isEmpty();
        long heartbeatAgeSec = heartbeatMissing ? Long.MAX_VALUE : heartbeatAgeSeconds(pyHeartbeat);
        boolean heartbeatStale = heartbeatMissing || heartbeatAgeSec > HEARTBEAT_STALE_SEC;

        if (!heartbeatStale) {
            List<String> candidates = resolveMonitoredCodes();
            if (!candidates.isEmpty()) {
                long missing = candidates.stream()
                        .filter(code -> redisService.getTickData(code).isEmpty())
                        .count();
                double missingRatio = (double) missing / candidates.size() * 100.0;
                if (missingRatio >= 85.0) {
                    log.debug("[DataQuality] ignore noisy tick-missing signal {}/{} ({}%) with fresh heartbeat",
                            missing, candidates.size(), String.format("%.1f", missingRatio));
                }
            }
            return;
        }

        if (!MarketTimeUtil.isTradingActive()) {
            log.info("[DataQuality] skip WS alert outside trading hours");
            return;
        }

        Long reconnectCount = redis.opsForValue().increment(KEY_WS_RECONNECT_COUNT);
        if (reconnectCount != null && reconnectCount == 1) {
            redis.expire(KEY_WS_RECONNECT_COUNT, Duration.ofHours(24));
        }

        long nowMs = System.currentTimeMillis();
        if (nowMs - lastWsAlertMs.get() < WS_ALERT_COOLDOWN_MS) {
            log.debug("[DataQuality] WS alert suppressed by cooldown");
            return;
        }
        lastWsAlertMs.set(nowMs);

        String reason = heartbeatStale
                ? (heartbeatMissing ? "heartbeat missing" : String.format("heartbeat stale %ds", heartbeatAgeSec))
                : "unknown";
        alerts.add(String.format("WebSocket 이상 (%s) – Python websocket-listener 확인 필요", reason));
    }

    private List<String> resolveMonitoredCodes() {
        Set<String> subscribed = redis.opsForSet().members("ws:subscribed:0B");
        if (subscribed != null && !subscribed.isEmpty()) {
            return new ArrayList<>(subscribed);
        }
        return List.of();
    }

    private long heartbeatAgeSeconds(Map<Object, Object> heartbeat) {
        Object raw = heartbeat.get("updated_at");
        if (raw == null) {
            return Long.MAX_VALUE;
        }
        try {
            double ts = Double.parseDouble(raw.toString());
            long ageSec = (long) (System.currentTimeMillis() / 1000.0 - ts);
            return Math.max(0L, ageSec);
        } catch (NumberFormatException e) {
            return Long.MAX_VALUE;
        }
    }

    private void publishSystemAlert(List<String> alertMessages) {
        try {
            String joined = String.join("\n", alertMessages);
            String msg = objectMapper.writeValueAsString(Map.of(
                    "type", "SYSTEM_ALERT",
                    "alerts", alertMessages,
                    "message", "🚨 <b>[시스템 경고]</b>\n" + joined
            ));
            redisService.pushScoredQueue(msg);
            log.info("[DataQuality] SYSTEM_ALERT published {}", alertMessages.size());
        } catch (Exception e) {
            log.warn("[DataQuality] SYSTEM_ALERT publish failed: {}", e.getMessage());
        }
    }
}
