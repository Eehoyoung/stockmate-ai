package org.invest.apiorchestrator.service;

import org.invest.apiorchestrator.dto.res.CandidateSearchResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CandidateSearchServiceTests {

    @Mock
    NamedParameterJdbcTemplate jdbc;

    @Mock
    StringRedisTemplate redis;

    @Mock
    ListOperations<String, String> listOps;

    @Mock
    HashOperations<String, Object, Object> hashOps;

    @Test
    void searchNormalizesMarketStrategiesAndLimitBeforeQuerying() {
        when(redis.opsForList()).thenReturn(listOps);
        when(listOps.range(anyString(), eq(0L), eq(-1L))).thenReturn(List.of());
        when(jdbc.query(anyString(), any(MapSqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        CandidateSearchService service = new CandidateSearchService(jdbc, redis);
        CandidateSearchResponse response = service.search(new CandidateSearchService.SearchRequest(
                LocalDate.of(2026, 5, 3),
                "kosdaq",
                List.of("s8", "S11_FRGN_CONT"),
                " samsung ",
                "semi",
                BigDecimal.valueOf(70),
                2,
                30,
                false,
                true,
                "strategy_count",
                500
        ));

        ArgumentCaptor<MapSqlParameterSource> paramsCaptor = ArgumentCaptor.forClass(MapSqlParameterSource.class);
        verify(jdbc).query(anyString(), paramsCaptor.capture(), any(RowMapper.class));

        MapSqlParameterSource params = paramsCaptor.getValue();
        assertEquals(List.of("101"), params.getValue("markets"));
        assertEquals(List.of("S8_GOLDEN_CROSS", "S11_FRGN_CONT"), params.getValue("strategies"));
        assertEquals("samsung", response.filters().get("query"));
        assertEquals("semi", response.filters().get("sector"));
        assertEquals(30, response.filters().get("seen_within_min"));
        assertEquals(200, response.filters().get("limit"));
        assertEquals("strategy_count", response.filters().get("sort"));
        assertEquals(0, response.count());
    }

    @Test
    void searchDefaultsUnknownInputsToSafeBroadSearch() {
        when(redis.opsForList()).thenReturn(listOps);
        when(listOps.range(anyString(), eq(0L), eq(-1L))).thenReturn(List.of());
        when(jdbc.query(anyString(), any(MapSqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        CandidateSearchService service = new CandidateSearchService(jdbc, redis);
        CandidateSearchResponse response = service.search(new CandidateSearchService.SearchRequest(
                LocalDate.of(2026, 5, 3),
                "nyse",
                List.of("unknown"),
                null,
                null,
                null,
                null,
                null,
                null,
                false,
                "unsupported",
                0
        ));

        ArgumentCaptor<MapSqlParameterSource> paramsCaptor = ArgumentCaptor.forClass(MapSqlParameterSource.class);
        verify(jdbc).query(anyString(), paramsCaptor.capture(), any(RowMapper.class));

        MapSqlParameterSource params = paramsCaptor.getValue();
        assertEquals(List.of("001", "101"), params.getValue("markets"));
        assertTrue(((List<?>) params.getValue("strategies")).contains("S1_GAP_OPEN"));
        assertEquals("score", response.filters().get("sort"));
        assertEquals(50, response.filters().get("limit"));
    }

    @Test
    void searchIncludesLiveRedisCandidatesBeforeHistorySnapshotExists() {
        when(redis.opsForList()).thenReturn(listOps);
        when(listOps.range(anyString(), eq(0L), eq(-1L))).thenAnswer(invocation -> {
            String key = invocation.getArgument(0, String.class);
            return "candidates:s8:001".equals(key) ? List.of("005930") : List.of();
        });
        when(jdbc.query(anyString(), any(MapSqlParameterSource.class), any(RowMapper.class))).thenReturn(List.of());

        CandidateSearchService service = new CandidateSearchService(jdbc, redis);
        CandidateSearchResponse response = service.search(new CandidateSearchService.SearchRequest(
                LocalDate.of(2026, 5, 3),
                "kospi",
                List.of("s8"),
                null,
                null,
                null,
                null,
                null,
                null,
                true,
                "score",
                20
        ));

        assertEquals(1, response.count());
        assertEquals("005930", response.candidates().get(0).stkCd());
        assertEquals(List.of("S8_GOLDEN_CROSS"), response.candidates().get(0).liveStrategies());
        assertEquals("redis_only", response.candidates().get(0).dataQuality().get("source"));
    }

    @Test
    void dataQualityReportCountsMissingAndFreshMarketData() {
        long now = System.currentTimeMillis();
        when(redis.opsForList()).thenReturn(listOps);
        when(redis.opsForHash()).thenReturn(hashOps);
        when(listOps.range(anyString(), eq(0L), eq(-1L))).thenAnswer(invocation -> {
            String key = invocation.getArgument(0, String.class);
            return "candidates:s8:001".equals(key) ? List.of("005930", "000660") : List.of();
        });
        when(hashOps.entries("ws:tick:005930")).thenReturn(Map.of("updated_at_ms", String.valueOf(now)));
        when(hashOps.entries("ws:hoga:005930")).thenReturn(Map.of("updated_at_ms", String.valueOf(now)));
        when(hashOps.entries("ws:tick:000660")).thenReturn(Map.of());
        when(hashOps.entries("ws:hoga:000660")).thenReturn(Map.of());

        CandidateSearchService service = new CandidateSearchService(jdbc, redis);
        Map<String, Object> report = service.buildDataQualityReport("001", List.of("s8"));

        assertEquals(2, report.get("unique_live_candidates"));
        assertEquals(1, report.get("fresh_count"));
        assertEquals(1, report.get("tick_missing_count"));
        assertEquals(1, report.get("hoga_missing_count"));
        assertEquals("DEGRADED", report.get("status"));
    }
}
