package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.KiwoomRestFallbackService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S11FrgnContScannerTests {

    @Mock KiwoomApiService apiService;
    @Mock RedisMarketDataService redisService;
    @Mock KiwoomRestFallbackService restFallbackService;

    @Test
    void enrichesFinalCandidateWithKa10064ShadowFields() {
        when(apiService.fetchKa10035(any())).thenReturn(contResponse(List.of(item("005930", 60_000))));
        stubMarketData();
        var flow = new KiwoomRestFallbackService.InvestorFlowSnapshot(
                "101500", 50_000, 30_000, 80_000, 70_000, 3, false,
                20_000, 12_000, 8_000, 5_000, false, "NONE");
        when(restFallbackService.fetchInvestorFlowDetailed("101", "005930"))
                .thenReturn(result(flow, KiwoomRestFallbackService.LookupStatus.REMOTE_SUCCESS));

        List<TradingSignalDto> results = scanner().scan(StrategyScanContext.market("101"));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.getFirst();
        assertEquals("005930", signal.getStkCd());
        assertEquals(TradingSignal.StrategyType.S11_FRGN_CONT, signal.getStrategy());
        assertEquals(28.6, signal.getSignalScore());
        assertEquals(10900.0, signal.getTp1Price());
        assertEquals(50_000L, signal.getExtra().get("s11_foreign_amount"));
        assertEquals("REMOTE_SUCCESS", signal.getExtra().get("s11_investor_flow_source"));
        assertFalse((Boolean) signal.getExtra().get("s11_flow_clearly_negative"));
        assertEquals(20_000L, signal.getExtra().get("s11_flow_combined_slope"));
    }

    @Test
    void clearlyNegativeRecentFlowIsLiveTransportWithoutJavaScoreChange() {
        when(apiService.fetchKa10035(any())).thenReturn(contResponse(List.of(item("005930", 60_000))));
        stubMarketData();
        var flow = new KiwoomRestFallbackService.InvestorFlowSnapshot(
                "101500", -50_000, -30_000, -80_000, -65_000, 3, true,
                -20_000, -12_000, -8_000, -5_000, true, "DOWN");
        when(restFallbackService.fetchInvestorFlowDetailed("101", "005930"))
                .thenReturn(result(flow, KiwoomRestFallbackService.LookupStatus.CACHE_HIT));

        List<TradingSignalDto> results = scanner().scan(StrategyScanContext.market("101"));

        assertEquals(1, results.size(), "negative enrichment must not hard-gate the candidate");
        assertEquals(28.6, results.getFirst().getSignalScore());
        assertEquals("python", results.getFirst().getExtra().get("strategy_evaluation_owner"));
        assertEquals("live_feature_transport", results.getFirst().getExtra().get("java_enrichment_mode"));
        assertEquals("CACHE_HIT", results.getFirst().getExtra().get("s11_investor_flow_source"));
    }

    @Test
    void callsEnrichmentForOnlyTopFivePrimaryCandidates() {
        var items = IntStream.range(0, 7)
                .mapToObj(i -> item(String.format("%06d", i), 100_000 - i * 1_000L))
                .toList();
        when(apiService.fetchKa10035(any())).thenReturn(contResponse(items));
        when(redisService.getFreshTick(anyString(), eq(RedisMarketDataService.ENTRY_TICK_POLICY)))
                .thenReturn(freshTick(RedisMarketDataService.FreshnessState.FRESH,
                        "2.0", "10000"));
        when(redisService.getFreshStrength(anyString(), eq(5),
                eq(RedisMarketDataService.ENTRY_STRENGTH_POLICY)))
                .thenReturn(freshStrength(RedisMarketDataService.FreshnessState.FRESH, 130.0));
        when(restFallbackService.fetchInvestorFlowDetailed(eq("001"), anyString()))
                .thenReturn(new KiwoomRestFallbackService.LookupResult<>(Optional.empty(),
                        KiwoomRestFallbackService.LookupStatus.BUDGET_EXHAUSTED));

        List<TradingSignalDto> results = scanner().scan(StrategyScanContext.market("001"));

        assertEquals(5, results.size());
        verify(restFallbackService, times(5)).fetchInvestorFlowDetailed(eq("001"), anyString());
        assertEquals("BUDGET_EXHAUSTED", results.getFirst().getExtra().get("s11_investor_flow_source"));
    }

    @Test
    void staleTickAndStrengthDoNotAffectScoreOrTargetPrices() {
        when(apiService.fetchKa10035(any())).thenReturn(contResponse(List.of(item("005930", 60_000))));
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY))
                .thenReturn(freshTick(RedisMarketDataService.FreshnessState.STALE,
                        "9.0", "10000"));
        when(redisService.getFreshStrength(
                "005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(freshStrength(RedisMarketDataService.FreshnessState.STALE, 200.0));
        when(restFallbackService.fetchInvestorFlowDetailed("101", "005930"))
                .thenReturn(new KiwoomRestFallbackService.LookupResult<>(Optional.empty(),
                        KiwoomRestFallbackService.LookupStatus.API_EMPTY));

        TradingSignalDto signal = scanner().scan(StrategyScanContext.market("101")).getFirst();

        assertEquals(21.1, signal.getSignalScore());
        assertEquals(1.5, signal.getVolRatio());
        assertEquals(100.0, signal.getCntrStrength());
        assertEquals(null, signal.getTp1Price());
        assertEquals(null, signal.getTp2Price());
        assertEquals(null, signal.getSlPrice());
        assertEquals("STALE", signal.getExtra().get("s11_tick_freshness"));
        assertEquals("STALE", signal.getExtra().get("s11_strength_freshness"));
    }

    private S11FrgnContScanner scanner() {
        return new S11FrgnContScanner(apiService, redisService, restFallbackService, 5);
    }

    private void stubMarketData() {
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY))
                .thenReturn(freshTick(RedisMarketDataService.FreshnessState.FRESH,
                        "2.0", "10000"));
        when(redisService.getFreshStrength(
                "005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(freshStrength(RedisMarketDataService.FreshnessState.FRESH, 130.0));
    }

    private RedisMarketDataService.FreshData<Map<Object, Object>> freshTick(
            RedisMarketDataService.FreshnessState state, String volRatio, String curPrice) {
        return new RedisMarketDataService.FreshData<>(Map.of(
                "vol_ratio", volRatio, "cur_prc", curPrice), null, null, state, "redis");
    }

    private RedisMarketDataService.FreshData<Double> freshStrength(
            RedisMarketDataService.FreshnessState state, double value) {
        return new RedisMarketDataService.FreshData<>(value, null, null, state, "redis");
    }

    private KiwoomRestFallbackService.LookupResult<KiwoomRestFallbackService.InvestorFlowSnapshot> result(
            KiwoomRestFallbackService.InvestorFlowSnapshot snapshot,
            KiwoomRestFallbackService.LookupStatus status) {
        return new KiwoomRestFallbackService.LookupResult<>(Optional.of(snapshot), status);
    }

    private KiwoomApiResponses.FrgnContNettrdUpperResponse contResponse(
            List<KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem> items) {
        var response = new KiwoomApiResponses.FrgnContNettrdUpperResponse();
        ReflectionTestUtils.setField(response, "items", items);
        return response;
    }

    private KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem item(
            String stkCd, long total) {
        var item = new KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem();
        ReflectionTestUtils.setField(item, "stkCd", stkCd);
        ReflectionTestUtils.setField(item, "stkNm", "Stock " + stkCd);
        ReflectionTestUtils.setField(item, "dm1", "+10,000");
        ReflectionTestUtils.setField(item, "dm2", "+20,000");
        ReflectionTestUtils.setField(item, "dm3", "+30,000");
        ReflectionTestUtils.setField(item, "tot", "+" + total);
        ReflectionTestUtils.setField(item, "limitExhRt", "2.0");
        return item;
    }
}
