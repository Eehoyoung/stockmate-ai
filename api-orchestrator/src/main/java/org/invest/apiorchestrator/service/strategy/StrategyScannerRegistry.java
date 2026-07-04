package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.springframework.stereotype.Component;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Component
public class StrategyScannerRegistry {

    private final Map<TradingSignal.StrategyType, StrategyScanner> scanners;

    public StrategyScannerRegistry(List<StrategyScanner> scanners) {
        Map<TradingSignal.StrategyType, StrategyScanner> mapped =
                new EnumMap<>(TradingSignal.StrategyType.class);
        for (StrategyScanner scanner : scanners) {
            StrategyScanner previous = mapped.put(scanner.type(), scanner);
            if (previous != null) {
                throw new IllegalStateException("Duplicate strategy scanner: " + scanner.type());
            }
        }
        this.scanners = Map.copyOf(mapped);
    }

    public Optional<StrategyScanner> find(TradingSignal.StrategyType type) {
        return Optional.ofNullable(scanners.get(type));
    }

    public boolean supports(TradingSignal.StrategyType type) {
        return scanners.containsKey(type);
    }
}

