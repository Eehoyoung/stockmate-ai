package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class S7AuctionScannerTests {

    @Test
    void exposesDeprecatedEmptyScannerContract() {
        S7AuctionScanner scanner = new S7AuctionScanner();

        assertEquals(TradingSignal.StrategyType.S7_ICHIMOKU_BREAKOUT, scanner.type());
        assertTrue(scanner.scan(StrategyScanContext.market("101", Set.of("005930"))).isEmpty());
    }
}
