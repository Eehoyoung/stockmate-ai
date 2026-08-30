package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import org.invest.apiorchestrator.domain.DailyPnl;
import org.invest.apiorchestrator.domain.MarketDailyContext;
import org.invest.apiorchestrator.domain.StrategyDailyStat;
import org.invest.apiorchestrator.domain.TradeOutcome;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.DailyPnlRepository;
import org.invest.apiorchestrator.repository.MarketDailyContextRepository;
import org.invest.apiorchestrator.repository.StrategyDailyStatRepository;
import org.invest.apiorchestrator.repository.TradeOutcomeRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.util.TradingDayWindow;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class DailyAggregationService {

    private final TradingSignalRepository signalRepository;
    private final TradeOutcomeRepository tradeOutcomeRepository;
    private final DailyPnlRepository dailyPnlRepository;
    private final StrategyDailyStatRepository strategyDailyStatRepository;
    private final MarketDailyContextRepository marketDailyContextRepository;
    private final StrategyParamSnapshotService strategyParamSnapshotService;
    private final StringRedisTemplate redis;

    @Transactional
    public DailyAggregation aggregateAndPersist(LocalDate date) {
        DailyAggregation aggregation = aggregate(date);
        if (aggregation.totalSignals() == 0 && aggregation.closedCount() == 0) {
            return aggregation;
        }
        saveDailyPnl(aggregation);
        saveStrategyDailyStats(aggregation);
        return aggregation;
    }

    @Transactional(readOnly = true)
    public DailyAggregation aggregate(LocalDate date) {
        TradingDayWindow window = TradingDayWindow.of(date);
        List<TradingSignal> daySignals = signalRepository.findSignalsCreatedBetween(window.start(), window.end());
        List<TradeOutcome> dayOutcomes =
                tradeOutcomeRepository.findByExitTsGreaterThanEqualAndExitTsLessThanOrderByExitTsAsc(
                        window.offsetStart(), window.offsetEnd());

        Map<Long, TradingSignal> signalsById = new LinkedHashMap<>();
        daySignals.stream()
                .filter(signal -> signal.getId() != null)
                .forEach(signal -> signalsById.put(signal.getId(), signal));

        List<Long> missingSignalIds = dayOutcomes.stream()
                .map(TradeOutcome::getSignalId)
                .filter(Objects::nonNull)
                .filter(signalId -> !signalsById.containsKey(signalId))
                .distinct()
                .toList();
        if (!missingSignalIds.isEmpty()) {
            signalRepository.findAllById(missingSignalIds)
                    .forEach(signal -> signalsById.put(signal.getId(), signal));
        }

        List<OutcomeFact> outcomeFacts = dayOutcomes.stream()
                .map(outcome -> new OutcomeFact(outcome, signalsById.get(outcome.getSignalId())))
                .toList();

        return DailyAggregation.from(date, daySignals, outcomeFacts);
    }

    private void saveDailyPnl(DailyAggregation aggregation) {
        MarketDailyContext marketCtx = marketDailyContextRepository.findByDate(aggregation.date()).orElse(null);
        String marketSentiment = redis.opsForValue().get("news:market_sentiment");
        DailyPnl existing = dailyPnlRepository.findByDate(aggregation.date()).orElse(null);

        DailyPnl pnl = DailyPnl.builder()
                .id(existing != null ? existing.getId() : null)
                .date(aggregation.date())
                .totalSignals(aggregation.totalSignals())
                .enterCount(aggregation.enterCount())
                .cancelCount(aggregation.cancelCount())
                .decisionEnterCount(aggregation.decisionEnterCount())
                .watchCount(aggregation.watchCount())
                .signalExpiredCount(aggregation.signalExpiredCount())
                .closedCount(aggregation.closedCount())
                .tpHitCount(aggregation.tpHitCount())
                .slHitCount(aggregation.slHitCount())
                .forceCloseCount(aggregation.forceCloseCount())
                .winRate(aggregation.winRate())
                .grossPnlAbs(aggregation.totalPnlAbs())
                .netPnlAbs(aggregation.totalPnlAbs())
                .grossPnlPct(aggregation.avgPnlPct())
                .netPnlPct(aggregation.avgPnlPct())
                .avgPnlPerTrade(aggregation.avgPnlPct())
                .kospiChangePct(marketCtx != null ? marketCtx.getKospiChangePct() : null)
                .kosdaqChangePct(marketCtx != null ? marketCtx.getKosdaqChangePct() : null)
                .marketSentiment(marketSentiment != null ? marketSentiment : "NEUTRAL")
                .build();
        dailyPnlRepository.save(pnl);
    }

    private void saveStrategyDailyStats(DailyAggregation aggregation) {
        for (StrategyAggregation stat : aggregation.byStrategy().values()) {
            Double threshold = strategyParamSnapshotService.getClaudeThreshold(stat.strategy());
            StrategyDailyStat existing = strategyDailyStatRepository
                    .findByDateAndStrategy(aggregation.date(), stat.strategy())
                    .orElse(null);

            StrategyDailyStat entity = StrategyDailyStat.builder()
                    .id(existing != null ? existing.getId() : null)
                    .date(aggregation.date())
                    .strategy(stat.strategy())
                    .totalSignals(stat.totalSignals())
                    .enterCount(stat.enterCount())
                    .cancelCount(stat.cancelCount())
                    .skipEntryCount(stat.skipEntryCount())
                    .decisionEnterCount(stat.decisionEnterCount())
                    .watchCount(stat.watchCount())
                    .signalExpiredCount(stat.signalExpiredCount())
                    .tp1HitCount(stat.tpHitCount())
                    .tp2HitCount(stat.tp2HitCount())
                    .slHitCount(stat.slHitCount())
                    .forceCloseCount(stat.forceCloseCount())
                    .expiredCount(stat.expiredCount())
                    .overnightCount(stat.overnightCount())
                    .winRate(stat.winRate())
                    .avgRuleScore(stat.avgRuleScore())
                    .avgAiScore(stat.avgAiScore())
                    .avgRrRatio(stat.avgRrRatio())
                    .pctAboveThreshold(stat.pctAboveThreshold(threshold))
                    .avgPnlPct(stat.avgPnlPct())
                    .avgHoldMin(stat.avgHoldMin())
                    .totalPnlAbs(stat.totalPnlAbs())
                    .bestPnlPct(stat.bestPnlPct())
                    .worstPnlPct(stat.worstPnlPct())
                    .thresholdSnapshot(BigDecimal.valueOf(threshold).setScale(2, RoundingMode.HALF_UP))
                    .build();
            strategyDailyStatRepository.save(entity);
        }
    }

    public record DailyAggregation(
            LocalDate date,
            int totalSignals,
            int enterCount,
            int cancelCount,
            int decisionEnterCount,
            int watchCount,
            int signalExpiredCount,
            int closedCount,
            int tpHitCount,
            int slHitCount,
            int forceCloseCount,
            BigDecimal winRate,
            BigDecimal avgPnlPct,
            BigDecimal totalPnlAbs,
            Map<String, StrategyAggregation> byStrategy
    ) {

        private static DailyAggregation from(LocalDate date, List<TradingSignal> signals, List<OutcomeFact> outcomes) {
            Map<String, StrategyAggregation> byStrategy = new LinkedHashMap<>();
            signals.stream()
                    .filter(signal -> signal.getStrategy() != null)
                    .collect(Collectors.groupingBy(signal -> signal.getStrategy().name(), LinkedHashMap::new, Collectors.toList()))
                    .forEach((strategy, strategySignals) -> byStrategy.put(strategy, StrategyAggregation.from(strategy, strategySignals, List.of())));

            outcomes.stream()
                    .map(OutcomeFact::signal)
                    .filter(Objects::nonNull)
                    .map(TradingSignal::getStrategy)
                    .filter(Objects::nonNull)
                    .map(Enum::name)
                    .distinct()
                    .filter(strategy -> !byStrategy.containsKey(strategy))
                    .forEach(strategy -> byStrategy.put(strategy, StrategyAggregation.from(strategy, List.of(), List.of())));

            Map<String, List<OutcomeFact>> outcomesByStrategy = outcomes.stream()
                    .filter(fact -> fact.signal() != null && fact.signal().getStrategy() != null)
                    .collect(Collectors.groupingBy(fact -> fact.signal().getStrategy().name(), LinkedHashMap::new, Collectors.toList()));
            outcomesByStrategy.forEach((strategy, strategyOutcomes) -> {
                StrategyAggregation current = byStrategy.get(strategy);
                byStrategy.put(strategy, StrategyAggregation.from(
                        strategy,
                        current != null ? current.signals() : List.of(),
                        strategyOutcomes));
            });

            return new DailyAggregation(
                    date,
                    signals.size(),
                    (int) signals.stream().filter(DailyAggregationService::isExecutedSignal).count(),
                    (int) signals.stream().filter(signal -> "CANCEL".equals(signal.getAction())).count(),
                    (int) signals.stream().filter(DailyAggregationService::isEnterDecision).count(),
                    (int) signals.stream().filter(DailyAggregationService::isWatchDecision).count(),
                    (int) signals.stream().filter(DailyAggregationService::isSignalExpired).count(),
                    outcomes.size(),
                    (int) outcomes.stream().filter(OutcomeFact::isTpHit).count(),
                    (int) outcomes.stream().filter(OutcomeFact::isSlHit).count(),
                    (int) outcomes.stream().filter(OutcomeFact::isForceClose).count(),
                    DailyAggregationService.winRate(outcomes),
                    avgOutcomePnlPct(outcomes),
                    totalOutcomePnlAbs(outcomes),
                    byStrategy
            );
        }
    }

    public record StrategyAggregation(
            String strategy,
            List<TradingSignal> signals,
            List<OutcomeFact> outcomes
    ) {

        private static StrategyAggregation from(String strategy, List<TradingSignal> signals, List<OutcomeFact> outcomes) {
            return new StrategyAggregation(strategy, signals, outcomes);
        }

        int totalSignals() {
            return signals.size();
        }

        int enterCount() {
            return (int) signals.stream().filter(DailyAggregationService::isExecutedSignal).count();
        }

        int decisionEnterCount() {
            return (int) signals.stream().filter(DailyAggregationService::isEnterDecision).count();
        }

        int watchCount() {
            return (int) signals.stream().filter(DailyAggregationService::isWatchDecision).count();
        }

        int signalExpiredCount() {
            return (int) signals.stream().filter(DailyAggregationService::isSignalExpired).count();
        }

        int cancelCount() {
            return (int) signals.stream().filter(signal -> "CANCEL".equals(signal.getAction())).count();
        }

        int skipEntryCount() {
            return (int) signals.stream().filter(signal -> Boolean.TRUE.equals(signal.getSkipEntry())).count();
        }

        int tpHitCount() {
            return (int) outcomes.stream().filter(OutcomeFact::isTpHit).count();
        }

        int tp2HitCount() {
            return (int) outcomes.stream().filter(OutcomeFact::isTp2Hit).count();
        }

        int slHitCount() {
            return (int) outcomes.stream().filter(OutcomeFact::isSlHit).count();
        }

        int forceCloseCount() {
            return (int) outcomes.stream().filter(OutcomeFact::isForceClose).count();
        }

        int expiredCount() {
            return signalExpiredCount();
        }

        int overnightCount() {
            return (int) signals.stream()
                    .filter(signal -> signal.getSignalStatus() == TradingSignal.SignalStatus.OVERNIGHT_HOLD)
                    .count();
        }

        BigDecimal winRate() {
            return DailyAggregationService.winRate(outcomes);
        }

        BigDecimal avgRuleScore() {
            return avg(signals.stream().map(TradingSignal::getRuleScore).toList(), 2);
        }

        BigDecimal avgAiScore() {
            return avg(signals.stream().map(TradingSignal::getAiScore).toList(), 2);
        }

        BigDecimal avgRrRatio() {
            return avg(signals.stream().map(TradingSignal::getRrRatio).toList(), 2);
        }

        BigDecimal pctAboveThreshold(Double threshold) {
            if (signals.isEmpty()) {
                return null;
            }
            long count = signals.stream()
                    .map(signal -> signal.getAiScore() != null ? signal.getAiScore() : signal.getRuleScore())
                    .filter(Objects::nonNull)
                    .filter(score -> score.doubleValue() >= threshold)
                    .count();
            return BigDecimal.valueOf((double) count / signals.size() * 100).setScale(2, RoundingMode.HALF_UP);
        }

        BigDecimal avgPnlPct() {
            return avgOutcomePnlPct(outcomes);
        }

        BigDecimal avgHoldMin() {
            return avg(signals.stream()
                    .map(TradingSignal::getHoldDurationMin)
                    .filter(Objects::nonNull)
                    .map(BigDecimal::valueOf)
                    .toList(), 1);
        }

        BigDecimal totalPnlAbs() {
            return totalOutcomePnlAbs(outcomes);
        }

        BigDecimal bestPnlPct() {
            return pnlPctValues(outcomes).stream().max(Comparator.naturalOrder()).orElse(null);
        }

        BigDecimal worstPnlPct() {
            return pnlPctValues(outcomes).stream().min(Comparator.naturalOrder()).orElse(null);
        }
    }

    public record OutcomeFact(TradeOutcome outcome, TradingSignal signal) {

        boolean isTpHit() {
            return startsWith("TP");
        }

        boolean isTp2Hit() {
            return "TP2_HIT".equals(outcome.getExitReason());
        }

        boolean isSlHit() {
            return "SL_HIT".equals(outcome.getExitReason());
        }

        boolean isForceClose() {
            return "FORCE_CLOSE".equals(outcome.getExitReason());
        }

        boolean isExpired() {
            return "EXPIRED".equals(outcome.getExitReason());
        }

        private boolean startsWith(String prefix) {
            return outcome.getExitReason() != null && outcome.getExitReason().startsWith(prefix);
        }
    }

    private static BigDecimal winRate(Collection<OutcomeFact> outcomes) {
        long wins = outcomes.stream().filter(OutcomeFact::isTpHit).count();
        long losses = outcomes.stream().filter(fact -> fact.isSlHit() || fact.isForceClose()).count();
        long closed = wins + losses;
        return closed > 0
                ? BigDecimal.valueOf((double) wins / closed * 100).setScale(2, RoundingMode.HALF_UP)
                : null;
    }

    private static boolean isExecutedSignal(TradingSignal signal) {
        return signal.getExecutedAt() != null
                && signal.getEntryQty() != null
                && signal.getEntryQty() > 0;
    }

    private static boolean isEnterDecision(TradingSignal signal) {
        return "ENTER".equals(signal.getExecutionDecision());
    }

    private static boolean isWatchDecision(TradingSignal signal) {
        return "WATCH".equals(signal.getExecutionDecision());
    }

    private static boolean isSignalExpired(TradingSignal signal) {
        return signal.getSignalStatus() == TradingSignal.SignalStatus.EXPIRED;
    }

    private static BigDecimal avgOutcomePnlPct(Collection<OutcomeFact> outcomes) {
        return avg(pnlPctValues(outcomes), 4);
    }

    private static List<BigDecimal> pnlPctValues(Collection<OutcomeFact> outcomes) {
        return outcomes.stream()
                .map(OutcomeFact::signal)
                .filter(Objects::nonNull)
                .map(signal -> {
                    if (signal.getExitPnlPct() != null) {
                        return signal.getExitPnlPct();
                    }
                    return signal.getRealizedPnl() != null ? BigDecimal.valueOf(signal.getRealizedPnl()) : null;
                })
                .filter(Objects::nonNull)
                .map(value -> value.setScale(4, RoundingMode.HALF_UP))
                .toList();
    }

    private static BigDecimal totalOutcomePnlAbs(Collection<OutcomeFact> outcomes) {
        BigDecimal total = outcomes.stream()
                .map(OutcomeFact::outcome)
                .map(TradeOutcome::getRealizedPnl)
                .filter(Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        return total.compareTo(BigDecimal.ZERO) == 0 ? null : total.setScale(0, RoundingMode.HALF_UP);
    }

    private static BigDecimal avg(Collection<BigDecimal> values, int scale) {
        List<BigDecimal> present = values.stream().filter(Objects::nonNull).toList();
        if (present.isEmpty()) {
            return null;
        }
        BigDecimal sum = present.stream().reduce(BigDecimal.ZERO, BigDecimal::add);
        return sum.divide(BigDecimal.valueOf(present.size()), scale, RoundingMode.HALF_UP);
    }
}
