package org.invest.apiorchestrator.config;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 키움 공지(2026-06-12): REST는 TR(api-id)당 초당 5건이며 TR끼리는 서로 경합하지 않는다.
 * 하나의 TR 예산이 소진되어도 다른 TR 호출은 영향을 받지 않아야 한다.
 *
 * 2026-08-05 재설계: 로컬 페이싱이 permits=1(버스트 없는 FIFO 간격)로 바뀌고
 * heavy(차트/대량조회/페이지네이션)·light(일반) TR 티어가 도입되었다. heavy TR은
 * light TR보다 더 긴 간격을 사용해야 한다.
 */
class KiwoomRateLimiterTests {

    private static KiwoomRateLimiter newLimiter(double lightRatePerSec, double heavyRatePerSec) {
        // globalEnabled=false 이므로 Redis 코디네이션 없이 로컬 per-TR 페이싱만 검증한다.
        KiwoomRateLimiter limiter = new KiwoomRateLimiter(
                null, false, 250L, 300L, 5000L, 1000L, 30000L,
                "kiwoom:global_rate_limit:lock:test", lightRatePerSec, heavyRatePerSec, ""
        );
        limiter.startRefiller();
        return limiter;
    }

    @Test
    void differentTrsDoNotBlockEachOther() {
        KiwoomRateLimiter limiter = newLimiter(5.0, 2.0);

        // ka10029(light TR)의 로컬 예산(permits=1)을 소진시킨다.
        limiter.acquire("ka10029");
        assertTrue(limiter.availablePermits("ka10029") == 0);

        long started = System.currentTimeMillis();
        limiter.acquire("ka10063"); // 무관한 TR -> ka10029 소진과 상관없이 즉시 통과해야 함
        long otherTrWaitMs = System.currentTimeMillis() - started;

        assertTrue(otherTrWaitMs < 150,
                "different TR should not wait for an unrelated TR's exhausted budget, waited " + otherTrWaitMs + "ms");
    }

    @Test
    void heavyTrUsesLongerLocalIntervalThanLightTr() {
        // light=5req/s(200ms), heavy=2req/s(500ms) 로 티어 간격 차이를 명확히 한다.
        KiwoomRateLimiter limiter = newLimiter(5.0, 2.0);

        limiter.acquire("ka10029"); // light TR (기본 목록에 없음)
        long lightStart = System.currentTimeMillis();
        limiter.acquire("ka10029");
        long lightWaitMs = System.currentTimeMillis() - lightStart;

        limiter.acquire("ka10055"); // heavy TR (기본 heavy 목록에 포함)
        long heavyStart = System.currentTimeMillis();
        limiter.acquire("ka10055");
        long heavyWaitMs = System.currentTimeMillis() - heavyStart;

        assertTrue(heavyWaitMs > lightWaitMs,
                "heavy TR should wait longer than light TR: light=" + lightWaitMs + "ms heavy=" + heavyWaitMs + "ms");
    }
}
