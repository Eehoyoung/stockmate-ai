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
        when(redisService.getExpectedData("005930")).thenReturn(Optional.of(Map.of(
                "pred_pre_pric", "10000",
                "exp_cntr_pric", "10400"
        )));
        when(redisService.getAvgCntrStrength("005930", 5)).thenReturn(140.0);
        when(redisService.hasStrengthData("005930")).thenReturn(true);
        when(redisService.getHogaData("005930")).thenReturn(Optional.of(Map.of(
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
        when(redisService.getExpectedData("005930")).thenReturn(Optional.of(Map.of(
                "pred_pre_pric", "10000",
                "exp_cntr_pric", "10200"
        )));

        S1GapOpeningScanner scanner = new S1GapOpeningScanner(redisService, stockMasterRepository, kiwoomApiService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.candidates(List.of("005930")));

        assertFalse(results.iterator().hasNext());
    }
}
