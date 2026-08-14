package org.invest.apiorchestrator.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.invest.apiorchestrator.service.OperationsHealthService;
import org.invest.apiorchestrator.service.SystemHealthSnapshotService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AdminControllerTests {

    @Mock OperationsHealthService operationsHealthService;
    @Mock SystemHealthSnapshotService systemHealthSnapshotService;
    @Mock StringRedisTemplate redis;
    @Mock JdbcTemplate jdbcTemplate;

    final ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks AdminController controller;

    @Test
    void overviewMergesOwnHealthSnapshotWithCrossServiceCheck() {
        when(operationsHealthService.buildHealthSnapshot())
                .thenReturn(Map.of("status", "UP", "service", "api-orchestrator"));
        when(systemHealthSnapshotService.buildSnapshot())
                .thenReturn(Map.of("overall", "OK"));

        var response = controller.overview();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("UP", response.getBody().get("status"));
        assertEquals("api-orchestrator", response.getBody().get("service"));
        @SuppressWarnings("unchecked")
        Map<String, Object> crossService = (Map<String, Object>) response.getBody().get("cross_service");
        assertEquals("OK", crossService.get("overall"));
    }

    @Test
    void ownHealthKeysAreNotOverwrittenByCrossServiceCheck() {
        when(operationsHealthService.buildHealthSnapshot())
                .thenReturn(Map.of("status", "DEGRADED"));
        when(systemHealthSnapshotService.buildSnapshot())
                .thenReturn(Map.of("overall", "CRITICAL"));

        var response = controller.overview();

        assertEquals("DEGRADED", response.getBody().get("status"));
    }

    @Test
    void claudeUsageComputesPercentageAgainstConfiguredBudget() {
        ReflectionTestUtils.setField(controller, "objectMapper", objectMapper);
        ReflectionTestUtils.setField(controller, "maxClaudeCallsPerDay", 100);
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(org.mockito.ArgumentMatchers.contains("claude:daily_calls:"))).thenReturn("42");
        when(values.get(org.mockito.ArgumentMatchers.contains("claude:daily_tokens:"))).thenReturn("123456");

        var response = controller.claudeUsage();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(42L, response.getBody().get("calls_today"));
        assertEquals(123456L, response.getBody().get("tokens_today"));
        assertEquals(100, response.getBody().get("max_calls_per_day"));
        assertEquals(42.0, response.getBody().get("usage_pct"));
    }

    @Test
    void claudeUsageDefaultsToZeroWhenCounterMissing() {
        ReflectionTestUtils.setField(controller, "objectMapper", objectMapper);
        ReflectionTestUtils.setField(controller, "maxClaudeCallsPerDay", 100);
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(org.mockito.ArgumentMatchers.anyString())).thenReturn(null);

        var response = controller.claudeUsage();

        assertEquals(0L, response.getBody().get("calls_today"));
        assertEquals(0L, response.getBody().get("tokens_today"));
    }

    @Test
    void holdWatchParsesValidItemsAndSkipsMalformedOnes() {
        ReflectionTestUtils.setField(controller, "objectMapper", objectMapper);
        @SuppressWarnings("unchecked")
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redis.opsForHash()).thenReturn(hashOps);
        when(hashOps.entries("hold_monitor:items")).thenReturn(Map.of(
                "S8_GOLDEN_CROSS:005930", "{\"stk_cd\":\"005930\",\"strategy\":\"S8_GOLDEN_CROSS\","
                        + "\"hold_reason\":\"rr below threshold\",\"ai_score\":78,"
                        + "\"hold_monitor_attempts\":3,\"hold_monitor_enqueued_at\":"
                        + (System.currentTimeMillis() / 1000 - 120) + "}",
                "BROKEN:000000", "not-json"
        ));

        var response = controller.holdWatch();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        List<Map<String, Object>> items = response.getBody();
        assertEquals(1, items.size());
        assertEquals("005930", items.get(0).get("stk_cd"));
        assertEquals("S8_GOLDEN_CROSS", items.get(0).get("strategy"));
        assertTrue(((Number) items.get(0).get("age_sec")).longValue() >= 120);
    }

    @Test
    void freshnessReturnsItemsAndSummary() {
        ReflectionTestUtils.setField(controller, "objectMapper", objectMapper);

        Map<String, Object> row = new HashMap<>();
        row.put("id", 1L);
        row.put("signal_id", 2969L);
        row.put("stk_cd", "068270");
        row.put("stk_nm", "셀트리온");
        row.put("strategy", "S15_MOMENTUM_ALIGN");
        row.put("action", "CANCEL");
        row.put("freshness_status", "CAUTION");
        row.put("rest_fallback_used", true);
        row.put("rest_fallback_fields", "[\"tick\",\"hoga\"]");
        row.put("rest_failure_classes", "[]");
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(row));

        Map<String, Object> agg = new HashMap<>();
        agg.put("total", 10L);
        agg.put("rest_fallback_count", 4L);
        agg.put("fresh_count", 3L);
        agg.put("caution_count", 4L);
        agg.put("stale_count", 1L);
        agg.put("unknown_count", 2L);
        when(jdbcTemplate.queryForMap(anyString())).thenReturn(agg);

        var response = controller.freshness(200);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) response.getBody().get("items");
        assertEquals(1, items.size());
        assertEquals("068270", items.get(0).get("stk_cd"));
        assertEquals(List.of("tick", "hoga"), items.get(0).get("rest_fallback_fields"));

        @SuppressWarnings("unchecked")
        Map<String, Object> summary = (Map<String, Object>) response.getBody().get("summary");
        assertEquals(40.0, summary.get("rest_fallback_pct"));
    }

    @Test
    void freshnessFallsBackToEmptyOnQueryFailure() {
        ReflectionTestUtils.setField(controller, "objectMapper", objectMapper);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class)))
                .thenThrow(new RuntimeException("relation does not exist"));

        var response = controller.freshness(200);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(List.of(), response.getBody().get("items"));
    }

    @Test
    void positionsComputesLivePnlFromRedisTick() {
        Map<String, Object> row = new HashMap<>();
        row.put("stk_cd", "005930");
        row.put("stk_nm", "삼성전자");
        row.put("strategy", "S8_GOLDEN_CROSS");
        row.put("status", "ACTIVE");
        row.put("entry_price", 70000);
        row.put("entry_qty", 10);
        row.put("remaining_qty", 10);
        when(jdbcTemplate.queryForList(anyString())).thenReturn(List.of(row));

        @SuppressWarnings("unchecked")
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redis.opsForHash()).thenReturn(hashOps);
        when(hashOps.get("ws:tick:005930", "cur_prc")).thenReturn("71,400");

        var response = controller.positions();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        Map<String, Object> result = response.getBody().get(0);
        assertEquals(71400.0, result.get("cur_prc"));
        assertEquals(2.0, result.get("pnl_pct"));
        assertEquals(14000L, result.get("pnl_abs"));
    }

    @Test
    void positionsReturnsEmptyOnQueryFailure() {
        when(jdbcTemplate.queryForList(anyString())).thenThrow(new RuntimeException("db down"));

        var response = controller.positions();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(List.of(), response.getBody());
    }

    @Test
    void pnlHistoryReturnsOldestFirst() {
        Map<String, Object> newer = new HashMap<>();
        newer.put("date", "2026-07-30");
        Map<String, Object> older = new HashMap<>();
        older.put("date", "2026-07-29");
        when(jdbcTemplate.queryForList(anyString(), org.mockito.ArgumentMatchers.eq(30)))
                .thenReturn(new java.util.ArrayList<>(List.of(newer, older)));

        var response = controller.pnlHistory(30);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("2026-07-29", response.getBody().get(0).get("date"));
        assertEquals("2026-07-30", response.getBody().get(1).get("date"));
    }

    @Test
    void errorQueueParsesJsonAndFallsBackToRawOnParseFailure() {
        ReflectionTestUtils.setField(controller, "objectMapper", objectMapper);
        @SuppressWarnings("unchecked")
        ListOperations<String, String> listOps = mock(ListOperations.class);
        when(redis.opsForList()).thenReturn(listOps);
        when(listOps.range("error_queue", 0, 49L)).thenReturn(List.of(
                "{\"stk_cd\":\"005930\",\"strategy\":\"S1_GAP_OPEN\",\"error\":\"timeout\"}",
                "not-json"
        ));

        var response = controller.errorQueue(50);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        List<Map<String, Object>> items = response.getBody();
        assertEquals(2, items.size());
        assertEquals("005930", items.get(0).get("stk_cd"));
        assertEquals("not-json", items.get(1).get("raw"));
    }
}
