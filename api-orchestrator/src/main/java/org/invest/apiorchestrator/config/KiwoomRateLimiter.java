package org.invest.apiorchestrator.config;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/**
 * 키움 API 전역 Rate Limiter.
 * 키움 제한: 초당 5회 → 여유 마진 두어 초당 4회(250ms당 1회)로 제한.
 *
 * 사용법: 모든 키움 API 호출 전 rateLimiter.acquire() 호출
 */
@Slf4j
@Component
public class KiwoomRateLimiter {

    private static final int MAX_REQUESTS_PER_SECOND = 4;

    /** 토큰 버킷 세마포어 – 초기 4 토큰 */
    private final Semaphore semaphore = new Semaphore(MAX_REQUESTS_PER_SECOND, true);

    private final ScheduledExecutorService refillExecutor =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "kiwoom-rate-limiter");
                t.setDaemon(true);
                return t;
            });

    @PostConstruct
    public void startRefiller() {
        // 250ms마다 토큰 1개 보충 (= 초당 최대 4회)
        refillExecutor.scheduleAtFixedRate(this::refillOne, 250, 250, TimeUnit.MILLISECONDS);
        log.info("[RateLimiter] 키움 API Rate Limiter 시작 – 최대 {}req/s", MAX_REQUESTS_PER_SECOND);
    }

    /**
     * API 호출 전 토큰 획득. 토큰 소진 시 최대 5초 대기.
     * 5초 초과 대기 시 경고 로그 후 강제 진행 (무한 블로킹 방지).
     */
    public void acquire() {
        try {
            boolean acquired = semaphore.tryAcquire(5, TimeUnit.SECONDS);
            if (!acquired) {
                log.warn("[RateLimiter] 토큰 대기 5초 초과 – 강제 진행 (Rate Limit 위험)");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("[RateLimiter] acquire 인터럽트: {}", e.getMessage());
        }
    }

    private void refillOne() {
        if (semaphore.availablePermits() < MAX_REQUESTS_PER_SECOND) {
            semaphore.release(1);
        }
    }
}
