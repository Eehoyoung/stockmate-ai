package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.KiwoomRestFallbackService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S4BigCandleEvaluatorTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Mock
    KiwoomApiService kiwoomApiService;

    @Mock
    KiwoomRestFallbackService restFallbackService;

    @Test
    void evaluatesLargeBullishMinuteCandleWithVolumeSurge() {
        KiwoomApiResponses.MinuteCandleResponse response = new KiwoomApiResponses.MinuteCandleResponse();
        List<KiwoomApiResponses.MinuteCandleResponse.CandleItem> candles = new ArrayList<>();
        candles.add(candle("100", "107", "99", "106", "6000"));
        for (int i = 0; i < 9; i++) {
            candles.add(candle("99", "105", "98", "100", "1000"));
        }
        ReflectionTestUtils.setField(response, "candles", candles);

        when(apiService.fetchKa10080(eq("005930"), eq("5"), any())).thenReturn(response);
        when(redisService.getFreshStrength(
                "005930", 3, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(new RedisMarketDataService.FreshData<>(
                        130.0, null, null, RedisMarketDataService.FreshnessState.FRESH, "redis"));
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of("stk_nm", "Samsung")));

        S4BigCandleEvaluator evaluator = new S4BigCandleEvaluator(
                apiService,
                redisService,
                stockMasterRepository,
                kiwoomApiService,
                restFallbackService
        );
        Optional<TradingSignalDto> result = evaluator.evaluate("005930");

        assertTrue(result.isPresent());
        TradingSignalDto signal = result.orElseThrow();
        assertEquals("005930", signal.getStkCd());
        assertEquals("Samsung", signal.getStkNm());
        assertEquals(TradingSignal.StrategyType.S4_BIG_CANDLE, signal.getStrategy());
        assertEquals(106.0, signal.getEntryPrice());
        assertEquals(6.0, signal.getGapPct());
        assertEquals(6.0, signal.getVolRatio());
        assertEquals(130.0, signal.getCntrStrength());
        assertEquals(0.75, signal.getBodyRatio());
        assertEquals(true, signal.getIsNewHigh());
        assertEquals(54.5, signal.getSignalScore());
        assertEquals("big_candle_breakout", signal.getEntryType());
        assertEquals(112.36, signal.getTp1Price());
        assertEquals(115.54, signal.getTp2Price());
        assertEquals(102.82, signal.getSlPrice());
        assertEquals("REDIS_FRESH", signal.getExtra().get("s4_strength_source"));
    }

    @Test
    void rejectsWhenVolumeSurgeIsTooSmall() {
        KiwoomApiResponses.MinuteCandleResponse response = new KiwoomApiResponses.MinuteCandleResponse();
        List<KiwoomApiResponses.MinuteCandleResponse.CandleItem> candles = new ArrayList<>();
        candles.add(candle("100", "107", "99", "106", "2000"));
        for (int i = 0; i < 9; i++) {
            candles.add(candle("99", "105", "98", "100", "1000"));
        }
        ReflectionTestUtils.setField(response, "candles", candles);

        when(apiService.fetchKa10080(eq("005930"), eq("5"), any())).thenReturn(response);

        S4BigCandleEvaluator evaluator = new S4BigCandleEvaluator(
                apiService,
                redisService,
                stockMasterRepository,
                kiwoomApiService,
                restFallbackService
        );

        assertTrue(evaluator.evaluate("005930").isEmpty());
    }

    @Test
    void fallsBackToBoundedRestStrengthWhenRedisStrengthIsStale() {
        KiwoomApiResponses.MinuteCandleResponse response = new KiwoomApiResponses.MinuteCandleResponse();
        List<KiwoomApiResponses.MinuteCandleResponse.CandleItem> candles = new ArrayList<>();
        candles.add(candle("100", "107", "99", "106", "6000"));
        for (int i = 0; i < 9; i++) candles.add(candle("99", "105", "98", "100", "1000"));
        ReflectionTestUtils.setField(response, "candles", candles);

        when(apiService.fetchKa10080(eq("005930"), eq("5"), any())).thenReturn(response);
        when(redisService.getFreshStrength(
                "005930", 3, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(new RedisMarketDataService.FreshData<>(
                        140.0, null, null, RedisMarketDataService.FreshnessState.STALE, "redis"));
        var snapshot = new KiwoomRestFallbackService.StrengthSnapshot(
                "101500", 125.0, 128.0, 122.0, 119.0);
        when(restFallbackService.fetchStrengthDetailed("005930"))
                .thenReturn(new KiwoomRestFallbackService.LookupResult<>(
                        Optional.of(snapshot), KiwoomRestFallbackService.LookupStatus.CACHE_HIT));
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of("stk_nm", "Samsung")));

        S4BigCandleEvaluator evaluator = new S4BigCandleEvaluator(
                apiService, redisService, stockMasterRepository, kiwoomApiService, restFallbackService);

        var result = evaluator.evaluate("005930");

        assertTrue(result.isPresent());
        assertEquals(128.0, result.orElseThrow().getCntrStrength());
        assertEquals("CACHE_HIT", result.orElseThrow().getExtra().get("s4_strength_source"));
    }

    private KiwoomApiResponses.MinuteCandleResponse.CandleItem candle(
            String open,
            String high,
            String low,
            String close,
            String volume
    ) {
        KiwoomApiResponses.MinuteCandleResponse.CandleItem item =
                new KiwoomApiResponses.MinuteCandleResponse.CandleItem();
        ReflectionTestUtils.setField(item, "openPric", open);
        ReflectionTestUtils.setField(item, "highPric", high);
        ReflectionTestUtils.setField(item, "lowPric", low);
        ReflectionTestUtils.setField(item, "curPrc", close);
        ReflectionTestUtils.setField(item, "trdeQty", volume);
        return item;
    }
}
