package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.DailyAggregationService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class SignalPerformanceScheduler {

    private final TradingSignalRepository signalRepository;
    private final RedisMarketDataService redisService;
    private final DailyAggregationService dailyAggregationService;

    @Scheduled(cron = "0 * 9-15 * * MON-FRI", zone = "Asia/Seoul")
    @Transactional
    public void updatePerformance() {
        List<TradingSignal> sentSignals =
                signalRepository.findMonitorablePaperPositions();

        if (sentSignals.isEmpty()) {
            return;
        }

        int wins = 0;
        int losses = 0;
        int skipped = 0;
        for (TradingSignal signal : sentSignals) {
            try {
                boolean updated = evaluateSignal(signal);
                if (updated) {
                    if (signal.getSignalStatus() == TradingSignal.SignalStatus.WIN) {
                        wins++;
                    } else {
                        losses++;
                    }
                } else {
                    skipped++;
                }
            } catch (Exception e) {
                log.debug("[Performance] evaluation error [{}]: {}", signal.getStkCd(), e.getMessage());
            }
        }

        if (wins + losses > 0) {
            log.info("[Performance] updated WIN={} LOSS={} skipped={}", wins, losses, skipped);
        }
    }

    @Scheduled(cron = "0 36 15 * * MON-FRI", zone = "Asia/Seoul")
    @Transactional
    public void expireSentSignals() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        List<TradingSignal> sentSignals =
                signalRepository.findNonActiveSignalsByStatusAfter(
                        TradingSignal.SignalStatus.SENT, startOfDay);

        int expired = 0;
        for (TradingSignal signal : sentSignals) {
            signal.updateStatus(TradingSignal.SignalStatus.EXPIRED);
            expired++;
        }

        if (expired > 0) {
            log.info("[Performance] expired SENT signals count={}", expired);
        }
    }

    @Scheduled(cron = "0 45 15 * * MON-FRI", zone = "Asia/Seoul")
    @Transactional
    public void aggregateDailyStats() {
        LocalDate today = KstClock.today();
        log.info("[DailyAgg] aggregation start date={}", today);

        try {
            DailyAggregationService.DailyAggregation aggregation = dailyAggregationService.aggregateAndPersist(today);
            if (aggregation.totalSignals() == 0 && aggregation.closedCount() == 0) {
                log.info("[DailyAgg] no signals or outcomes for date={}", today);
                return;
            }

            log.info("[DailyAgg] aggregation complete date={} totalSignals={} closed={}",
                    today, aggregation.totalSignals(), aggregation.closedCount());
        } catch (Exception e) {
            log.error("[DailyAgg] aggregation failed date={}: {}", today, e.getMessage(), e);
        }
    }

    boolean evaluateSignal(TradingSignal signal) {
        if (signal.getEntryPrice() == null || signal.getEntryPrice() <= 0) {
            return false;
        }

        Map<Object, Object> tick = redisService.getTickData(signal.getStkCd()).orElse(null);
        if (tick == null) {
            return false;
        }

        String curPrcStr = (String) tick.get("cur_prc");
        if (curPrcStr == null || curPrcStr.isBlank()) {
            return false;
        }

        double curPrc;
        try {
            curPrc = Double.parseDouble(curPrcStr.replace(",", "").replace("+", "").replace("-", "").trim());
            curPrc = Math.abs(curPrc);
        } catch (NumberFormatException e) {
            return false;
        }

        if (curPrc <= 0) {
            return false;
        }

        double entryPrice = signal.getEntryPrice();
        double pnlPct = (curPrc - entryPrice) / entryPrice * 100.0;
        double targetPct = signal.getTargetPct() != null ? signal.getTargetPct() : 3.5;
        double stopPct = signal.getStopPct() != null ? signal.getStopPct() : -2.0;
        double targetPrice = signal.getTargetPrice() != null && signal.getTargetPrice() > 0
                ? signal.getTargetPrice() : entryPrice * (1.0 + targetPct / 100.0);
        double stopPrice = signal.getStopPrice() != null && signal.getStopPrice() > 0
                ? signal.getStopPrice() : entryPrice * (1.0 + stopPct / 100.0);

        if (curPrc >= targetPrice) {
            signal.closePaperSignal("TP_HIT", BigDecimal.valueOf(curPrc), pnlPct);
            log.info("[Performance] WIN [{} {}] entry={} cur={} pnl={}",
                    signal.getStkCd(), signal.getStrategy(), entryPrice, curPrc, pnlPct);
            return true;
        }
        if (curPrc <= stopPrice) {
            signal.closePaperSignal("SL_HIT", BigDecimal.valueOf(curPrc), pnlPct);
            log.info("[Performance] LOSS [{} {}] entry={} cur={} pnl={}",
                    signal.getStkCd(), signal.getStrategy(), entryPrice, curPrc, pnlPct);
            return true;
        }

        BigDecimal current = BigDecimal.valueOf(curPrc);
        BigDecimal peak = signal.getPeakPrice();
        if (peak == null || current.compareTo(peak) > 0) {
            peak = current;
        }
        BigDecimal trailingPct = signal.getTrailingPct();
        BigDecimal activation = signal.getTrailingActivation();
        if (trailingPct != null && trailingPct.signum() > 0
                && activation != null && activation.signum() > 0
                && peak.compareTo(activation) >= 0) {
            BigDecimal trailingStop = peak.multiply(
                    BigDecimal.ONE.subtract(trailingPct.movePointLeft(2)))
                    .setScale(0, RoundingMode.HALF_UP);
            signal.updatePaperPeak(peak, trailingStop);
            if (current.compareTo(trailingStop) <= 0) {
                signal.closePaperSignal("TRAILING_STOP", current, pnlPct);
                log.info("[Performance] TRAILING_STOP [{} {}] entry={} peak={} stop={} cur={} pnl={}",
                        signal.getStkCd(), signal.getStrategy(), entryPrice, peak, trailingStop, curPrc, pnlPct);
                return true;
            }
        } else {
            signal.updatePaperPeak(peak, signal.getTrailingStopPrice());
        }

        return false;
    }
}
