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

import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S2ViPullbackEvaluatorTests {

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Mock
    KiwoomApiService kiwoomApiService;

    @Test
    void evaluatesViPullbackCandidate() {
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of(
                "cur_prc", "9800",
                "stk_nm", "Samsung"
        )));
        when(redisService.getAvgCntrStrength("005930", 3)).thenReturn(120.0);
        when(redisService.getHogaData("005930")).thenReturn(Optional.of(Map.of(
                "total_buy_bid_req", "180",
                "total_sel_bid_req", "100"
        )));

        S2ViPullbackEvaluator evaluator = new S2ViPullbackEvaluator(redisService, stockMasterRepository, kiwoomApiService);
        Optional<TradingSignalDto> result = evaluator.evaluate("005930", 10000, true);

        assertTrue(result.isPresent());
        TradingSignalDto signal = result.orElseThrow();
        assertEquals(TradingSignal.StrategyType.S2_VI_PULLBACK, signal.getStrategy());
        assertEquals(9800.0, signal.getEntryPrice());
        assertEquals(-2.0, signal.getPullbackPct());
        assertEquals(120.0, signal.getCntrStrength());
        assertEquals(1.8, signal.getBidRatio());
        assertEquals(45.0, signal.getSignalScore());
        assertEquals(10437.0, signal.getTp1Price());
        assertEquals(10731.0, signal.getTp2Price());
        assertEquals(9604.0, signal.getSlPrice());
    }

    @Test
    void rejectsWhenPullbackIsTooShallow() {
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of("cur_prc", "9950")));

        S2ViPullbackEvaluator evaluator = new S2ViPullbackEvaluator(redisService, stockMasterRepository, kiwoomApiService);

        assertTrue(evaluator.evaluate("005930", 10000, false).isEmpty());
    }
}
