package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * 4개 서비스(api-orchestrator/websocket-listener/ai-engine/telegram-bot) + Redis + PostgreSQL
 * 헬스 상태를 병렬로 조회한다. {@link org.invest.apiorchestrator.scheduler.SystemHealthLogScheduler}가
 * 5분마다 로그로 남기는 것과 관리자 대시보드({@code /api/admin/overview})가 요청 시점에 즉시 조회하는 것,
 * 두 소비처가 동일한 로직을 공유한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SystemHealthSnapshotService {

    private final StringRedisTemplate stringRedisTemplate;
    private final JdbcTemplate jdbcTemplate;
    private final WebClient internalWebClient;

    private static final String[] QUEUE_KEYS = {
            "telegram_queue", "ai_scored_queue", "vi_watch_queue"
    };

    // spot-check 대상 candidates 키 (운영에서 KEYS * 사용 금지)
    private static final String[] CANDIDATE_SPOT_KEYS = {
            "candidates:s1:001", "candidates:s1:101",
            "candidates:s3:001", "candidates:s3:101",
            "candidates:s8:001", "candidates:s8:101",
            "candidates:s9:001", "candidates:s9:101",
            "candidates:s12:001", "candidates:s12:101"
    };

    private static final String[][] SERVICE_ENDPOINTS = {
            {"api-orchestrator", "http://localhost:5050/actuator/health"},
            {"websocket-listener", "http://websocket-listener:8081/health"},
            {"ai-engine",         "http://ai-engine:8082/health"},
            {"telegram-bot",      "http://telegram-bot:3001/health"},
    };

    public Map<String, Object> buildSnapshot() {
        Map<String, Object> servicesMap = checkServicesParallel();
        Map<String, Object> redisMap = checkRedis();
        Map<String, Object> pgMap = checkPostgres();
        String overall = determineOverall(servicesMap, redisMap, pgMap);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("services", servicesMap);
        result.put("redis", redisMap);
        result.put("postgres", pgMap);
        result.put("overall", overall);
        return result;
    }

    // -------------------------------------------------------------------------
    // 서비스 헬스 체크
    // -------------------------------------------------------------------------

    private Map<String, Object> checkServicesParallel() {
        List<CompletableFuture<ServiceHealth>> futures = new ArrayList<>();

        for (String[] entry : SERVICE_ENDPOINTS) {
            String name = entry[0];
            String url  = entry[1];
            futures.add(CompletableFuture.supplyAsync(() -> checkService(name, url)));
        }

        // 전체 최대 5초 대기
        try {
            CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]))
                    .get(5, TimeUnit.SECONDS);
        } catch (Exception e) {
            log.debug("[SystemHealth] 서비스 병렬 체크 타임아웃 또는 인터럽트: {}", e.getMessage());
        }

        Map<String, Object> result = new LinkedHashMap<>();
        for (CompletableFuture<ServiceHealth> f : futures) {
            ServiceHealth sh;
            try {
                sh = f.isDone() ? f.get() : new ServiceHealth("unknown", "DOWN", 5000, "timeout");
            } catch (Exception e) {
                sh = new ServiceHealth("unknown", "DOWN", 5000, e.getMessage());
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("status", sh.status());
            entry.put("latency_ms", sh.latencyMs());
            if (sh.detail() != null && !sh.detail().isBlank()) {
                entry.put("detail", sh.detail());
            }
            result.put(sh.name(), entry);
        }
        return result;
    }

    private ServiceHealth checkService(String name, String url) {
        long start = System.currentTimeMillis();
        try {
            internalWebClient.get()
                    .uri(url)
                    .retrieve()
                    .bodyToMono(String.class)
                    .timeout(Duration.ofSeconds(4))
                    .block();
            long latency = System.currentTimeMillis() - start;
            return new ServiceHealth(name, "UP", latency, null);
        } catch (Exception e) {
            long latency = System.currentTimeMillis() - start;
            String detail = simplifyError(e);
            log.warn("[SystemHealth] service DOWN name={} latency_ms={} detail={}", name, latency, detail);
            return new ServiceHealth(name, "DOWN", latency, detail);
        }
    }

    private String simplifyError(Throwable e) {
        String msg = e.getMessage();
        if (msg == null) {
            return e.getClass().getSimpleName();
        }
        if (msg.contains("Connection refused")) return "Connection refused";
        if (msg.contains("timeout") || msg.contains("Timeout")) return "Timeout";
        if (msg.contains("Connection reset")) return "Connection reset";
        // 너무 긴 메시지는 잘라냄
        return msg.length() > 120 ? msg.substring(0, 120) : msg;
    }

    // -------------------------------------------------------------------------
    // Redis 헬스 체크
    // -------------------------------------------------------------------------

    @SuppressWarnings("ConstantConditions")
    private Map<String, Object> checkRedis() {
        Map<String, Object> result = new LinkedHashMap<>();

        String redisStatus = "DOWN";
        try {
            String pong = stringRedisTemplate.execute(
                    (org.springframework.data.redis.core.RedisCallback<String>) conn -> conn.ping()
            );
            if ("PONG".equalsIgnoreCase(pong)) {
                redisStatus = "UP";
            }
        } catch (Exception e) {
            log.warn("[SystemHealth] Redis PING 실패: {}", e.getMessage());
        }
        result.put("status", redisStatus);

        Map<String, Object> queues = new LinkedHashMap<>();
        for (String key : QUEUE_KEYS) {
            try {
                Long size = stringRedisTemplate.opsForList().size(key);
                queues.put(key, size != null ? size : 0L);
            } catch (Exception e) {
                queues.put(key, -1L);
                log.debug("[SystemHealth] Redis lLen 실패 key={}: {}", key, e.getMessage());
            }
        }
        result.put("queues", queues);

        int candidateKeyCount = 0;
        for (String key : CANDIDATE_SPOT_KEYS) {
            try {
                Boolean exists = stringRedisTemplate.hasKey(key);
                if (Boolean.TRUE.equals(exists)) {
                    candidateKeyCount++;
                }
            } catch (Exception e) {
                log.debug("[SystemHealth] Redis hasKey 실패 key={}: {}", key, e.getMessage());
            }
        }
        result.put("candidate_keys_present", candidateKeyCount);

        return result;
    }

    // -------------------------------------------------------------------------
    // PostgreSQL 헬스 체크
    // -------------------------------------------------------------------------

    private Map<String, Object> checkPostgres() {
        Map<String, Object> result = new LinkedHashMap<>();
        try {
            Integer activeConn = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'",
                    Integer.class
            );
            Integer signalsLastHour = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM trading_signals WHERE created_at >= NOW() - INTERVAL '1 hour'",
                    Integer.class
            );
            result.put("status", "UP");
            result.put("active_connections", activeConn != null ? activeConn : 0);
            result.put("signals_last_1h", signalsLastHour != null ? signalsLastHour : 0);
        } catch (Exception e) {
            log.warn("[SystemHealth] PostgreSQL 체크 실패: {}", e.getMessage());
            result.put("status", "DOWN");
            result.put("detail", simplifyError(e));
        }
        return result;
    }

    // -------------------------------------------------------------------------
    // overall 판정
    // -------------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private String determineOverall(
            Map<String, Object> servicesMap,
            Map<String, Object> redisMap,
            Map<String, Object> pgMap
    ) {
        boolean redisDown = !"UP".equals(redisMap.get("status"));
        boolean pgDown    = !"UP".equals(pgMap.get("status"));

        if (redisDown || pgDown) {
            return "CRITICAL";
        }

        boolean anyServiceDown = servicesMap.values().stream()
                .filter(v -> v instanceof Map)
                .map(v -> (Map<String, Object>) v)
                .anyMatch(m -> !"UP".equals(m.get("status")));

        return anyServiceDown ? "DEGRADED" : "OK";
    }

    private record ServiceHealth(String name, String status, long latencyMs, String detail) {}
}
