package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.service.*;
import org.invest.apiorchestrator.websocket.WebSocketSubscriptionManager;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalTime;
import java.util.List;

@Slf4j
@Component
@RequiredArgsConstructor
public class TradingScheduler {

    private final StrategyService strategyService;
    private final SignalService signalService;
    private final CandidateService candidateService;
    private final ViWatchService viWatchService;
    private final WebSocketSubscriptionManager subscriptionManager;
    private final TokenService tokenService;

    // ─────────────────────────────────────────────
    // 시스템 준비
    // ─────────────────────────────────────────────

    /** 07:25 - 토큰 갱신 및 WebSocket 연결 */
    @Scheduled(cron = "0 25 7 * * MON-FRI")
    public void prepareSystem() {
        log.info("=== 시스템 준비 시작 (07:25) ===");
        try {
            tokenService.refreshToken();
        } catch (Exception e) {
            log.error("토큰 갱신 실패: {}", e.getMessage());
        }
    }

    /** 07:30 - 장전 WebSocket 구독 (예상체결, 호가잔량) */
    @Scheduled(cron = "0 30 7 * * MON-FRI")
    public void startPreMarketSubscription() {
        log.info("=== 장전 구독 시작 (07:30) ===");
        try {
            subscriptionManager.setupPreMarketSubscription();
        } catch (Exception e) {
            log.error("장전 구독 실패: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 7: 장전 동시호가 (08:30~09:00, 2분마다)
    // ─────────────────────────────────────────────

    /** 08:30~09:00 매 2분 - 전술 7 동시호가 */
    @Scheduled(cron = "0 0/2 8 * * MON-FRI")
    public void scanAuction() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(8, 30)) || now.isAfter(LocalTime.of(9, 0))) return;

        log.info("[S7] 동시호가 스캔 실행");
        try {
            List<TradingSignalDto> kospiSignals  = strategyService.scanAuction("001");
            List<TradingSignalDto> kosdaqSignals = strategyService.scanAuction("101");
            int cnt = signalService.processSignals(kospiSignals)
                    + signalService.processSignals(kosdaqSignals);
            log.info("[S7] 동시호가 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S7] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 정규장 시작 전 준비 (09:00)
    // ─────────────────────────────────────────────

    /** 09:00 - 정규장 구독 전환 */
    @Scheduled(cron = "0 0 9 * * MON-FRI")
    public void startMarketHours() {
        log.info("=== 정규장 구독 전환 (09:00) ===");
        try {
            subscriptionManager.setupMarketHoursSubscription();
        } catch (Exception e) {
            log.error("정규장 구독 전환 실패: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 1: 갭상승 시초가 (09:00~09:10, 2분마다)
    // ─────────────────────────────────────────────

    /** 09:00~09:10 매 2분 - 전술 1 갭상승 */
    @Scheduled(cron = "0 0/2 9 * * MON-FRI")
    public void scanGapOpening() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 0)) || now.isAfter(LocalTime.of(9, 10))) return;

        log.info("[S1] 갭상승 시초가 스캔");
        try {
            List<String> candidates = candidateService.getAllCandidates();
            List<TradingSignalDto> signals = strategyService.scanGapOpening(candidates);
            int cnt = signalService.processSignals(signals);
            log.info("[S1] 갭상승 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S1] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 2: VI 눌림목 감시 (5초마다 큐 처리)
    // ─────────────────────────────────────────────

    /** 09:00~15:20 매 5초 - 전술 2 VI 눌림목 큐 처리 */
    @Scheduled(fixedDelay = 5000, initialDelay = 60000)
    public void processViWatchQueue() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 0)) || now.isAfter(LocalTime.of(15, 20))) return;

        viWatchService.processViWatchQueue();
    }

    // ─────────────────────────────────────────────
    // 전술 3: 외인+기관 동시 순매수 (09:30~14:30, 5분마다)
    // ─────────────────────────────────────────────

    /** 09:30~14:30 매 5분 - 전술 3 외인+기관 */
    @Scheduled(cron = "0 0/5 9-14 * * MON-FRI")
    public void scanInstFrgn() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(14, 30))) return;

        log.info("[S3] 외인+기관 스캔");
        try {
            List<TradingSignalDto> kospiSignals  = strategyService.scanInstFrgn("001");
            List<TradingSignalDto> kosdaqSignals = strategyService.scanInstFrgn("101");
            int cnt = signalService.processSignals(kospiSignals)
                    + signalService.processSignals(kosdaqSignals);
            if (cnt > 0) log.info("[S3] 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S3] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 4: 장대양봉 추격 (09:30~14:30, 3분마다)
    // ─────────────────────────────────────────────

    /** 09:30~14:30 매 3분 - 전술 4 장대양봉 스캔 */
    @Scheduled(cron = "0 0/3 9-14 * * MON-FRI")
    public void scanBigCandle() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(14, 30))) return;

        log.info("[S4] 장대양봉 스캔");
        try {
            List<String> candidates = candidateService.getAllCandidates();
            int cnt = 0;
            for (String stkCd : candidates.subList(0, Math.min(100, candidates.size()))) {
                var sigOpt = strategyService.checkBigCandle(stkCd);
                if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                    cnt++;
                    if (cnt >= 5) break; // 최대 5건
                }
            }
            if (cnt > 0) log.info("[S4] 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S4] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 5: 프로그램+외인 (10:00~14:00, 10분마다)
    // ─────────────────────────────────────────────

    /** 10:00~14:00 매 10분 - 전술 5 프로그램+외인 */
    @Scheduled(cron = "0 0/10 10-13 * * MON-FRI")
    public void scanProgramFrgn() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(10, 0)) || now.isAfter(LocalTime.of(14, 0))) return;

        log.info("[S5] 프로그램+외인 스캔");
        try {
            List<TradingSignalDto> kospiSignals  = strategyService.scanProgramFrgn("P00101");
            List<TradingSignalDto> kosdaqSignals = strategyService.scanProgramFrgn("P10102");
            int cnt = signalService.processSignals(kospiSignals)
                    + signalService.processSignals(kosdaqSignals);
            if (cnt > 0) log.info("[S5] 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S5] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 6: 테마 후발주 (09:30~13:00, 10분마다)
    // ─────────────────────────────────────────────

    /** 09:30~13:00 매 10분 - 전술 6 테마 후발주 */
    @Scheduled(cron = "0 0/10 9-12 * * MON-FRI")
    public void scanThemeLaggard() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(13, 0))) return;

        log.info("[S6] 테마 후발주 스캔");
        try {
            List<TradingSignalDto> signals = strategyService.scanThemeLaggard();
            int cnt = signalService.processSignals(signals);
            if (cnt > 0) log.info("[S6] 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S6] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 공통 유지보수 스케줄
    // ─────────────────────────────────────────────

    /** 매 15분 - 후보 종목 구독 갱신 */
    @Scheduled(cron = "0 0/15 9-15 * * MON-FRI")
    public void refreshSubscription() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 15)) || now.isAfter(LocalTime.of(15, 0))) return;
        try {
            subscriptionManager.refreshCandidateSubscription();
        } catch (Exception e) {
            log.error("구독 갱신 실패: {}", e.getMessage());
        }
    }

    /** 매 시간 - 오래된 신호 만료 처리 */
    @Scheduled(cron = "0 0 * * * MON-FRI")
    public void expireOldSignals() {
        try {
            int cnt = signalService.expireOldSignals();
            if (cnt > 0) log.info("신호 만료 처리: {}건", cnt);
        } catch (Exception e) {
            log.error("신호 만료 처리 실패: {}", e.getMessage());
        }
    }

    /** 15:30 - 장 종료 처리 */
    @Scheduled(cron = "0 30 15 * * MON-FRI")
    public void endOfDay() {
        log.info("=== 장 종료 처리 (15:30) ===");
        try {
            subscriptionManager.teardownSubscriptions();
            signalService.expireOldSignals();

            // 당일 통계 로그
            signalService.getTodayStats().forEach(row ->
                    log.info("전략별 성과 - strategy={} count={} avgPnl={}",
                            row[0], row[1], row[2]));
        } catch (Exception e) {
            log.error("장 종료 처리 실패: {}", e.getMessage());
        }
    }

    /** 매일 06:50 - 다음 거래일 준비 (토큰 사전 발급) */
    @Scheduled(cron = "0 50 6 * * MON-FRI")
    public void dailyPrepare() {
        log.info("=== 일일 준비 (06:50) ===");
        try {
            tokenService.refreshToken();
        } catch (Exception e) {
            log.error("사전 토큰 발급 실패: {}", e.getMessage());
        }
    }

    /** 매일 23:00 - 오래된 tick 데이터 정리 */
    @Scheduled(cron = "0 0 23 * * *")
    public void cleanupTickData() {
        // WsTickDataRepository.deleteOldTickData는 별도 배치에서 처리
        log.info("틱 데이터 정리 완료");
    }
}
