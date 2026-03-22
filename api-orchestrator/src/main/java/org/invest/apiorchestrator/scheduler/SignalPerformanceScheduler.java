package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;

/**
 * Feature 1 – 신호 성과 추적 스케쥴러.
 *
 * 장중 10분마다 SENT 상태 신호를 조회하고 현재가를 기반으로 가상 P&L 계산.
 * 목표가/손절가 도달 시 WIN/LOSS 상태로 업데이트.
 * 장마감 후 15:35에 잔여 SENT 신호를 EXPIRED 처리.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SignalPerformanceScheduler {

    private final TradingSignalRepository signalRepository;
    private final RedisMarketDataService redisService;

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
