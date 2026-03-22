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
 *
 * <p>키움 제한: 초당 5회<br>
 * 설정값: 초당 최대 3회 (333ms 간격) – 여유 마진 확보 및 재시도 burst 방지.
 *
 * <p><b>Mono.defer 연동</b>: KiwoomApiService 에서 Mono.defer() 로 감쌌으므로
 * retryWhen 재시도 시에도 acquire() 가 반드시 재호출됩니다.
 *
 * <p>사용법: 모든 키움 API 호출 전 {@code rateLimiter.acquire()} 호출
 */
@Slf4j
@Component
public class KiwoomRateLimiter {

    /** 초당 최대 요청 수 (키움 제한 5/s 에서 여유 마진 적용) */
    private static final int MAX_REQUESTS_PER_SECOND = 3;

    /** 토큰 보충 간격 ms = 1000 / MAX_REQUESTS_PER_SECOND */
    private static final long REFILL_INTERVAL_MS = 1000L / MAX_REQUESTS_PER_SECOND; // 333ms

    /** 토큰 버킷 세마포어 – 초기 MAX 토큰 */
    private final Semaphore semaphore = new Semaphore(MAX_REQUESTS_PER_SECOND, true);

    private final ScheduledExecutorService refillExecutor =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "kiwoom-rate-limiter");
                t.setDaemon(true);
                return t;
            });

    @PostConstruct
    public void startRefiller() {
        refillExecutor.scheduleAtFixedRate(
                this::refillOne,
                REFILL_INTERVAL_MS, REFILL_INTERVAL_MS, TimeUnit.MILLISECONDS);
        log.info("[RateLimiter] 키움 API Rate Limiter 시작 – 최대 {}req/s ({}ms 간격)",
                MAX_REQUESTS_PER_SECOND, REFILL_INTERVAL_MS);
    }

    /**
     * API 호출 전 토큰 획득. 토큰 소진 시 최대 5초 대기.
     * 5초 초과 시 경고 로그 후 강제 진행 (무한 블로킹 방지).
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

    /** 현재 사용 가능한 토큰 수 (모니터링용) */
    public int availablePermits() {
        return semaphore.availablePermits();
    }

    private void refillOne() {
        if (semaphore.availablePermits() < MAX_REQUESTS_PER_SECOND) {
            semaphore.release(1);
        }
    }
}
