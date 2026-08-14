package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomSupplementalResponses;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S12ClosingStrengthEvaluatorTests {

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Mock
    KiwoomApiService kiwoomApiService;

    @Test
    void evaluatesClosingStrengthCandidate() {
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY)).thenReturn(fresh(Map.of(
                "cur_prc", "10000",
                "flu_rt", "5.0",
                "stk_nm", "Samsung"
        )));
        when(redisService.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(fresh(130.0));
        when(redisService.getFreshHoga("005930", RedisMarketDataService.ENTRY_HOGA_POLICY)).thenReturn(fresh(Map.of(
                "total_buy_bid_req", "180",
                "total_sel_bid_req", "100"
        )));

        S12ClosingStrengthEvaluator evaluator =
                new S12ClosingStrengthEvaluator(redisService, stockMasterRepository, kiwoomApiService);
        Optional<TradingSignalDto> result = evaluator.evaluate("005930");

        assertTrue(result.isPresent());
        TradingSignalDto signal = result.orElseThrow();
        assertEquals(TradingSignal.StrategyType.S12_CLOSING, signal.getStrategy());
        assertEquals(33.0, signal.getSignalScore());
        assertEquals("closing_strength", signal.getEntryType());
        assertEquals(10600.0, signal.getTp1Price());
        assertEquals(11000.0, signal.getTp2Price());
        assertEquals(9700.0, signal.getSlPrice());
    }

    @Test
    void rejectsHeavySellExitFlow() {
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY)).thenReturn(fresh(Map.of(
                "cur_prc", "10000",
                "flu_rt", "5.0"
        )));
        when(redisService.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(fresh(130.0));
        when(redisService.getFreshHoga("005930", RedisMarketDataService.ENTRY_HOGA_POLICY)).thenReturn(fresh(Map.of(
                "total_buy_bid_req", "180",
                "total_sel_bid_req", "100"
        )));

        KiwoomSupplementalResponses.TodayUpperExitResponse exit =
                new KiwoomSupplementalResponses.TodayUpperExitResponse();
        KiwoomSupplementalResponses.TodayUpperExitResponse.TodayUpperExitItem item =
                new KiwoomSupplementalResponses.TodayUpperExitResponse.TodayUpperExitItem();
        ReflectionTestUtils.setField(item, "sellQty", "600");
        ReflectionTestUtils.setField(item, "buyQty", "50");
        ReflectionTestUtils.setField(exit, "items", List.of(item));
        when(kiwoomApiService.fetchKa10053("005930")).thenReturn(exit);

        S12ClosingStrengthEvaluator evaluator =
                new S12ClosingStrengthEvaluator(redisService, stockMasterRepository, kiwoomApiService);

        assertTrue(evaluator.evaluate("005930").isEmpty());
    }

    @Test
    void rejectsStaleHogaEvenWhenBidRatioIsStrong() {
        when(redisService.getFreshTick("005930", RedisMarketDataService.ENTRY_TICK_POLICY)).thenReturn(fresh(Map.of(
                "cur_prc", "10000",
                "flu_rt", "5.0"
        )));
        when(redisService.getFreshStrength("005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(fresh(130.0));
        when(redisService.getFreshHoga("005930", RedisMarketDataService.ENTRY_HOGA_POLICY)).thenReturn(stale(Map.of(
                "total_buy_bid_req", "1000",
                "total_sel_bid_req", "100"
        )));

        S12ClosingStrengthEvaluator evaluator =
                new S12ClosingStrengthEvaluator(redisService, stockMasterRepository, kiwoomApiService);

        assertTrue(evaluator.evaluate("005930").isEmpty());
    }

    private static <T> RedisMarketDataService.FreshData<T> fresh(T value) {
        return new RedisMarketDataService.FreshData<>(value, Instant.EPOCH, Duration.ZERO,
                RedisMarketDataService.FreshnessState.FRESH, "redis");
    }

    private static <T> RedisMarketDataService.FreshData<T> stale(T value) {
        return new RedisMarketDataService.FreshData<>(value, Instant.EPOCH, Duration.ofMinutes(1),
                RedisMarketDataService.FreshnessState.STALE, "redis");
    }
}
