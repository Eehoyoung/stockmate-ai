package org.invest.apiorchestrator.service;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class OperationsHealthServiceMarketDataTests {

    @Test
    void summarizesFreshnessFallbackCacheAndBudgetCounters() {
        Map<Object, Object> s1 = new LinkedHashMap<>();
        s1.put("tick.state.fresh", "8");
        s1.put("hoga.state.cancel", "2");
        s1.put("rest.fallback_used.true", "3");
        s1.put("rest.budget.exhausted", "1");
        s1.put("cache.used.true", "7");
        Map<Object, Object> s8 = Map.of(
                "strength.state.missing", "4",
                "rest.fallback_used.true", "2"
        );

        Map<String, Object> snapshot = OperationsHealthService.summarizeMarketDataObservability(
                "2026-07-19", Map.of("S1_GAP_OPEN", s1, "S8_GOLDEN_CROSS", s8));

        assertEquals("OBSERVED", snapshot.get("status"));
        assertEquals("2026-07-19", snapshot.get("business_date"));
        @SuppressWarnings("unchecked")
        Map<String, Object> totals = (Map<String, Object>) snapshot.get("totals");
        assertEquals(5L, totals.get("rest_fallback_used"));
        assertEquals(1L, totals.get("rest_budget_exhausted"));
        assertEquals(7L, totals.get("cache_used"));
        assertEquals(6L, totals.get("stale_or_missing"));
    }

    @Test
    void reportsNoDataWithoutCounters() {
        Map<String, Object> snapshot = OperationsHealthService.summarizeMarketDataObservability(
                "2026-07-19", Map.of());

        assertEquals("NO_DATA", snapshot.get("status"));
    }
}
