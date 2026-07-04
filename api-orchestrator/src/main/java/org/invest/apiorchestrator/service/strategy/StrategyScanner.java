package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;

import java.util.List;

public interface StrategyScanner {

    TradingSignal.StrategyType type();

    List<TradingSignalDto> scan(StrategyScanContext context);
}

