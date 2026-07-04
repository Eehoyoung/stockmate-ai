package org.invest.apiorchestrator.config;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/**
 * Kiwoom REST API rate limiter.
 *
 * <p>Kiwoom's documented baseline is 5 requests per second. This service uses
 * a conservative 3 requests per second local limiter, plus a Redis-backed global
 * limiter to coordinate multiple processes.
 *
 * <p>Call {@code rateLimiter.acquire()} immediately before every Kiwoom REST call.
 * When Redis coordination is unavailable or too slow, this class now falls back
 * to a stricter local throttle instead of fail-open bursting requests.
 */
@Slf4j
@Component
public class KiwoomRateLimiter {

    private static final int MAX_REQUESTS_PER_SECOND = 3;
    private static final long REFILL_INTERVAL_MS = 1000L / MAX_REQUESTS_PER_SECOND; // 333ms

    private final Semaphore semaphore = new Semaphore(MAX_REQUESTS_PER_SECOND, true);
    private final StringRedisTemplate redisTemplate;
    private final boolean globalEnabled;
    private final long globalIntervalMs;
    private final long globalWaitMs;
    private final long fallbackIntervalMs;
    private final long unavailableBackoffMs;
    private final String globalKey;
    private volatile long globalDisabledUntilMs = 0L;
    private long fallbackLastMs = 0L;

    private final ScheduledExecutorService refillExecutor =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "kiwoom-rate-limiter");
                t.setDaemon(true);
                return t;
            });

    public KiwoomRateLimiter(
            StringRedisTemplate redisTemplate,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_ENABLED:true}") boolean globalEnabled,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_INTERVAL_MS:333}") long globalIntervalMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_WAIT_MS:5000}") long globalWaitMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_FALLBACK_INTERVAL_MS:1000}") long fallbackIntervalMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_UNAVAILABLE_BACKOFF_MS:30000}") long unavailableBackoffMs,
            @Value("${KIWOOM_GLOBAL_RATE_LIMIT_KEY:kiwoom:global_rate_limit:lock}") String globalKey
    ) {
        this.redisTemplate = redisTemplate;
        this.globalEnabled = globalEnabled;
        this.globalIntervalMs = Math.max(globalIntervalMs, 1L);
        this.globalWaitMs = Math.max(globalWaitMs, 0L);
        this.fallbackIntervalMs = Math.max(fallbackIntervalMs, this.globalIntervalMs);
        this.unavailableBackoffMs = Math.max(unavailableBackoffMs, 0L);
        this.globalKey = globalKey;
    }

    @PostConstruct
    public void startRefiller() {
        refillExecutor.scheduleAtFixedRate(
                this::refillOne,
                REFILL_INTERVAL_MS, REFILL_INTERVAL_MS, TimeUnit.MILLISECONDS);
        log.info("[RateLimiter] Kiwoom REST limiter started: local={}req/s interval={}ms global={} globalInterval={}ms fallback={}ms",
                MAX_REQUESTS_PER_SECOND, REFILL_INTERVAL_MS, globalEnabled, globalIntervalMs, fallbackIntervalMs);
    }

    /**
     * Blocks until a local token is available, then applies the global limiter.
     * If the local wait exceeds 5 seconds, continue through the stricter fallback
     * throttle so the caller is delayed instead of released in a burst.
     */
    public void acquire() {
        try {
            boolean acquired = semaphore.tryAcquire(5, TimeUnit.SECONDS);
            if (!acquired) {
                log.warn("[RateLimiter] local token wait exceeded 5000ms - local fallback {}ms", fallbackIntervalMs);
                acquireGlobalFallback("local token wait exceeded");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("[RateLimiter] acquire interrupted: {}", e.getMessage());
        }
        acquireGlobal();
    }

    public int availablePermits() {
        return semaphore.availablePermits();
    }

    private void refillOne() {
        if (semaphore.availablePermits() < MAX_REQUESTS_PER_SECOND) {
            semaphore.release(1);
        }
    }

    private void acquireGlobal() {
        if (!globalEnabled) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now < globalDisabledUntilMs) {
            acquireGlobalFallback("global limiter unavailable");
            return;
        }
        long deadline = now + globalWaitMs;
        while (true) {
            try {
                Boolean ok = redisTemplate.opsForValue().setIfAbsent(
                        globalKey,
                        "java",
                        Duration.ofMillis(globalIntervalMs)
                );
                if (Boolean.TRUE.equals(ok)) {
                    return;
                }
            } catch (Exception e) {
                globalDisabledUntilMs = System.currentTimeMillis() + unavailableBackoffMs;
                acquireGlobalFallback("global limiter unavailable");
                log.warn("[RateLimiter] Redis global limiter unavailable - local fallback {}ms for {}ms: {}",
                        fallbackIntervalMs, unavailableBackoffMs, e.getMessage());
                return;
            }
            if (System.currentTimeMillis() >= deadline) {
                acquireGlobalFallback("global limiter wait exceeded");
                log.warn("[RateLimiter] Redis global limiter wait exceeded {}ms - local fallback {}ms",
                        globalWaitMs, fallbackIntervalMs);
                return;
            }
            try {
                Thread.sleep(25L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                log.warn("[RateLimiter] Redis global limiter wait interrupted: {}", e.getMessage());
                return;
            }
        }
    }

    private synchronized void acquireGlobalFallback(String reason) {
        long now = System.currentTimeMillis();
        long waitMs = fallbackIntervalMs - (now - fallbackLastMs);
        if (waitMs > 0L) {
            try {
                Thread.sleep(waitMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                log.warn("[RateLimiter] local fallback interrupted reason={}: {}", reason, e.getMessage());
                return;
            }
        }
        fallbackLastMs = System.currentTimeMillis();
    }
}
