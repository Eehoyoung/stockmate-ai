package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S6ThemeLaggardScannerTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Test
    void scansThemeLaggardsBelowThemeLeadersWithEnoughStrength() {
        KiwoomApiResponses.ThemeGroupResponse themes = new KiwoomApiResponses.ThemeGroupResponse();
        KiwoomApiResponses.ThemeGroupResponse.ThemeGroupItem theme = new KiwoomApiResponses.ThemeGroupResponse.ThemeGroupItem();
        ReflectionTestUtils.setField(theme, "themaGrpCd", "T001");
        ReflectionTestUtils.setField(theme, "themaNm", "AI");
        ReflectionTestUtils.setField(theme, "fluRt", "+6.00");
        ReflectionTestUtils.setField(themes, "items", List.of(theme));

        KiwoomApiResponses.ThemeStockResponse stocks = new KiwoomApiResponses.ThemeStockResponse();
        KiwoomApiResponses.ThemeStockResponse.ThemeStockItem included = stock("005930", "Samsung", "+2.00");
        KiwoomApiResponses.ThemeStockResponse.ThemeStockItem low = stock("111111", "Low", "+0.30");
        KiwoomApiResponses.ThemeStockResponse.ThemeStockItem leader = stock("222222", "Leader", "+4.00");
        KiwoomApiResponses.ThemeStockResponse.ThemeStockItem hot = stock("333333", "Hot", "+6.00");
        ReflectionTestUtils.setField(stocks, "items", List.of(low, included, leader, hot));

        when(apiService.post(
                eq("ka90001"),
                eq("/api/dostk/thme"),
                any(),
                eq(KiwoomApiResponses.ThemeGroupResponse.class)
        )).thenReturn(themes);
        when(apiService.post(
                eq("ka90002"),
                eq("/api/dostk/thme"),
                any(),
                eq(KiwoomApiResponses.ThemeStockResponse.class)
        )).thenReturn(stocks);
        when(redisService.getAvgCntrStrength("005930", 3)).thenReturn(130.0);
        when(redisService.hasStrengthData("005930")).thenReturn(true);
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of("cur_prc", "10000")));

        S6ThemeLaggardScanner scanner = new S6ThemeLaggardScanner(apiService, redisService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.market(""));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals("005930", signal.getStkCd());
        assertEquals("Samsung", signal.getStkNm());
        assertEquals(TradingSignal.StrategyType.S6_THEME_LAGGARD, signal.getStrategy());
        assertEquals("AI", signal.getThemeName());
        assertEquals(2.0, signal.getGapPct());
        assertEquals(130.0, signal.getCntrStrength());
        assertEquals(47.0, signal.getSignalScore());
        assertEquals("theme_laggard_1min", signal.getEntryType());
        assertEquals(10600.0, signal.getTp1Price());
        assertEquals(10900.0, signal.getTp2Price());
        assertEquals(9700.0, signal.getSlPrice());
    }

    private KiwoomApiResponses.ThemeStockResponse.ThemeStockItem stock(String code, String name, String fluRt) {
        KiwoomApiResponses.ThemeStockResponse.ThemeStockItem item = new KiwoomApiResponses.ThemeStockResponse.ThemeStockItem();
        ReflectionTestUtils.setField(item, "stkCd", code);
        ReflectionTestUtils.setField(item, "stkNm", name);
        ReflectionTestUtils.setField(item, "fluRt", fluRt);
        return item;
    }
}
