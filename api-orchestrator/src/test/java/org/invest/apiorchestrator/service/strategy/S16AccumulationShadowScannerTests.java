package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.StockMaster;
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

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S16AccumulationShadowScannerTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Test
    void scansMediumCapAccumulationCandidate() {
        KiwoomApiResponses.DailyCandleResponse response = new KiwoomApiResponses.DailyCandleResponse();
        List<KiwoomApiResponses.DailyCandleResponse.DailyCandleItem> candles = new ArrayList<>();
        candles.add(candle("20260703", "104", "109", "101", "108", "2000"));
        for (int i = 1; i < 20; i++) {
            candles.add(candle("202606" + String.format("%02d", i), "98", i == 3 ? "110" : "106", "92", "100", "1000"));
        }
        for (int i = 20; i < 60; i++) {
            candles.add(candle("202605" + String.format("%02d", i - 19), "96", "104", "90", "98", "1000"));
        }
        ReflectionTestUtils.setField(response, "candles", candles);

        StockMaster master = StockMaster.builder()
                .stkCd("005930")
                .stkNm("Samsung")
                .market("101")
                .marketCap(500_000_000_000L)
                .build();

        when(apiService.fetchKa10081("005930")).thenReturn(response);
        when(stockMasterRepository.findByStkCd("005930")).thenReturn(Optional.of(master));
        when(redisService.getAvgCntrStrength("005930", 5)).thenReturn(125.0);
        when(redisService.getHogaData("005930")).thenReturn(Optional.of(Map.of(
                "total_buy_bid_req", "1400",
                "total_sel_bid_req", "1000"
        )));

        S16AccumulationShadowScanner scanner = new S16AccumulationShadowScanner(
                apiService,
                redisService,
                stockMasterRepository
        );
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.candidates(List.of("005930")));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals(TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW, signal.getStrategy());
        assertEquals("accumulation_shadow_daily", signal.getEntryType());
        assertEquals(108.0, signal.getEntryPrice());
        assertTrue(signal.getSignalScore() >= 55.0);
        assertEquals(1.4, signal.getBidRatio());
        assertEquals(125.0, signal.getCntrStrength());
        assertTrue(signal.getExtra().containsKey("s16_box_high"));
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
        ReflectionTestUtils.setField(item, "trdePrica", "3000000000");
        return item;
    }
}
