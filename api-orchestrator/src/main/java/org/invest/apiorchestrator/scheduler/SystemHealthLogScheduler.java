package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.channel.ChannelOption;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;

import java.time.Duration;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

@Slf4j
@Component
@RequiredArgsConstructor
public class SystemHealthLogScheduler {

    private static final LocalTime START_TIME = LocalTime.of(7, 0);
    private static final LocalTime END_TIME   = LocalTime.of(20, 10);

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

    private final StringRedisTemplate stringRedisTemplate;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    /** 내부 서비스 전용 WebClient — Kiwoom 클라이언트와 별도 생성 */
    private final WebClient internalClient = WebClient.builder()
            .clientConnector(new ReactorClientHttpConnector(
                    HttpClient.create()
                            .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 4_000)
                            .responseTimeout(Duration.ofSeconds(4))
            ))
            .codecs(c -> c.defaultCodecs().maxInMemorySize(512 * 1024))
            .build();

    @Scheduled(cron = "0 */5 7-20 * * MON-FRI", zone = "Asia/Seoul")
    public void collectAndLogSystemHealth() {
        LocalTime now = KstClock.nowTime();
        if (now.isBefore(START_TIME) || now.isAfter(END_TIME)) {
            return;
        }

        try {
            // 1. 서비스 헬스 — 4개 동시 체크
            Map<String, Object> servicesMap = checkServicesParallel();

            // 2. Redis 상태
            Map<String, Object> redisMap = checkRedis();

            // 3. PostgreSQL 상태
            Map<String, Object> pgMap = checkPostgres();

            // 4. overall 판정
            String overall = determineOverall(servicesMap, redisMap, pgMap);

            // 5. JSON 조립 및 로그 출력
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("ts", KstClock.nowOffset().toString());
            payload.put("module", "system_health");
            payload.put("level", "INFO");
            payload.put("services", servicesMap);
            payload.put("redis", redisMap);
            payload.put("postgres", pgMap);
            payload.put("overall", overall);

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

    // -------------------------------------------------------------------------
    // 서비스 헬스 체크
    // -------------------------------------------------------------------------

    private static final String[][] SERVICE_ENDPOINTS = {
            {"api-orchestrator", "http://localhost:8080/actuator/health"},
            {"websocket-listener", "http://websocket-listener:8081/health"},
            {"ai-engine",         "http://ai-engine:8082/health"},
            {"telegram-bot",      "http://telegram-bot:3001/health"},
    };

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
            internalClient.get()
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

        // PING
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

        // 큐 깊이
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

        // candidates spot-check
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

    // -------------------------------------------------------------------------
    // 내부 레코드
    // -------------------------------------------------------------------------

    private record ServiceHealth(String name, String status, long latencyMs, String detail) {}
}
