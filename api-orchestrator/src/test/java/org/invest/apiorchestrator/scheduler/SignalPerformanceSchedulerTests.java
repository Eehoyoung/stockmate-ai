package org.invest.apiorchestrator.scheduler;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.DailyAggregationService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SignalPerformanceSchedulerTests {

    @Test
    void monitorsActivePaperPositionAcrossTradingDays() {
        TradingSignalRepository repository = mock(TradingSignalRepository.class);
        RedisMarketDataService redis = mock(RedisMarketDataService.class);
        TradingSignal signal = TradingSignal.builder()
                .stkCd("373220")
                .strategy(TradingSignal.StrategyType.S15_MOMENTUM_ALIGN)
                .signalStatus(TradingSignal.SignalStatus.SENT)
                .positionStatus("ACTIVE")
                .monitorEnabled(true)
                .entryPrice(372000.0)
                .targetPrice(422000.0)
                .stopPrice(350500.0)
                .build();
        when(repository.findMonitorablePaperPositions()).thenReturn(List.of(signal));
        when(redis.getTickData("373220")).thenReturn(Optional.of(Map.of("cur_prc", "373000")));

        new SignalPerformanceScheduler(repository, redis, mock(DailyAggregationService.class)).updatePerformance();

        verify(repository).findMonitorablePaperPositions();
        assertEquals(0, signal.getPeakPrice().compareTo(BigDecimal.valueOf(373000)));
    }

    @Test
    void sentPaperSignalClosesOnTrailingStopWithoutExecutionFields() {
        RedisMarketDataService redis = mock(RedisMarketDataService.class);
        when(redis.getTickData("020120")).thenReturn(Optional.of(Map.of("cur_prc", "105")));
        SignalPerformanceScheduler scheduler = new SignalPerformanceScheduler(
                mock(TradingSignalRepository.class), redis, mock(DailyAggregationService.class));
        TradingSignal signal = TradingSignal.builder()
                .stkCd("020120")
                .strategy(TradingSignal.StrategyType.S11_FRGN_CONT)
                .signalStatus(TradingSignal.SignalStatus.SENT)
                .entryPrice(100.0)
                .targetPrice(120.0)
                .stopPrice(95.0)
                .peakPrice(BigDecimal.valueOf(110))
                .trailingActivation(BigDecimal.valueOf(105))
                .trailingPct(BigDecimal.valueOf(5))
                .build();

        assertTrue(scheduler.evaluateSignal(signal));
        assertEquals("TRAILING_STOP", signal.getExitType());
        assertEquals(TradingSignal.SignalStatus.WIN, signal.getSignalStatus());
        assertEquals(0, signal.getTrailingStopPrice().compareTo(BigDecimal.valueOf(105)));
    }
}
