package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.DailyPnl;
import org.invest.apiorchestrator.domain.StrategyDailyStat;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.DailyPnlRepository;
import org.invest.apiorchestrator.repository.StrategyDailyStatRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Feature 1 – 신호 성과 추적 스케쥴러.
 *
 * 장중 10분마다 SENT 상태 신호를 조회하고 현재가를 기반으로 가상 P&L 계산.
 * 목표가/손절가 도달 시 WIN/LOSS 상태로 업데이트.
 * 장마감 후 15:35에 잔여 SENT 신호를 EXPIRED 처리.
 * 15:45에 DailyPnl + StrategyDailyStat 집계 저장.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SignalPerformanceScheduler {

    private final TradingSignalRepository signalRepository;
    private final RedisMarketDataService redisService;
    private final DailyPnlRepository dailyPnlRepository;
    private final StrategyDailyStatRepository strategyDailyStatRepository;
    private final StringRedisTemplate redis;

    /**
     * 장중 10분마다 가상 P&L 계산 및 WIN/LOSS 판정
     * 09:00 ~ 15:30, 월~금
     */
    @Scheduled(cron = "0 0/10 9-15 * * MON-FRI")
    @Transactional
    public void updatePerformance() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        List<TradingSignal> sentSignals =
                signalRepository.findBySignalStatusAndCreatedAtAfter(
                        TradingSignal.SignalStatus.SENT, startOfDay);

        if (sentSignals.isEmpty()) return;

        int wins = 0, losses = 0, skipped = 0;
        for (TradingSignal signal : sentSignals) {
            try {
                boolean updated = evaluateSignal(signal);
                if (updated) {
                    if (signal.getSignalStatus() == TradingSignal.SignalStatus.WIN) wins++;
                    else losses++;
                } else {
                    skipped++;
                }
            } catch (Exception e) {
                log.debug("[Performance] 평가 오류 [{}]: {}", signal.getStkCd(), e.getMessage());
            }
        }

        if (wins + losses > 0) {
            log.info("[Performance] 성과 업데이트 WIN={} LOSS={} 미결={}", wins, losses, skipped);
        }
    }

    /**
     * 장마감 후 잔여 SENT 신호 EXPIRED 처리 (15:35 월~금)
     */
    @Scheduled(cron = "0 35 15 * * MON-FRI")
    @Transactional
    public void expireSentSignals() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        List<TradingSignal> sentSignals =
                signalRepository.findBySignalStatusAndCreatedAtAfter(
                        TradingSignal.SignalStatus.SENT, startOfDay);

        int expired = 0;
        for (TradingSignal signal : sentSignals) {
            signal.updateStatus(TradingSignal.SignalStatus.EXPIRED);
            expired++;
        }

        if (expired > 0) {
            log.info("[Performance] 장마감 EXPIRED 처리 {}건", expired);
        }
    }

    /**
     * 15:45 – DailyPnl + StrategyDailyStat 집계 후 DB 저장 (UPSERT 패턴)
     */
    @Scheduled(cron = "0 45 15 * * MON-FRI")
    @Transactional
    public void aggregateDailyStats() {
        log.info("=== 일별 성과 집계 시작 (15:45) ===");
        LocalDate today = LocalDate.now();
        LocalDateTime startOfDay = LocalDateTime.of(today, LocalTime.MIDNIGHT);

        try {
            List<TradingSignal> allSignals = signalRepository.findTodaySignals(startOfDay);
            if (allSignals.isEmpty()) {
                log.info("[DailyAgg] 당일 신호 없음 – 집계 건너뜀");
                return;
            }

            saveDailyPnl(today, allSignals);
            saveStrategyDailyStats(today, allSignals);

            log.info("[DailyAgg] 집계 완료 – 총 {}건 신호", allSignals.size());
        } catch (Exception e) {
            log.error("[DailyAgg] 집계 실패: {}", e.getMessage());
        }
    }

    // ──── 내부 집계 ────────────────────────────────────────────────

    private void saveDailyPnl(LocalDate today, List<TradingSignal> signals) {
        int totalSignals  = signals.size();
        int enterCount    = (int) signals.stream().filter(s -> "ENTER".equals(s.getAction())).count();
        int cancelCount   = (int) signals.stream().filter(s -> "CANCEL".equals(s.getAction())).count();
        int closedCount   = (int) signals.stream()
                .filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.WIN
                          || s.getSignalStatus() == TradingSignal.SignalStatus.LOSS).count();
        int tpHitCount    = (int) signals.stream().filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.WIN).count();
        int slHitCount    = (int) signals.stream().filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.LOSS).count();
        int forceCloseCount = (int) signals.stream().filter(s -> "FORCE_CLOSE".equals(s.getExitType())).count();

        BigDecimal winRate = closedCount > 0
                ? BigDecimal.valueOf((double) tpHitCount / closedCount * 100).setScale(2, RoundingMode.HALF_UP)
                : null;

        // P&L 집계 (exitPnlPct 또는 realizedPnl 사용)
        double grossPnlPctSum = 0.0;
        BigDecimal grossPnlAbsSum = BigDecimal.ZERO;
        int pnlCount = 0;
        for (TradingSignal s : signals) {
            if (s.getExitPnlPct() != null) {
                grossPnlPctSum += s.getExitPnlPct().doubleValue();
                pnlCount++;
            } else if (s.getRealizedPnl() != null) {
                grossPnlPctSum += s.getRealizedPnl();
                pnlCount++;
            }
            if (s.getExitPnlAbs() != null) {
                grossPnlAbsSum = grossPnlAbsSum.add(s.getExitPnlAbs());
            }
        }
        BigDecimal avgPnlPct = pnlCount > 0
                ? BigDecimal.valueOf(grossPnlPctSum / pnlCount).setScale(4, RoundingMode.HALF_UP)
                : null;
        BigDecimal grossPnlAbs = grossPnlAbsSum.compareTo(BigDecimal.ZERO) != 0 ? grossPnlAbsSum : null;

        // 시장 심리 (Redis)
        String marketSentiment = redis.opsForValue().get("news:market_sentiment");

        DailyPnl pnl = dailyPnlRepository.findByDate(today)
                .map(existing -> existing)
                .orElse(null);

        if (pnl == null) {
            pnl = DailyPnl.builder()
                    .date(today)
                    .totalSignals(totalSignals)
                    .enterCount(enterCount)
                    .cancelCount(cancelCount)
                    .closedCount(closedCount)
                    .tpHitCount(tpHitCount)
                    .slHitCount(slHitCount)
                    .forceCloseCount(forceCloseCount)
                    .winRate(winRate)
                    .grossPnlAbs(grossPnlAbs)
                    .netPnlAbs(grossPnlAbs)
                    .grossPnlPct(avgPnlPct)
                    .netPnlPct(avgPnlPct)
                    .avgPnlPerTrade(avgPnlPct)
                    .marketSentiment(marketSentiment != null ? marketSentiment : "NEUTRAL")
                    .build();
        } else {
            // 기존 행이 있으면 필드 업데이트 (Hibernate dirty-check)
            // DailyPnl은 @Builder이므로 새 객체를 저장 (id 포함)
            pnl = DailyPnl.builder()
                    .id(pnl.getId())
                    .date(today)
                    .totalSignals(totalSignals)
                    .enterCount(enterCount)
                    .cancelCount(cancelCount)
                    .closedCount(closedCount)
                    .tpHitCount(tpHitCount)
                    .slHitCount(slHitCount)
                    .forceCloseCount(forceCloseCount)
                    .winRate(winRate)
                    .grossPnlAbs(grossPnlAbs)
                    .netPnlAbs(grossPnlAbs)
                    .grossPnlPct(avgPnlPct)
                    .netPnlPct(avgPnlPct)
                    .avgPnlPerTrade(avgPnlPct)
                    .marketSentiment(marketSentiment != null ? marketSentiment : "NEUTRAL")
                    .build();
        }
        dailyPnlRepository.save(pnl);
        log.info("[DailyAgg] DailyPnl 저장 완료 – date={} total={} wins={} losses={} avgPnl={}",
                today, totalSignals, tpHitCount, slHitCount, avgPnlPct);
    }

    private void saveStrategyDailyStats(LocalDate today, List<TradingSignal> signals) {
        Map<TradingSignal.StrategyType, List<TradingSignal>> byStrategy =
                signals.stream().collect(Collectors.groupingBy(TradingSignal::getStrategy));

        for (Map.Entry<TradingSignal.StrategyType, List<TradingSignal>> entry : byStrategy.entrySet()) {
            String strategyName = entry.getKey().name();
            List<TradingSignal> stratSignals = entry.getValue();

            int total       = stratSignals.size();
            int enters      = (int) stratSignals.stream().filter(s -> "ENTER".equals(s.getAction())).count();
            int cancels     = (int) stratSignals.stream().filter(s -> "CANCEL".equals(s.getAction())).count();
            int wins        = (int) stratSignals.stream().filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.WIN).count();
            int losses      = (int) stratSignals.stream().filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.LOSS).count();
            int expired     = (int) stratSignals.stream().filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.EXPIRED).count();
            int forceClosed = (int) stratSignals.stream().filter(s -> "FORCE_CLOSE".equals(s.getExitType())).count();
            int overnight   = (int) stratSignals.stream().filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.OVERNIGHT_HOLD).count();

            int closed = wins + losses;
            BigDecimal winRate = closed > 0
                    ? BigDecimal.valueOf((double) wins / closed * 100).setScale(2, RoundingMode.HALF_UP)
                    : null;

            // 스코어 평균
            double ruleScoreSum = stratSignals.stream()
                    .filter(s -> s.getRuleScore() != null)
                    .mapToDouble(s -> s.getRuleScore().doubleValue()).sum();
            long ruleScoreCnt = stratSignals.stream().filter(s -> s.getRuleScore() != null).count();
            BigDecimal avgRuleScore = ruleScoreCnt > 0
                    ? BigDecimal.valueOf(ruleScoreSum / ruleScoreCnt).setScale(2, RoundingMode.HALF_UP)
                    : null;

            double aiScoreSum = stratSignals.stream()
                    .filter(s -> s.getAiScore() != null)
                    .mapToDouble(s -> s.getAiScore().doubleValue()).sum();
            long aiScoreCnt = stratSignals.stream().filter(s -> s.getAiScore() != null).count();
            BigDecimal avgAiScore = aiScoreCnt > 0
                    ? BigDecimal.valueOf(aiScoreSum / aiScoreCnt).setScale(2, RoundingMode.HALF_UP)
                    : null;

            // 성과 통계
            double pnlSum = 0.0;
            BigDecimal pnlAbsSum = BigDecimal.ZERO;
            double bestPnl = Double.MIN_VALUE;
            double worstPnl = Double.MAX_VALUE;
            int pnlCnt = 0;
            for (TradingSignal s : stratSignals) {
                double pnl = 0.0;
                if (s.getExitPnlPct() != null) pnl = s.getExitPnlPct().doubleValue();
                else if (s.getRealizedPnl() != null) pnl = s.getRealizedPnl();
                else continue;
                pnlSum += pnl;
                if (pnl > bestPnl) bestPnl = pnl;
                if (pnl < worstPnl) worstPnl = pnl;
                pnlCnt++;
                if (s.getExitPnlAbs() != null) pnlAbsSum = pnlAbsSum.add(s.getExitPnlAbs());
            }
            // lambda에서 참조하려면 effectively final 이어야 하므로 final 복사본 준비
            final BigDecimal fAvgPnlPct = pnlCnt > 0
                    ? BigDecimal.valueOf(pnlSum / pnlCnt).setScale(4, RoundingMode.HALF_UP)
                    : null;
            final BigDecimal fPnlAbsSum = pnlAbsSum;
            final BigDecimal fBestPnl   = pnlCnt > 0
                    ? BigDecimal.valueOf(bestPnl).setScale(4, RoundingMode.HALF_UP) : null;
            final BigDecimal fWorstPnl  = pnlCnt > 0
                    ? BigDecimal.valueOf(worstPnl).setScale(4, RoundingMode.HALF_UP) : null;

            StrategyDailyStat stat = strategyDailyStatRepository
                    .findByDateAndStrategy(today, strategyName)
                    .map(existing -> StrategyDailyStat.builder()
                            .id(existing.getId())
                            .date(today).strategy(strategyName)
                            .totalSignals(total).enterCount(enters).cancelCount(cancels)
                            .tp1HitCount(wins).slHitCount(losses).forceCloseCount(forceClosed)
                            .expiredCount(expired).overnightCount(overnight)
                            .winRate(winRate).avgRuleScore(avgRuleScore).avgAiScore(avgAiScore)
                            .avgPnlPct(fAvgPnlPct)
                            .totalPnlAbs(fPnlAbsSum.compareTo(BigDecimal.ZERO) != 0 ? fPnlAbsSum : null)
                            .bestPnlPct(fBestPnl).worstPnlPct(fWorstPnl)
                            .build())
                    .orElse(StrategyDailyStat.builder()
                            .date(today).strategy(strategyName)
                            .totalSignals(total).enterCount(enters).cancelCount(cancels)
                            .tp1HitCount(wins).slHitCount(losses).forceCloseCount(forceClosed)
                            .expiredCount(expired).overnightCount(overnight)
                            .winRate(winRate).avgRuleScore(avgRuleScore).avgAiScore(avgAiScore)
                            .avgPnlPct(fAvgPnlPct)
                            .totalPnlAbs(fPnlAbsSum.compareTo(BigDecimal.ZERO) != 0 ? fPnlAbsSum : null)
                            .bestPnlPct(fBestPnl).worstPnlPct(fWorstPnl)
                            .build());
            strategyDailyStatRepository.save(stat);
        }
        log.info("[DailyAgg] StrategyDailyStat 저장 완료 – {}개 전략", byStrategy.size());
    }

    /**
     * 단일 신호 평가 – 현재가 기반 가상 P&L 계산
     * @return true = WIN/LOSS 판정 완료, false = 현재가 없음 또는 미결
     */
    private boolean evaluateSignal(TradingSignal signal) {
        if (signal.getEntryPrice() == null || signal.getEntryPrice() <= 0) return false;

        Map<Object, Object> tick = redisService.getTickData(signal.getStkCd()).orElse(null);
        if (tick == null) return false;

        String curPrcStr = (String) tick.get("cur_prc");
        if (curPrcStr == null || curPrcStr.isBlank()) return false;

        double curPrc;
        try {
            curPrc = Double.parseDouble(curPrcStr.replace(",", "").replace("+", "").replace("-", "").trim());
            if (curPrcStr.startsWith("-")) curPrc = -curPrc;
            curPrc = Math.abs(curPrc); // Kiwoom sometimes sends signed prices
        } catch (NumberFormatException e) {
            return false;
        }

        if (curPrc <= 0) return false;

        double entryPrice = signal.getEntryPrice();
        double pnlPct = (curPrc - entryPrice) / entryPrice * 100.0;

        // 목표/손절 기준 (DTO targetPct/stopPct 또는 기본값)
        double targetPct = signal.getTargetPct() != null ? signal.getTargetPct() : 3.5;
        double stopPct   = signal.getStopPct()   != null ? signal.getStopPct()   : -2.0;

        if (pnlPct >= targetPct) {
            signal.closeSignal(pnlPct);
            log.info("[Performance] WIN [{} {}] entry={} cur={} pnl=+{:.2f}%",
                    signal.getStkCd(), signal.getStrategy(), entryPrice, curPrc, pnlPct);
            return true;
        } else if (pnlPct <= stopPct) {
            signal.closeSignal(pnlPct);
            log.info("[Performance] LOSS [{} {}] entry={} cur={} pnl={:.2f}%",
                    signal.getStkCd(), signal.getStrategy(), entryPrice, curPrc, pnlPct);
            return true;
        }

        return false;
    }
}
