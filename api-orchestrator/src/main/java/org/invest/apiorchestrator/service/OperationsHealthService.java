package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import org.invest.apiorchestrator.domain.TradingSignal;
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
    private final StrategyExecutionOwnership strategyExecutionOwnership;

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
                "bypass_market_hours", runtimeFlag("bypass_market_hours", "BYPASS_MARKET_HOURS", false),
                "strategy_session_filter", runtimeFlag("strategy_session_filter", "ENABLE_STRATEGY_SESSION_FILTER", false),
                "strategy_session_dry_run", runtimeFlag("strategy_session_dry_run", "STRATEGY_SESSION_DRY_RUN", false),
                "strategy_session_fail_open", runtimeFlag("strategy_session_fail_open", "STRATEGY_SESSION_FAIL_OPEN", false),
                "session_enter_guard", runtimeFlag("session_enter_guard", "SESSION_ENTER_GUARD_ENABLED", false)
        ));
        response.put("queues", linkedMap(
                "telegram_queue", telegramQueue,
                "ai_scored_queue", aiScoredQueue,
                "error_queue", errorQueue,
                "vi_watch_queue", viWatchQueue
        ));
        response.put("schedulers", buildSchedulerSnapshot());
        response.put("market_data_observability", buildMarketDataObservabilitySnapshot());
        response.put("strategy_execution", strategyExecutionOwnership.snapshot());
        return response;
    }

    private Map<String, Object> buildMarketDataObservabilitySnapshot() {
        String businessDate = KstClock.today().toString();
        Map<String, Map<Object, Object>> metrics = new LinkedHashMap<>();
        for (TradingSignal.StrategyType strategy : TradingSignal.StrategyType.values()) {
            Map<Object, Object> entries = getHashEntries(
                    "status:market_data_observability:" + businessDate + ":" + strategy.name());
            if (!entries.isEmpty()) {
                metrics.put(strategy.name(), entries);
            }
        }
        return summarizeMarketDataObservability(businessDate, metrics);
    }

    static Map<String, Object> summarizeMarketDataObservability(
            String businessDate, Map<String, Map<Object, Object>> metrics) {
        Map<String, Object> strategies = new LinkedHashMap<>();
        long restFallbackUsed = 0L;
        long budgetExhausted = 0L;
        long cacheUsed = 0L;
        long staleOrMissing = 0L;

        for (var strategyEntry : metrics.entrySet()) {
            Map<String, Long> counters = new LinkedHashMap<>();
            for (var counter : strategyEntry.getValue().entrySet()) {
                String name = String.valueOf(counter.getKey());
                long value = toLong(counter.getValue());
                counters.put(name, value);
                if ("rest.fallback_used.true".equals(name)) restFallbackUsed += value;
                if ("rest.budget.exhausted".equals(name)) budgetExhausted += value;
                if ("cache.used.true".equals(name)) cacheUsed += value;
                if (name.endsWith(".state.cancel") || name.endsWith(".state.missing")) {
                    staleOrMissing += value;
                }
            }
            strategies.put(strategyEntry.getKey(), counters);
        }

        Map<String, Object> totals = new LinkedHashMap<>();
        totals.put("rest_fallback_used", restFallbackUsed);
        totals.put("rest_budget_exhausted", budgetExhausted);
        totals.put("cache_used", cacheUsed);
        totals.put("stale_or_missing", staleOrMissing);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", strategies.isEmpty() ? "NO_DATA" : "OBSERVED");
        result.put("business_date", businessDate);
        result.put("totals", totals);
        result.put("strategies", strategies);
        return result;
    }

    private static long toLong(Object value) {
        try {
            return value == null ? 0L : Long.parseLong(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return 0L;
        }
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

    /**
     * flags:{redisKey} 에 대시보드에서 저장한 런타임 오버라이드가 있으면 그 값을,
     * 없으면 기존 env/System property 기반 envFlag() 값을 사용한다.
     */
    private boolean runtimeFlag(String redisKey, String envKey, boolean defaultValue) {
        try {
            String override = redis.opsForValue().get("flags:" + redisKey);
            if (override != null && !override.isBlank()) {
                return "true".equalsIgnoreCase(override.trim());
            }
        } catch (Exception e) {
            // Redis 조회 실패 시 env 기본값으로 폴백
        }
        return envFlag(envKey, defaultValue);
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
