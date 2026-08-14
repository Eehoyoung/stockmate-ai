package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S10NewHighEvaluatorTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Test
    void evaluatesDailyNewHighBreakout() {
        KiwoomApiResponses.DailyCandleResponse response = new KiwoomApiResponses.DailyCandleResponse();
        List<KiwoomApiResponses.DailyCandleResponse.DailyCandleItem> candles = new ArrayList<>();
        candles.add(candle("20260703", "100", "112", "99", "110", "4000"));
        candles.add(candle("20260702", "99", "111", "98", "100", "1000"));
        for (int i = 0; i < 19; i++) {
            candles.add(candle("202606" + String.format("%02d", i + 1), "99", "105", "98", "100", "1000"));
        }
        ReflectionTestUtils.setField(response, "candles", candles);

        when(apiService.fetchKa10081("005930")).thenReturn(response);
        when(redisService.getFreshStrength(
                "005930", 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY))
                .thenReturn(new RedisMarketDataService.FreshData<>(
                        130.0, Instant.now(), Duration.ZERO,
                        RedisMarketDataService.FreshnessState.FRESH, "redis"));

        S10NewHighEvaluator evaluator = new S10NewHighEvaluator(
                apiService,
                redisService,
                stockMasterRepository
        );
        Optional<TradingSignalDto> result = evaluator.evaluate("005930");

        assertTrue(result.isPresent());
        TradingSignalDto signal = result.orElseThrow();
        assertEquals("005930", signal.getStkCd());
        assertEquals(TradingSignal.StrategyType.S10_NEW_HIGH, signal.getStrategy());
        assertEquals("new_high_daily", signal.getEntryType());
        assertEquals(110.0, signal.getEntryPrice());
        assertEquals(10.0, signal.getGapPct());
        assertEquals(4.0, signal.getVolRatio());
        assertEquals(300.0, signal.getVolSurgeRt());
        assertEquals(130.0, signal.getCntrStrength());
        assertEquals(58.0, signal.getSignalScore());
        assertEquals(118.8, signal.getTp1Price());
        assertEquals(126.5, signal.getTp2Price());
        assertEquals(109.89, signal.getSlPrice());
        assertEquals(-0.1, signal.getStopPct());
    }

    @Test
    void rejectsOverextendedPriceAboveMa20() {
        KiwoomApiResponses.DailyCandleResponse response = new KiwoomApiResponses.DailyCandleResponse();
        List<KiwoomApiResponses.DailyCandleResponse.DailyCandleItem> candles = new ArrayList<>();
        candles.add(candle("20260703", "100", "160", "99", "150", "4000"));
        for (int i = 0; i < 20; i++) {
            candles.add(candle("202606" + String.format("%02d", i + 1), "99", "120", "98", "100", "1000"));
        }
        ReflectionTestUtils.setField(response, "candles", candles);

        when(apiService.fetchKa10081("005930")).thenReturn(response);

        S10NewHighEvaluator evaluator = new S10NewHighEvaluator(
                apiService,
                redisService,
                stockMasterRepository
        );

        assertTrue(evaluator.evaluate("005930").isEmpty());
    }

    private KiwoomApiResponses.DailyCandleResponse.DailyCandleItem candle(
            String date,
            String open,
            String high,
            String low,
            String close,
            String volume
    ) {
        KiwoomApiResponses.DailyCandleResponse.DailyCandleItem item =
                new KiwoomApiResponses.DailyCandleResponse.DailyCandleItem();
        ReflectionTestUtils.setField(item, "date", date);
        ReflectionTestUtils.setField(item, "openPric", open);
        ReflectionTestUtils.setField(item, "highPric", high);
        ReflectionTestUtils.setField(item, "lowPric", low);
        ReflectionTestUtils.setField(item, "curPrc", close);
        ReflectionTestUtils.setField(item, "trdeQty", volume);
        return item;
    }
}
