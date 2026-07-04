package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

@ExtendWith(MockitoExtension.class)
class DailyStrategyScannerTypeTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Mock
    StockMasterRepository stockMasterRepository;

    @Test
    void registersDailySwingScannersByStrategyType() {
        List<StrategyScanner> scanners = List.of(
                new S8GoldenCrossScanner(apiService, redisService, stockMasterRepository),
                new S9PullbackSwingScanner(apiService, redisService, stockMasterRepository),
                new S13BoxBreakoutScanner(apiService, redisService, stockMasterRepository),
                new S14OversoldBounceScanner(apiService, redisService, stockMasterRepository),
                new S15MomentumAlignScanner(apiService, redisService, stockMasterRepository),
                new S16AccumulationShadowScanner(apiService, redisService, stockMasterRepository)
        );

        StrategyScannerRegistry registry = new StrategyScannerRegistry(scanners);

        assertEquals(TradingSignal.StrategyType.S8_GOLDEN_CROSS,
                registry.find(TradingSignal.StrategyType.S8_GOLDEN_CROSS).orElseThrow().type());
        assertEquals(TradingSignal.StrategyType.S9_PULLBACK_SWING,
                registry.find(TradingSignal.StrategyType.S9_PULLBACK_SWING).orElseThrow().type());
        assertEquals(TradingSignal.StrategyType.S13_BOX_BREAKOUT,
                registry.find(TradingSignal.StrategyType.S13_BOX_BREAKOUT).orElseThrow().type());
        assertEquals(TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE,
                registry.find(TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE).orElseThrow().type());
        assertEquals(TradingSignal.StrategyType.S15_MOMENTUM_ALIGN,
                registry.find(TradingSignal.StrategyType.S15_MOMENTUM_ALIGN).orElseThrow().type());
        assertTrue(registry.supports(TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW));
    }
}
