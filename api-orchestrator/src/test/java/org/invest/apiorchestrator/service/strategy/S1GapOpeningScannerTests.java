package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S1GapOpeningScannerTests {

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Mock
    KiwoomApiService kiwoomApiService;

    @Test
    void scansGapOpeningCandidateWithExpectedDataStrengthAndBidRatio() {
        when(redisService.getFreshExpected("005930", RedisMarketDataService.ENTRY_EXPECTED_POLICY)).thenReturn(fresh(Map.of(
                "pred_pre_pric", "10000",
                "exp_cntr_pric", "10400"
        )));
        when(redisService.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(fresh(140.0));
        when(redisService.getFreshHoga("005930", RedisMarketDataService.ENTRY_HOGA_POLICY)).thenReturn(fresh(Map.of(
                "total_buy_bid_req", "200",
                "total_sel_bid_req", "100"
        )));
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of("stk_nm", " Samsung ")));

        S1GapOpeningScanner scanner = new S1GapOpeningScanner(redisService, stockMasterRepository, kiwoomApiService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.candidates(List.of("005930")));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals("005930", signal.getStkCd());
        assertEquals("Samsung", signal.getStkNm());
        assertEquals(TradingSignal.StrategyType.S1_GAP_OPEN, signal.getStrategy());
        assertEquals(10400.0, signal.getEntryPrice());
        assertEquals(4.0, signal.getGapPct());
        assertEquals(140.0, signal.getCntrStrength());
        assertEquals(2.0, signal.getBidRatio());
        assertEquals(10920.0, signal.getTp1Price());
        assertEquals(11336.0, signal.getTp2Price());
        assertEquals(10192.0, signal.getSlPrice());
        verify(kiwoomApiService, never()).fetchKa10001("005930");
    }

    @Test
    void rejectsWhenGapIsOutsidePolicyRange() {
        when(redisService.getFreshExpected("005930", RedisMarketDataService.ENTRY_EXPECTED_POLICY)).thenReturn(fresh(Map.of(
                "pred_pre_pric", "10000",
                "exp_cntr_pric", "10200"
        )));

        S1GapOpeningScanner scanner = new S1GapOpeningScanner(redisService, stockMasterRepository, kiwoomApiService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.candidates(List.of("005930")));

        assertFalse(results.iterator().hasNext());
    }

    @Test
    void keepsLegacyNeutralStrengthWhenSamplesAreMissing() {
        when(redisService.getFreshExpected("005930", RedisMarketDataService.ENTRY_EXPECTED_POLICY)).thenReturn(fresh(Map.of(
                "pred_pre_pric", "10000",
                "exp_cntr_pric", "10400"
        )));
        when(redisService.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(missing());
        when(redisService.getFreshHoga("005930", RedisMarketDataService.ENTRY_HOGA_POLICY)).thenReturn(fresh(Map.of(
                "total_buy_bid_req", "200",
                "total_sel_bid_req", "100"
        )));

        S1GapOpeningScanner scanner = new S1GapOpeningScanner(redisService, stockMasterRepository, kiwoomApiService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.candidates(List.of("005930")));

        assertEquals(1, results.size());
        assertEquals(100.0, results.get(0).getCntrStrength());
    }

    @Test
    void staleExpectedStrongValueCannotPassWithoutFreshTickFallback() {
        when(redisService.getFreshExpected("005930", RedisMarketDataService.ENTRY_EXPECTED_POLICY)).thenReturn(stale(Map.of(
                "pred_pre_pric", "10000",
                "exp_cntr_pric", "10400"
        )));
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY))
                .thenReturn(missing());

        S1GapOpeningScanner scanner = new S1GapOpeningScanner(redisService, stockMasterRepository, kiwoomApiService);

        assertFalse(scanner.scan(StrategyScanContext.candidates(List.of("005930"))).iterator().hasNext());
        verify(redisService, never()).getFreshStrength(
                "005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
    }

    private static <T> RedisMarketDataService.FreshData<T> fresh(T value) {
        return new RedisMarketDataService.FreshData<>(value, Instant.EPOCH, Duration.ZERO,
                RedisMarketDataService.FreshnessState.FRESH, "redis");
    }

    private static <T> RedisMarketDataService.FreshData<T> stale(T value) {
        return new RedisMarketDataService.FreshData<>(value, Instant.EPOCH, Duration.ofMinutes(1),
                RedisMarketDataService.FreshnessState.STALE, "redis");
    }

    private static <T> RedisMarketDataService.FreshData<T> missing() {
        return new RedisMarketDataService.FreshData<>(null, null, null,
                RedisMarketDataService.FreshnessState.MISSING, "redis");
    }
}
