package org.invest.apiorchestrator.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RedisMarketDataServiceFreshnessTests {

    private static final long NOW_MS = 2_000_000L;
    private static final RedisMarketDataService.FreshnessPolicy POLICY =
            new RedisMarketDataService.FreshnessPolicy(Duration.ofSeconds(3), Duration.ofSeconds(5), true);

    @Mock
    StringRedisTemplate redis;

    @Mock
    HashOperations<String, Object, Object> hashOps;

    @Mock
    ListOperations<String, String> listOps;

    RedisMarketDataService service;

    @BeforeEach
    void setUp() {
        service = new RedisMarketDataService(redis, () -> NOW_MS);
    }

    @Test
    void tickClassifiesExactAndOverBoundaries() {
        when(redis.opsForHash()).thenReturn(hashOps);
        when(hashOps.entries("ws:tick:FRESH")).thenReturn(Map.of("updated_at_ms", String.valueOf(NOW_MS - 3_000)));
        when(hashOps.entries("ws:tick:CAUTION")).thenReturn(Map.of("updated_at_ms", String.valueOf(NOW_MS - 3_001)));
        when(hashOps.entries("ws:tick:REJECT_EDGE")).thenReturn(Map.of("updated_at_ms", String.valueOf(NOW_MS - 5_000)));
        when(hashOps.entries("ws:tick:STALE")).thenReturn(Map.of("updated_at_ms", String.valueOf(NOW_MS - 5_001)));

        assertEquals(RedisMarketDataService.FreshnessState.FRESH, service.getFreshTick("FRESH", POLICY).state());
        assertEquals(RedisMarketDataService.FreshnessState.CAUTION, service.getFreshTick("CAUTION", POLICY).state());
        assertEquals(RedisMarketDataService.FreshnessState.CAUTION, service.getFreshTick("REJECT_EDGE", POLICY).state());
        var stale = service.getFreshTick("STALE", POLICY);
        assertEquals(RedisMarketDataService.FreshnessState.STALE, stale.state());
        assertFalse(stale.usable());
        assertEquals(Duration.ofMillis(5_001), stale.age());
    }

    @Test
    void timestampMetadataIsExposedAndFutureClockSkewIsClamped() {
        when(redis.opsForHash()).thenReturn(hashOps);
        when(hashOps.entries("ws:hoga:005930")).thenReturn(Map.of("updated_at_ms", String.valueOf(NOW_MS + 250)));

        var result = service.getFreshHoga("005930", POLICY);

        assertEquals(RedisMarketDataService.FreshnessState.FRESH, result.state());
        assertEquals(Duration.ZERO, result.age());
        assertEquals(Instant.ofEpochMilli(NOW_MS + 250), result.updatedAt());
    }

    @Test
    void missingOrMalformedRequiredTimestampIsMissing() {
        when(redis.opsForHash()).thenReturn(hashOps);
        when(hashOps.entries("ws:expected:MISSING")).thenReturn(Map.of("exp_cntr_pric", "70000"));
        when(hashOps.entries("ws:expected:MALFORMED")).thenReturn(Map.of("updated_at_ms", "not-a-number"));
        when(hashOps.entries("ws:expected:NON_FINITE")).thenReturn(Map.of("updated_at_ms", "NaN"));
        when(hashOps.entries("ws:expected:EMPTY")).thenReturn(Map.of());

        for (String code : List.of("MISSING", "MALFORMED", "NON_FINITE", "EMPTY")) {
            var result = service.getFreshExpected(code, POLICY);
            assertEquals(RedisMarketDataService.FreshnessState.MISSING, result.state());
            assertFalse(result.usable());
            assertNull(result.age());
        }
    }

    @Test
    void optionalTimestampIsCautionInsteadOfSilentlyFresh() {
        when(redis.opsForHash()).thenReturn(hashOps);
        when(hashOps.entries("ws:tick:LEGACY")).thenReturn(Map.of("cur_prc", "70000"));
        var optional = new RedisMarketDataService.FreshnessPolicy(
                Duration.ofSeconds(3), Duration.ofSeconds(5), false);

        var result = service.getFreshTick("LEGACY", optional);

        assertEquals(RedisMarketDataService.FreshnessState.CAUTION, result.state());
        assertTrue(result.usable());
        assertNull(result.updatedAt());
    }

    @Test
    void strengthRequiresBothSamplesAndFreshMetadata() {
        when(redis.opsForList()).thenReturn(listOps);
        when(redis.opsForHash()).thenReturn(hashOps);
        when(listOps.range("ws:strength:005930", 0, 4)).thenReturn(List.of("110", "120", "bad", "+130"));
        when(hashOps.entries("ws:strength_meta:005930"))
                .thenReturn(Map.of("updated_at_ms", String.valueOf(NOW_MS - 10_001)));

        var result = service.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY);

        assertEquals(120.0, result.value());
        assertEquals(RedisMarketDataService.FreshnessState.STALE, result.state());
        assertFalse(result.usable());
    }

    @Test
    void strengthWithFreshMetaButNoSamplesIsMissing() {
        when(redis.opsForList()).thenReturn(listOps);
        when(listOps.range("ws:strength:005930", 0, 4)).thenReturn(List.of());

        var result = service.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY);

        assertEquals(RedisMarketDataService.FreshnessState.MISSING, result.state());
        assertNull(result.value());
    }

    @Test
    void legacyRawGetterStillReturnsTimestampAgnosticData() {
        when(redis.opsForHash()).thenReturn(hashOps);
        Map<Object, Object> staleRaw = Map.of(
                "cur_prc", "70000",
                "updated_at_ms", String.valueOf(NOW_MS - 60_000));
        when(hashOps.entries("ws:tick:005930")).thenReturn(staleRaw);

        Optional<Map<Object, Object>> result = service.getTickData("005930");

        assertTrue(result.isPresent());
        assertEquals(staleRaw, result.orElseThrow());
    }

    @Test
    void policyRejectsInvalidDurations() {
        assertThrows(IllegalArgumentException.class, () -> new RedisMarketDataService.FreshnessPolicy(
                Duration.ofSeconds(5), Duration.ofSeconds(3), true));
        assertThrows(IllegalArgumentException.class, () -> new RedisMarketDataService.FreshnessPolicy(
                Duration.ofSeconds(-1), Duration.ZERO, true));
    }
}
