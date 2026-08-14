package org.invest.apiorchestrator.config;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Arrays;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;
import java.util.stream.Collectors;

/**
 * Kiwoom REST API rate limiter.
 *
 * <p>Kiwoom 공지(2026-06-12): REST는 TR(api-id)당 초당 5건이 허용되며, 여러 TR을
 * 동시에 요청해도 TR별로 각각 초당 5건이다. 과거 구현은 이 예산을 전체 Kiwoom
 * 호출(모든 TR 합산, Python ai-engine과도 공유)에 단일 버킷으로 적용해서 서로
 * 무관한 TR끼리 불필요하게 경합했다(2026-07-26 조사로 확인). 이제 로컬 세마포어와
 * Redis 코디네이션 키 모두 TR(apiId)별로 독립 관리한다.
 *
 * <p>실무 가이드(레포 오너, 2026-08-05 조사): 키움 공식 "초당 5건"은 이론상
 * 상한이며, 서버 응답 지연·자동 속도조절 탓에 실제로는 안정적으로 채우기
 * 어렵다. 차트/대량조회/페이지네이션 TR(heavy)은 최소 1.0초 간격, 그 외 일반
 * TR(light)도 최소 0.8초 간격을 기본값으로 두고, 다수 요청은 TR별 FIFO
 * 잠금(permits=1)으로 직렬화한다. Python http_utils.py::_KiwoomRateLimiter 와
 * 동일한 티어(heavy TR 목록·요율)를 사용해 두 프로세스 간 예산 정합성을
 * 맞춘다.
 *
 * <p>Call {@code rateLimiter.acquire(apiId)} immediately before every Kiwoom REST call.
 * Redis coordination is the dispatch authority. Calls fail closed when the
 * reservation cannot be acquired before the deadline.
 */
@Slf4j
@Component
public class KiwoomRateLimiter {

    // 로컬 페이싱은 TR당 permits=1(버스트 없이 FIFO 간격만 강제)로 두고,
    // light/heavy 티어별 refill 주기로 유효 요율을 결정한다.
    private static final int LOCAL_CAPACITY = 1;

    // Python http_utils.py::_DEFAULT_HEAVY_TR_IDS 와 동일한 목록.
    private static final Set<String> DEFAULT_HEAVY_TR_IDS = Set.of(
            "ka10025", "ka10047", "ka10055", "ka10059", "ka10061", "ka10064",
            "ka10080", "ka10081", "ka90003", "ka90008", "ka90009"
    );

    private final ConcurrentHashMap<String, Semaphore> semaphores = new ConcurrentHashMap<>();
    private final StringRedisTemplate redisTemplate;
    private final boolean globalEnabled;
    private final long globalIntervalMsLight;
    private final long globalIntervalMsHeavy;
    private final long globalWaitMs;
    private final long localWaitMs;
    private final long unavailableBackoffMs;
    private final String globalKey;
    private final Set<String> heavyTrIds;
    private final long lightLocalIntervalMs;
    private final long heavyLocalIntervalMs;
    private static final String METRICS_KEY = "status:kiwoom_rest_reservations";
    private volatile long globalDisabledUntilMs = 0L;

    private final ScheduledExecutorService refillExecutor =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "kiwoom-rate-limiter");
                t.setDaemon(true);
                return t;
            });

    public KiwoomRateLimiter(
            StringRedisTemplate redisTemplate,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_ENABLED:true}") boolean globalEnabled,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_INTERVAL_MS:800}") long globalIntervalMsLight,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_INTERVAL_MS_HEAVY:1000}") long globalIntervalMsHeavy,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_WAIT_MS:8000}") long globalWaitMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_FALLBACK_INTERVAL_MS:1000}") long fallbackIntervalMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_UNAVAILABLE_BACKOFF_MS:30000}") long unavailableBackoffMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_KEY:kiwoom:global_rate_limit:lock}") String globalKey,
            @Value("${KIWOOM_REST_RATE_PER_TR:1.25}") double lightRatePerSec,
            @Value("${KIWOOM_REST_RATE_HEAVY_TR:1.0}") double heavyRatePerSec,
            @Value("${KIWOOM_HEAVY_TR_IDS:}") String heavyTrIdsCsv
    ) {
        this.redisTemplate = redisTemplate;
        this.globalEnabled = globalEnabled;
        this.globalIntervalMsLight = Math.max(globalIntervalMsLight, 1L);
        this.globalIntervalMsHeavy = Math.max(globalIntervalMsHeavy, 1L);
        this.globalWaitMs = Math.max(globalWaitMs, 0L);
        // 로컬 세마포어 대기 한도는 global 대기 한도보다 짧으면 안 되므로 둘 중
        // 큰 값을 사용한다(과거 하드코딩된 5초 유지, 필요 시 globalWaitMs로 확장).
        this.localWaitMs = Math.max(this.globalWaitMs, 5000L);
        this.unavailableBackoffMs = Math.max(unavailableBackoffMs, 0L);
        this.globalKey = globalKey;
        this.heavyTrIds = (heavyTrIdsCsv == null || heavyTrIdsCsv.isBlank())
                ? DEFAULT_HEAVY_TR_IDS
                : Arrays.stream(heavyTrIdsCsv.split(","))
                        .map(String::trim)
                        .filter(s -> !s.isEmpty())
                        .collect(Collectors.toSet());
        this.lightLocalIntervalMs = Math.max(1L, Math.round(1000.0 / Math.max(lightRatePerSec, 0.001)));
        this.heavyLocalIntervalMs = Math.max(1L, Math.round(1000.0 / Math.max(heavyRatePerSec, 0.001)));
    }

    @PostConstruct
    public void startRefiller() {
        refillExecutor.scheduleAtFixedRate(
                () -> refillTier(id -> !isHeavy(id)),
                lightLocalIntervalMs, lightLocalIntervalMs, TimeUnit.MILLISECONDS);
        refillExecutor.scheduleAtFixedRate(
                () -> refillTier(this::isHeavy),
                heavyLocalIntervalMs, heavyLocalIntervalMs, TimeUnit.MILLISECONDS);
        log.info("[RateLimiter] Kiwoom REST limiter started: lightInterval={}ms heavyInterval={}ms "
                        + "global={} globalIntervalLight={}ms globalIntervalHeavy={}ms failClosed=true",
                lightLocalIntervalMs, heavyLocalIntervalMs, globalEnabled, globalIntervalMsLight, globalIntervalMsHeavy);
    }

    /**
     * Blocks until a local per-TR token is available, then applies the global limiter.
     */
    public void acquire() {
        acquire("unknown");
    }

    public void acquire(String apiId) {
        String metricApi = apiId == null || apiId.isBlank() ? "unknown" : apiId;
        metric(metricApi, "requested", 1);
        metric(metricApi, "pending", 1);
        long started = System.currentTimeMillis();
        try {
            boolean acquired = semaphoreFor(metricApi).tryAcquire(localWaitMs, TimeUnit.MILLISECONDS);
            if (!acquired) {
                metric(metricApi, "dropped.local_deadline", 1);
                throw new ReservationUnavailableException("local token deadline exceeded");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            metric(metricApi, "dropped.interrupted", 1);
            throw new ReservationUnavailableException("reservation interrupted", e);
        }
        try {
            acquireGlobal(metricApi);
            metric(metricApi, "granted", 1);
            metric(metricApi, "wait_ms_total", System.currentTimeMillis() - started);
        } finally {
            metric(metricApi, "pending", -1);
        }
    }

    public int availablePermits(String apiId) {
        return semaphoreFor(apiId).availablePermits();
    }

    private boolean isHeavy(String apiId) {
        return heavyTrIds.contains(apiId);
    }

    private Semaphore semaphoreFor(String apiId) {
        return semaphores.computeIfAbsent(apiId, k -> new Semaphore(LOCAL_CAPACITY, true));
    }

    private void refillTier(Predicate<String> tierMatch) {
        for (Map.Entry<String, Semaphore> entry : semaphores.entrySet()) {
            if (!tierMatch.test(entry.getKey())) {
                continue;
            }
            Semaphore semaphore = entry.getValue();
            if (semaphore.availablePermits() < LOCAL_CAPACITY) {
                semaphore.release(1);
            }
        }
    }

    private void acquireGlobal(String apiId) {
        if (!globalEnabled) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now < globalDisabledUntilMs) {
            metric(apiId, "dropped.coordinator_unavailable", 1);
            throw new ReservationUnavailableException("global limiter unavailable");
        }
        long deadline = now + globalWaitMs;
        String key = globalKey + ":" + apiId;
        long intervalMs = isHeavy(apiId) ? globalIntervalMsHeavy : globalIntervalMsLight;
        while (true) {
            try {
                Boolean ok = redisTemplate.opsForValue().setIfAbsent(
                        key,
                        "java",
                        Duration.ofMillis(intervalMs)
                );
                if (Boolean.TRUE.equals(ok)) {
                    return;
                }
            } catch (Exception e) {
                globalDisabledUntilMs = System.currentTimeMillis() + unavailableBackoffMs;
                log.warn("[RateLimiter] Redis global limiter unavailable - calls blocked for {}ms: {}",
                        unavailableBackoffMs, e.getMessage());
                metric(apiId, "dropped.coordinator_unavailable", 1);
                throw new ReservationUnavailableException("global limiter unavailable", e);
            }
            if (System.currentTimeMillis() >= deadline) {
                log.warn("[RateLimiter] Redis global limiter({}) wait exceeded {}ms - call dropped", apiId, globalWaitMs);
                metric(apiId, "dropped.global_deadline", 1);
                throw new ReservationUnavailableException("global limiter deadline exceeded");
            }
            try {
                Thread.sleep(25L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new ReservationUnavailableException("global reservation interrupted", e);
            }
        }
    }

    private void metric(String apiId, String field, long delta) {
        try {
            redisTemplate.opsForHash().increment(METRICS_KEY, "java." + apiId + "." + field, delta);
            redisTemplate.expire(METRICS_KEY, Duration.ofDays(7));
        } catch (Exception ignored) {
            // Reservation behavior must not depend on observability writes.
        }
    }

    public static class ReservationUnavailableException extends RuntimeException {
        public ReservationUnavailableException(String message) {
            super(message);
        }

        public ReservationUnavailableException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
