package org.invest.apiorchestrator.service;

import org.invest.apiorchestrator.domain.TradeOutcome;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.DailyPnlRepository;
import org.invest.apiorchestrator.repository.MarketDailyContextRepository;
import org.invest.apiorchestrator.repository.StrategyDailyStatRepository;
import org.invest.apiorchestrator.repository.TradeOutcomeRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.util.KstClock;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyIterable;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DailyAggregationServiceTests {

    @Mock TradingSignalRepository signalRepository;
    @Mock TradeOutcomeRepository tradeOutcomeRepository;
    @Mock DailyPnlRepository dailyPnlRepository;
    @Mock StrategyDailyStatRepository strategyDailyStatRepository;
    @Mock MarketDailyContextRepository marketDailyContextRepository;
    @Mock StrategyParamSnapshotService strategyParamSnapshotService;
    @Mock StringRedisTemplate redis;

    @Test
    void aggregateUsesOneKstDateWindowForSignalsAndOutcomes() {
        LocalDate date = LocalDate.of(2026, 5, 22);
        TradingSignal signal = TradingSignal.builder()
                .id(1L)
                .strategy(TradingSignal.StrategyType.S8_GOLDEN_CROSS)
                .action("ENTER")
                .executedAt(LocalDateTime.of(date, LocalTime.of(9, 30)))
                .entryQty(10)
                .ruleScore(BigDecimal.valueOf(80))
                .exitPnlPct(BigDecimal.valueOf(1.2500))
                .build();
        TradeOutcome outcome = TradeOutcome.builder()
                .signalId(1L)
                .exitReason("TP1_HIT")
                .exitTs(LocalDateTime.of(date, LocalTime.of(15, 0)).atZone(KstClock.ZONE_ID).toOffsetDateTime())
                .realizedPnl(BigDecimal.valueOf(12500))
                .build();

        when(signalRepository.findSignalsCreatedBetween(
                LocalDateTime.of(date, LocalTime.MIDNIGHT),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT)))
                .thenReturn(List.of(signal));
        when(tradeOutcomeRepository.findByExitTsGreaterThanEqualAndExitTsLessThanOrderByExitTsAsc(
                LocalDateTime.of(date, LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime(),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime()))
                .thenReturn(List.of(outcome));

        DailyAggregationService service = service();
        DailyAggregationService.DailyAggregation aggregation = service.aggregate(date);

        assertEquals(1, aggregation.totalSignals());
        assertEquals(1, aggregation.enterCount());
        assertEquals(1, aggregation.closedCount());
        assertEquals(1, aggregation.tpHitCount());
        assertEquals(BigDecimal.valueOf(100.00).setScale(2), aggregation.winRate());
        assertEquals(BigDecimal.valueOf(1.2500).setScale(4), aggregation.avgPnlPct());
        assertEquals(BigDecimal.valueOf(12500).setScale(0), aggregation.totalPnlAbs());
        assertEquals(1, aggregation.byStrategy().get("S8_GOLDEN_CROSS").signals().size());
    }

    @Test
    void aggregateDoesNotCountEnterRecommendationWithoutExecutionEvidence() {
        LocalDate date = LocalDate.of(2026, 8, 3);
        TradingSignal unexecuted = TradingSignal.builder()
                .id(1L)
                .strategy(TradingSignal.StrategyType.S11_FRGN_CONT)
                .action("ENTER")
                .executionDecision("ENTER")
                .signalStatus(TradingSignal.SignalStatus.EXPIRED)
                .build();

        when(signalRepository.findSignalsCreatedBetween(
                LocalDateTime.of(date, LocalTime.MIDNIGHT),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT)))
                .thenReturn(List.of(unexecuted));
        when(tradeOutcomeRepository.findByExitTsGreaterThanEqualAndExitTsLessThanOrderByExitTsAsc(
                LocalDateTime.of(date, LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime(),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime()))
                .thenReturn(List.of());

        DailyAggregationService.DailyAggregation aggregation = service().aggregate(date);

        assertEquals(1, aggregation.totalSignals());
        assertEquals(0, aggregation.enterCount());
        assertEquals(1, aggregation.decisionEnterCount());
        assertEquals(1, aggregation.signalExpiredCount());
        assertEquals(0, aggregation.byStrategy().get("S11_FRGN_CONT").enterCount());
        assertEquals(1, aggregation.byStrategy().get("S11_FRGN_CONT").decisionEnterCount());
        assertEquals(1, aggregation.byStrategy().get("S11_FRGN_CONT").expiredCount());
    }

    @Test
    void aggregateDoesNotCountWatchAsCancel() {
        LocalDate date = LocalDate.of(2026, 8, 24);
        TradingSignal watch = TradingSignal.builder()
                .id(2L)
                .strategy(TradingSignal.StrategyType.S9_PULLBACK_SWING)
                .action("HOLD")
                .executionDecision("WATCH")
                .signalStatus(TradingSignal.SignalStatus.WATCHING)
                .build();

        when(signalRepository.findSignalsCreatedBetween(
                LocalDateTime.of(date, LocalTime.MIDNIGHT),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT)))
                .thenReturn(List.of(watch));
        when(tradeOutcomeRepository.findByExitTsGreaterThanEqualAndExitTsLessThanOrderByExitTsAsc(
                LocalDateTime.of(date, LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime(),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime()))
                .thenReturn(List.of());

        DailyAggregationService.DailyAggregation aggregation = service().aggregate(date);

        assertEquals(1, aggregation.watchCount());
        assertEquals(0, aggregation.cancelCount());
    }

    @Test
    void aggregateLoadsOutcomeSignalsClosedOnDateEvenWhenSignalWasCreatedEarlier() {
        LocalDate date = LocalDate.of(2026, 5, 22);
        TradingSignal priorSignal = TradingSignal.builder()
                .id(10L)
                .strategy(TradingSignal.StrategyType.S1_GAP_OPEN)
                .exitPnlPct(BigDecimal.valueOf(-0.7500))
                .build();
        TradeOutcome outcome = TradeOutcome.builder()
                .signalId(10L)
                .exitReason("SL_HIT")
                .realizedPnl(BigDecimal.valueOf(-7500))
                .build();

        when(signalRepository.findSignalsCreatedBetween(
                LocalDateTime.of(date, LocalTime.MIDNIGHT),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT)))
                .thenReturn(List.of());
        when(tradeOutcomeRepository.findByExitTsGreaterThanEqualAndExitTsLessThanOrderByExitTsAsc(
                LocalDateTime.of(date, LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime(),
                LocalDateTime.of(date.plusDays(1), LocalTime.MIDNIGHT).atZone(KstClock.ZONE_ID).toOffsetDateTime()))
                .thenReturn(List.of(outcome));
        when(signalRepository.findAllById(anyIterable())).thenReturn(List.of(priorSignal));

        DailyAggregationService.DailyAggregation aggregation = service().aggregate(date);

        ArgumentCaptor<Iterable<Long>> idsCaptor = ArgumentCaptor.forClass(Iterable.class);
        verify(signalRepository).findAllById(idsCaptor.capture());
        assertEquals(List.of(10L), idsCaptor.getValue());
        assertEquals(0, aggregation.totalSignals());
        assertEquals(1, aggregation.closedCount());
        assertEquals(1, aggregation.slHitCount());
        assertEquals(BigDecimal.valueOf(-0.7500).setScale(4), aggregation.avgPnlPct());
        assertEquals(BigDecimal.valueOf(-7500).setScale(0), aggregation.totalPnlAbs());
        assertEquals(0, aggregation.byStrategy().get("S1_GAP_OPEN").signals().size());
    }

    private DailyAggregationService service() {
        return new DailyAggregationService(
                signalRepository,
                tradeOutcomeRepository,
                dailyPnlRepository,
                strategyDailyStatRepository,
                marketDailyContextRepository,
                strategyParamSnapshotService,
                redis
        );
    }
}
