package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StrategyScannerRegistryTests {

    @Test
    void registersScannerByStrategyType() {
        StrategyScanner scanner = new StubScanner(TradingSignal.StrategyType.S1_GAP_OPEN);
        StrategyScannerRegistry registry = new StrategyScannerRegistry(List.of(scanner));

        assertTrue(registry.supports(TradingSignal.StrategyType.S1_GAP_OPEN));
        assertEquals(scanner, registry.find(TradingSignal.StrategyType.S1_GAP_OPEN).orElseThrow());
        assertFalse(registry.supports(TradingSignal.StrategyType.S2_VI_PULLBACK));
    }

    @Test
    void rejectsDuplicateStrategyScanners() {
        StrategyScanner first = new StubScanner(TradingSignal.StrategyType.S1_GAP_OPEN);
        StrategyScanner second = new StubScanner(TradingSignal.StrategyType.S1_GAP_OPEN);

        assertThrows(IllegalStateException.class, () -> new StrategyScannerRegistry(List.of(first, second)));
    }

    private record StubScanner(TradingSignal.StrategyType type) implements StrategyScanner {
        @Override
        public List<TradingSignalDto> scan(StrategyScanContext context) {
            return List.of();
        }
    }
}

