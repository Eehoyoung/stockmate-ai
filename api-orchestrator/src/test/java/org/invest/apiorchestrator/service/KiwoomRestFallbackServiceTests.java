package org.invest.apiorchestrator.service;

import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mockingDetails;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KiwoomRestFallbackServiceTests {

    @Test
    void cachesSuccessfulStrengthSnapshot() {
        KiwoomApiService apiService = mock(KiwoomApiService.class);
        when(apiService.fetchKa10046("005930")).thenReturn(strengthResponse("125.0", "130.0"));
        AtomicLong clock = new AtomicLong(1_000L);
        var service = new KiwoomRestFallbackService(apiService, clock::get, Duration.ofSeconds(10), 5);

        var first = service.fetchStrength("005930");
        clock.addAndGet(5_000L);
        var second = service.fetchStrengthDetailed("005930");

        assertEquals(130.0, first.orElseThrow().effectiveStrength());
        assertEquals(first, second.value());
        assertEquals(KiwoomRestFallbackService.LookupStatus.CACHE_HIT, second.status());
        verify(apiService, times(1)).fetchKa10046("005930");
    }

    @Test
    void cachesAndClassifiesRecentKa10064InvestorFlow() {
        KiwoomApiService apiService = mock(KiwoomApiService.class);
        when(apiService.fetchKa10064("001", "005930")).thenReturn(investorFlowResponse(
                flowItem("095200", "-80", "-30"),
                flowItem("090000", "+10", "0"),
                flowItem("092200", "-40", "+5")));
        AtomicLong clock = new AtomicLong(1_000L);
        var service = new KiwoomRestFallbackService(apiService, clock::get, Duration.ofSeconds(10), 5);

        var first = service.fetchInvestorFlowDetailed("001", "A005930_KRX");
        clock.addAndGet(5_000L);
        var second = service.fetchInvestorFlowDetailed("001", "005930");

        var snapshot = first.value().orElseThrow();
        assertEquals(KiwoomRestFallbackService.LookupStatus.REMOTE_SUCCESS, first.status());
        assertEquals("095200", snapshot.observedAt());
        assertEquals(-110L, snapshot.latestCombinedAmount());
        assertEquals(-120L, snapshot.combinedSlope());
        assertEquals(-75L, snapshot.latestDelta());
        assertTrue(snapshot.recentCombinedAverage() < 0);
        assertTrue(snapshot.clearlyNegative());
        assertEquals(KiwoomRestFallbackService.LookupStatus.CACHE_HIT, second.status());
        verify(apiService, times(1)).fetchKa10064("001", "005930");
    }

    @Test
    void detectsRecentCombinedFlowReversalDirection() {
        KiwoomApiService apiService = mock(KiwoomApiService.class);
        when(apiService.fetchKa10064("001", "005930")).thenReturn(investorFlowResponse(
                flowItem("095200", "+20", "0"),
                flowItem("092200", "-20", "0"),
                flowItem("090000", "+10", "0")));
        var service = new KiwoomRestFallbackService(
                apiService, () -> 1_000L, Duration.ofSeconds(10), 5);

        var snapshot = service.fetchInvestorFlow("001", "005930").orElseThrow();

        assertEquals(10L, snapshot.combinedSlope());
        assertEquals(40L, snapshot.latestDelta());
        assertTrue(snapshot.recentReversal());
        assertEquals("UP", snapshot.recentReversalDirection());
    }

    @Test
    void cachesKa10054ViHistoryAndPreservesReferenceFeatures() {
        KiwoomApiService apiService = mock(KiwoomApiService.class);
        when(apiService.fetchKa10054("001", "005930")).thenReturn(viResponse(
                viItem("101000", "101200", "10000", "동적+정적", "9500", "9000", "3"),
                viItem("102000", "102200", "11000", "동적", "10000", "0", "4")));
        AtomicLong clock = new AtomicLong(1_000L);
        var service = new KiwoomRestFallbackService(apiService, clock::get, Duration.ofSeconds(10), 5);

        var first = service.fetchViHistoryDetailed("001", "A005930");
        clock.addAndGet(5_000L);
        var second = service.fetchViHistoryDetailed("001", "005930");

        var snapshot = first.value().orElseThrow();
        assertEquals(KiwoomRestFallbackService.LookupStatus.REMOTE_SUCCESS, first.status());
        assertEquals("102200", snapshot.releaseTime());
        assertEquals(4, snapshot.activationCount());
        assertTrue(snapshot.dynamic());
        assertTrue(snapshot.referenceConsistent());
        assertEquals(KiwoomRestFallbackService.LookupStatus.CACHE_HIT, second.status());
        verify(apiService, times(1)).fetchKa10054("001", "005930");
    }

    @Test
    void rejectsAdditionalRemoteCallsWhenMinuteBudgetIsExhausted() {
        KiwoomApiService apiService = mock(KiwoomApiService.class);
        when(apiService.fetchKa10046("005930")).thenReturn(strengthResponse("125.0", "130.0"));
        var service = new KiwoomRestFallbackService(apiService, () -> 1_000L, Duration.ZERO, 1);

        assertTrue(service.fetchStrength("005930").isPresent());
        assertEquals(Optional.empty(), service.fetchStrength("000660"));

        verify(apiService, times(1)).fetchKa10046(anyString());
    }

    @Test
    void mixedConcurrentRequestsNeverExceedSharedMinuteBudget() throws Exception {
        KiwoomApiService apiService = mock(KiwoomApiService.class);
        when(apiService.fetchKa10046(anyString())).thenReturn(strengthResponse("125.0", "130.0"));
        when(apiService.fetchKa10064(anyString(), anyString())).thenReturn(investorFlowResponse(
                flowItem("095200", "10", "5"), flowItem("092200", "8", "4")));
        when(apiService.fetchKa10054(anyString(), anyString())).thenReturn(viResponse(
                viItem("101000", "101200", "10000", "동적", "9500", "0", "1")));
        int budget = 5;
        var service = new KiwoomRestFallbackService(apiService, () -> 1_000L, Duration.ZERO, budget);
        var executor = Executors.newFixedThreadPool(10);
        var start = new CountDownLatch(1);

        try {
            var futures = java.util.stream.IntStream.range(0, 20)
                    .mapToObj(i -> executor.submit(() -> {
                        start.await();
                        String stkCd = String.format("%06d", i);
                        return switch (i % 3) {
                            case 0 -> service.fetchStrengthDetailed(stkCd);
                            case 1 -> service.fetchInvestorFlowDetailed("001", stkCd);
                            default -> service.fetchViHistoryDetailed("001", stkCd);
                        };
                    }))
                    .toList();
            start.countDown();
            for (var future : futures) future.get(5, TimeUnit.SECONDS);
        } finally {
            executor.shutdownNow();
        }

        long remoteCalls = mockingDetails(apiService).getInvocations().stream()
                .filter(invocation -> invocation.getMethod().getName().equals("fetchKa10046")
                        || invocation.getMethod().getName().equals("fetchKa10064")
                        || invocation.getMethod().getName().equals("fetchKa10054"))
                .count();
        assertEquals(budget, remoteCalls);
    }

    private KiwoomApiResponses.CntrStrengthTimeResponse strengthResponse(
            String current, String fiveMinute) {
        var response = new KiwoomApiResponses.CntrStrengthTimeResponse();
        var item = new KiwoomApiResponses.CntrStrengthTimeResponse.CntrStrengthItem();
        ReflectionTestUtils.setField(item, "cntrTm", "101500");
        ReflectionTestUtils.setField(item, "cntrStr", current);
        ReflectionTestUtils.setField(item, "cntrStr5min", fiveMinute);
        ReflectionTestUtils.setField(response, "cntrStrTm", List.of(item));
        return response;
    }

    private KiwoomApiResponses.IntradayInvestorChartResponse investorFlowResponse(
            KiwoomApiResponses.IntradayInvestorChartResponse.InvestorChartItem... items) {
        var response = new KiwoomApiResponses.IntradayInvestorChartResponse();
        ReflectionTestUtils.setField(response, "items", List.of(items));
        return response;
    }

    private KiwoomApiResponses.IntradayInvestorChartResponse.InvestorChartItem flowItem(
            String time, String foreign, String institution) {
        var item = new KiwoomApiResponses.IntradayInvestorChartResponse.InvestorChartItem();
        ReflectionTestUtils.setField(item, "time", time);
        ReflectionTestUtils.setField(item, "foreignInvestor", foreign);
        ReflectionTestUtils.setField(item, "institution", institution);
        return item;
    }

    private KiwoomApiResponses.ViActivationResponse viResponse(
            KiwoomApiResponses.ViActivationResponse.ViActivationItem... items) {
        var response = new KiwoomApiResponses.ViActivationResponse();
        ReflectionTestUtils.setField(response, "items", List.of(items));
        return response;
    }

    private KiwoomApiResponses.ViActivationResponse.ViActivationItem viItem(
            String activationTime, String releaseTime, String activationPrice,
            String type, String dynamicReference, String staticReference, String count) {
        var item = new KiwoomApiResponses.ViActivationResponse.ViActivationItem();
        ReflectionTestUtils.setField(item, "stkCd", "005930");
        ReflectionTestUtils.setField(item, "activationTime", activationTime);
        ReflectionTestUtils.setField(item, "releaseTime", releaseTime);
        ReflectionTestUtils.setField(item, "activationPrice", activationPrice);
        ReflectionTestUtils.setField(item, "applicationType", type);
        ReflectionTestUtils.setField(item, "dynamicReferencePrice", dynamicReference);
        ReflectionTestUtils.setField(item, "staticReferencePrice", staticReference);
        ReflectionTestUtils.setField(item, "activationCount", count);
        return item;
    }
}
