package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class OperationsHealthService {

    private final StringRedisTemplate redis;
    private final JdbcTemplate jdbcTemplate;
    private final TradingSignalRepository tradingSignalRepository;
    private final NewsControlService newsControlService;

    public Map<String, Object> buildHealthSnapshot() {
        OffsetDateTime checkedAt = KstClock.nowOffset();
        boolean redisUp = isRedisUp();
        boolean postgresUp = isPostgresUp();

        long telegramQueue = getListSize("telegram_queue");
        long aiScoredQueue = getListSize("ai_scored_queue");
        long errorQueue = getListSize("error_queue");
        long viWatchQueue = getListSize("vi_watch_queue");
        long activePositions = getActivePositionCount();

        Map<Object, Object> heartbeat = getHashEntries("ws:py_heartbeat");
        Double heartbeatEpoch = toDouble(heartbeat.get("updated_at"));
        OffsetDateTime heartbeatAt = heartbeatEpoch != null
                ? Instant.ofEpochMilli((long) (heartbeatEpoch * 1000)).atZone(KstClock.ZONE_ID).toOffsetDateTime()
                : null;
        Long heartbeatAgeSec = heartbeatEpoch != null
                ? Math.max(0L, Instant.now().getEpochSecond() - (long) heartbeatEpoch.doubleValue())
                : null;
        boolean wsUp = heartbeatAt != null && heartbeatAgeSec != null && heartbeatAgeSec <= 90;

        String wsEventMode = getString("ws:db_writer:event_mode", "unknown");
        String tradingControl = newsControlService.getTradingControl().name();
        boolean calendarPreEvent = "true".equalsIgnoreCase(getString("calendar:pre_event", "false"));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("status", redisUp && postgresUp ? "UP" : "DEGRADED");
        response.put("service", "api-orchestrator");
        response.put("timezone", KstClock.ZONE_ID.getId());
        response.put("checked_at", checkedAt.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        response.put("business_date", KstClock.today().toString());
        response.put("redis", linkedMap(
                "status", redisUp ? "UP" : "DOWN",
                "telegram_queue", telegramQueue,
                "ai_scored_queue", aiScoredQueue,
                "error_queue", errorQueue,
                "vi_watch_queue", viWatchQueue
        ));
        response.put("postgres", linkedMap(
                "status", postgresUp ? "UP" : "DOWN"
        ));
        response.put("ws", linkedMap(
                "status", wsUp ? "UP" : "DOWN",
                "last_heartbeat_at", heartbeatAt != null ? heartbeatAt.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME) : null,
                "heartbeat_age_sec", heartbeatAgeSec,
                "event_mode", wsEventMode
        ));
        response.put("positions", linkedMap(
                "active_count", activePositions
        ));
        response.put("flags", linkedMap(
                "trading_control", tradingControl,
                "calendar_pre_event", calendarPreEvent,
                "ws_db_writer_event_mode", wsEventMode,
                "bypass_market_hours", envFlag("BYPASS_MARKET_HOURS", false),
                "strategy_session_filter", envFlag("ENABLE_STRATEGY_SESSION_FILTER", false),
                "strategy_session_dry_run", envFlag("STRATEGY_SESSION_DRY_RUN", false),
                "strategy_session_fail_open", envFlag("STRATEGY_SESSION_FAIL_OPEN", true),
                "session_enter_guard", envFlag("SESSION_ENTER_GUARD_ENABLED", false)
        ));
        response.put("queues", linkedMap(
                "telegram_queue", telegramQueue,
                "ai_scored_queue", aiScoredQueue,
                "error_queue", errorQueue,
                "vi_watch_queue", viWatchQueue
        ));
        response.put("schedulers", buildSchedulerSnapshot());
        return response;
    }

    private Map<String, Object> buildSchedulerSnapshot() {
        Map<String, Object> schedulers = new LinkedHashMap<>();
        schedulers.put("news_scheduler", linkedMap(
                "last_success_at", getString("ops:scheduler:news_scheduler:last_success_at", null),
                "last_slot", getString("ops:scheduler:news_scheduler:last_slot", null),
                "last_status", getString("ops:scheduler:news_scheduler:last_status", "UNKNOWN")
        ));
        schedulers.put("status_report", linkedMap(
                "last_success_at", getString("ops:scheduler:status_report:last_success_at", null),
                "last_status", getString("ops:scheduler:status_report:last_status", "UNKNOWN")
        ));
        schedulers.put("daily_summary", linkedMap(
                "last_success_at", getString("ops:scheduler:daily_summary:last_success_at", null),
                "last_status", getString("ops:scheduler:daily_summary:last_status", "UNKNOWN")
        ));
        return schedulers;
    }

    private Map<String, Object> linkedMap(Object... values) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < values.length; i += 2) {
            result.put(String.valueOf(values[i]), values[i + 1]);
        }
        return result;
    }

    static boolean envFlag(String key, boolean defaultValue) {
        String value = System.getProperty(key);
        if (value == null || value.isBlank()) {
            value = System.getenv(key);
        }
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        return "true".equalsIgnoreCase(value) || "1".equals(value) || "yes".equalsIgnoreCase(value);
    }

    private boolean isRedisUp() {
        try {
            String pong = redis.execute((RedisCallback<String>) connection -> connection.ping());
            return "PONG".equalsIgnoreCase(pong);
        } catch (Exception e) {
            return false;
        }
    }

    private boolean isPostgresUp() {
        try {
            Integer one = jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            return one != null && one == 1;
        } catch (Exception e) {
            return false;
        }
    }

    private long getListSize(String key) {
        try {
            Long size = redis.opsForList().size(key);
            return size != null ? size : 0L;
        } catch (Exception e) {
            return 0L;
        }
    }

    private long getActivePositionCount() {
        try {
            return tradingSignalRepository.countActivePositions();
        } catch (Exception e) {
            return 0L;
        }
    }

    private Map<Object, Object> getHashEntries(String key) {
        try {
            return redis.opsForHash().entries(key);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private String getString(String key, String fallback) {
        try {
            String value = redis.opsForValue().get(key);
            return value != null ? value : fallback;
        } catch (Exception e) {
            return fallback;
        }
    }

    private Double toDouble(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception e) {
            return null;
        }
    }
}
