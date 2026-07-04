package org.invest.apiorchestrator.service.strategy;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;

@Slf4j
@Component
public class S7AuctionScanner implements StrategyScanner {

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S7_ICHIMOKU_BREAKOUT;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        log.warn("[S7] legacy auction scanner requested for market={} preFiltered={} returning empty list",
                context.market(), context.preFiltered().size());
        return Collections.emptyList();
    }
}
