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
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S3InstFrgnScannerTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Mock
    KiwoomRestFallbackService restFallbackService;

    @Test
    void scansOnlyContinuousInstitutionForeignBuyCandidates() {
        KiwoomApiResponses.IntradayInvestorResponse intraday = new KiwoomApiResponses.IntradayInvestorResponse();
        KiwoomApiResponses.IntradayInvestorResponse.InvestorItem included = new KiwoomApiResponses.IntradayInvestorResponse.InvestorItem();
        ReflectionTestUtils.setField(included, "stkCd", "005930");
        ReflectionTestUtils.setField(included, "stkNm", "Samsung");
        ReflectionTestUtils.setField(included, "netBuyAmt", "+2,000,000");
        KiwoomApiResponses.IntradayInvestorResponse.InvestorItem excluded = new KiwoomApiResponses.IntradayInvestorResponse.InvestorItem();
        ReflectionTestUtils.setField(excluded, "stkCd", "000660");
        ReflectionTestUtils.setField(excluded, "stkNm", "SK Hynix");
        ReflectionTestUtils.setField(excluded, "netBuyAmt", "+9,000,000");
        ReflectionTestUtils.setField(intraday, "items", List.of(included, excluded));

        KiwoomApiResponses.InstFrgnContinuousResponse continuous = new KiwoomApiResponses.InstFrgnContinuousResponse();
        KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem cont = new KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem();
        ReflectionTestUtils.setField(cont, "stkCd", "005930");
        ReflectionTestUtils.setField(cont, "contDtCnt", "3");
        ReflectionTestUtils.setField(continuous, "items", List.of(cont));

        when(apiService.post(
                eq("ka10063"),
                eq("/api/dostk/mrkcond"),
                any(),
                eq(KiwoomApiResponses.IntradayInvestorResponse.class)
        )).thenReturn(intraday);
        when(apiService.post(
                eq("ka10131"),
                eq("/api/dostk/frgnistt"),
                any(),
                eq(KiwoomApiResponses.InstFrgnContinuousResponse.class)
        )).thenReturn(continuous);
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY))
                .thenReturn(new RedisMarketDataService.FreshData<>(Map.of(
                        "vol_ratio", "2.0", "cur_prc", "10000"),
                        Instant.EPOCH, Duration.ZERO,
                        RedisMarketDataService.FreshnessState.FRESH, "redis"));
        var flow = new KiwoomRestFallbackService.InvestorFlowSnapshot(
                "101500", 100, 200, 300, 250, 3, false,
                120, 50, 70, -20, true, "DOWN");
        when(restFallbackService.fetchInvestorFlowDetailed("101", "005930"))
                .thenReturn(new KiwoomRestFallbackService.LookupResult<>(Optional.of(flow),
                        KiwoomRestFallbackService.LookupStatus.REMOTE_SUCCESS));

        S3InstFrgnScanner scanner = new S3InstFrgnScanner(apiService, redisService, restFallbackService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.market("101"));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals("005930", signal.getStkCd());
        assertEquals("Samsung", signal.getStkNm());
        assertEquals(TradingSignal.StrategyType.S3_INST_FRGN, signal.getStrategy());
        assertEquals(2_000_000L, signal.getNetBuyAmt());
        assertEquals(2.0, signal.getVolRatio());
        assertEquals(3, signal.getContinuousDays());
        assertEquals(12.0, signal.getSignalScore());
        assertEquals(10600.0, signal.getTp1Price());
        assertEquals(11000.0, signal.getTp2Price());
        assertEquals(9700.0, signal.getSlPrice());
        assertEquals(120L, signal.getExtra().get("s3_flow_combined_slope"));
        assertEquals(true, signal.getExtra().get("s3_flow_recent_reversal"));
        assertEquals("REMOTE_SUCCESS", signal.getExtra().get("s3_investor_flow_source"));
        assertEquals("python", signal.getExtra().get("strategy_evaluation_owner"));
    }

    @Test
    void enrichesOnlyTopFiveCandidatesWithoutChangingScores() {
        var investorItems = new java.util.ArrayList<KiwoomApiResponses.IntradayInvestorResponse.InvestorItem>();
        var continuousItems = new java.util.ArrayList<KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem>();
        for (int i = 0; i < 7; i++) {
            String code = String.format("%06d", i);
            var investor = new KiwoomApiResponses.IntradayInvestorResponse.InvestorItem();
            ReflectionTestUtils.setField(investor, "stkCd", code);
            ReflectionTestUtils.setField(investor, "netBuyAmt", String.valueOf(7_000_000 - i * 100_000));
            investorItems.add(investor);
            var continuous = new KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem();
            ReflectionTestUtils.setField(continuous, "stkCd", code);
            ReflectionTestUtils.setField(continuous, "contDtCnt", "3");
            continuousItems.add(continuous);
        }
        var intraday = new KiwoomApiResponses.IntradayInvestorResponse();
        ReflectionTestUtils.setField(intraday, "items", investorItems);
        var continuous = new KiwoomApiResponses.InstFrgnContinuousResponse();
        ReflectionTestUtils.setField(continuous, "items", continuousItems);
        when(apiService.post(eq("ka10063"), anyString(), any(),
                eq(KiwoomApiResponses.IntradayInvestorResponse.class))).thenReturn(intraday);
        when(apiService.post(eq("ka10131"), anyString(), any(),
                eq(KiwoomApiResponses.InstFrgnContinuousResponse.class))).thenReturn(continuous);
        when(redisService.getFreshTick(anyString(), eq(RedisMarketDataService.ENTRY_TICK_POLICY)))
                .thenReturn(new RedisMarketDataService.FreshData<>(Map.of(
                        "vol_ratio", "2.0", "cur_prc", "10000"), Instant.EPOCH, Duration.ZERO,
                        RedisMarketDataService.FreshnessState.FRESH, "redis"));
        when(restFallbackService.fetchInvestorFlowDetailed(eq("001"), anyString()))
                .thenReturn(new KiwoomRestFallbackService.LookupResult<>(Optional.empty(),
                        KiwoomRestFallbackService.LookupStatus.BUDGET_EXHAUSTED));

        var results = new S3InstFrgnScanner(apiService, redisService, restFallbackService)
                .scan(StrategyScanContext.market("001"));

        assertEquals(5, results.size());
        assertEquals(17.0, results.getFirst().getSignalScore());
        verify(restFallbackService, times(5))
                .fetchInvestorFlowDetailed(eq("001"), anyString());
    }
}
