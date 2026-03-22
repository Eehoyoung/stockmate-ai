package org.invest.apiorchestrator.controller;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.EconomicEvent;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.*;
import org.invest.apiorchestrator.websocket.WebSocketSubscriptionManager;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/trading")
@RequiredArgsConstructor
public class TradingController {

    private final StrategyService strategyService;
    private final SignalService signalService;
    private final CandidateService candidateService;
    private final TokenService tokenService;
    private final WebSocketSubscriptionManager subscriptionManager;
    private final EconomicCalendarService calendarService;
    private final NewsControlService newsControlService;
    private final RedisMarketDataService redisMarketDataService;
    private final TradingSignalRepository signalRepository;
    private final StringRedisTemplate redis;

    /** 토큰 수동 갱신 */
    @PostMapping("/token/refresh")
    public ResponseEntity<Map<String, String>> refreshToken() {
        try {
            tokenService.refreshToken();
            return ResponseEntity.ok(Map.of("status", "ok", "msg", "토큰 갱신 완료"));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(Map.of("status", "error", "msg", e.getMessage()));
        }
    }

    /** 당일 전체 신호 조회 */
    @GetMapping("/signals/today")
    public ResponseEntity<List<TradingSignal>> getTodaySignals() {
        return ResponseEntity.ok(signalService.getTodaySignals());
    }

    /** 전략별 통계 조회 */
    @GetMapping("/signals/stats")
    public ResponseEntity<List<Object[]>> getStats() {
        return ResponseEntity.ok(signalService.getTodayStats());
    }

    /** 전술 1 수동 실행 (갭상승 시초가) */
    @PostMapping("/strategy/s1/run")
    public ResponseEntity<Map<String, Object>> runS1(
            @RequestParam(defaultValue = "000") String market) {
        List<String> candidates = candidateService.getCandidates(market);
        List<TradingSignalDto> signals = strategyService.scanGapOpening(candidates);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S1_GAP_OPEN",
                "signals", signals, "published", cnt));
    }

    /** 전술 3 수동 실행 (외인+기관) */
    @PostMapping("/strategy/s3/run")
    public ResponseEntity<Map<String, Object>> runS3(
            @RequestParam(defaultValue = "001") String market) {
        List<TradingSignalDto> signals = strategyService.scanInstFrgn(market);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S3_INST_FRGN",
                "signals", signals, "published", cnt));
    }

    /** 전술 5 수동 실행 (프로그램+외인) */
    @PostMapping("/strategy/s5/run")
    public ResponseEntity<Map<String, Object>> runS5(
            @RequestParam(defaultValue = "P00101") String market) {
        List<TradingSignalDto> signals = strategyService.scanProgramFrgn(market);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S5_PROG_FRGN",
                "signals", signals, "published", cnt));
    }

    /** 전술 6 수동 실행 (테마 후발주) */
    @PostMapping("/strategy/s6/run")
    public ResponseEntity<Map<String, Object>> runS6() {
        List<TradingSignalDto> signals = strategyService.scanThemeLaggard();
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S6_THEME_LAGGARD",
                "signals", signals, "published", cnt));
    }

    /** 전술 7 수동 실행 (동시호가) */
    @PostMapping("/strategy/s7/run")
    public ResponseEntity<Map<String, Object>> runS7(
            @RequestParam(defaultValue = "000") String market) {
        List<TradingSignalDto> signals = strategyService.scanAuction(market);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S7_AUCTION",
                "signals", signals, "published", cnt));
    }

    /** WebSocket 수동 연결/구독 */
    @PostMapping("/ws/connect")
    public ResponseEntity<Map<String, String>> connectWs() {
        subscriptionManager.setupMarketHoursSubscription();
        return ResponseEntity.ok(Map.of("status", "ok", "msg", "WebSocket 연결 및 구독 완료"));
    }

    /** WebSocket 구독 해제 */
    @PostMapping("/ws/disconnect")
    public ResponseEntity<Map<String, String>> disconnectWs() {
        subscriptionManager.teardownSubscriptions();
        return ResponseEntity.ok(Map.of("status", "ok", "msg", "구독 해제 완료"));
    }

    /** 후보 종목 조회 */
    @GetMapping("/candidates")
    public ResponseEntity<Map<String, Object>> getCandidates(
            @RequestParam(defaultValue = "000") String market) {
        List<String> candidates = candidateService.getCandidates(market);
        return ResponseEntity.ok(Map.of("market", market,
                "count", candidates.size(), "codes", candidates));
    }

    /** 헬스체크 */
    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of("status", "UP", "service", "kiwoom-trading"));
    }

    // ──────────────────────────────────────────────────────────────
    // Feature 1 – 신호 성과 추적
    // ──────────────────────────────────────────────────────────────

    /** 오늘 신호 + 가상 P&L 목록 */
    @GetMapping("/signals/performance")
    public ResponseEntity<List<TradingSignal>> getSignalPerformance() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        List<TradingSignal> signals = signalRepository.findTodaySignals(startOfDay);
        return ResponseEntity.ok(signals);
    }

    /** 전략별 가상 성과 요약 */
    @GetMapping("/signals/performance/summary")
    public ResponseEntity<List<Object[]>> getPerformanceSummary() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        return ResponseEntity.ok(signalRepository.getStrategyPerformanceStats(startOfDay));
    }

    // ──────────────────────────────────────────────────────────────
    // Feature 2 – 경제 캘린더
    // ──────────────────────────────────────────────────────────────

    /** 이번 주 경제 이벤트 */
    @GetMapping("/calendar/week")
    public ResponseEntity<List<EconomicEvent>> getWeekCalendar() {
        return ResponseEntity.ok(calendarService.getThisWeekEvents());
    }

    /** 오늘 경제 이벤트 */
    @GetMapping("/calendar/today")
    public ResponseEntity<List<EconomicEvent>> getTodayCalendar() {
        return ResponseEntity.ok(calendarService.getTodayEvents());
    }

    /** 경제 이벤트 등록 */
    @PostMapping("/calendar/event")
    public ResponseEntity<EconomicEvent> addCalendarEvent(@RequestBody Map<String, Object> body) {
        EconomicEvent event = EconomicEvent.builder()
                .eventName((String) body.get("event_name"))
                .eventType(EconomicEvent.EventType.valueOf(
                        String.valueOf(body.getOrDefault("event_type", "CUSTOM")).toUpperCase()))
                .eventDate(LocalDate.parse((String) body.get("event_date")))
                .eventTime(body.containsKey("event_time") && body.get("event_time") != null
                        ? java.time.LocalTime.parse((String) body.get("event_time")) : null)
                .expectedImpact(EconomicEvent.ImpactLevel.valueOf(
                        String.valueOf(body.getOrDefault("expected_impact", "MEDIUM")).toUpperCase()))
                .description((String) body.getOrDefault("description", ""))
                .build();
        return ResponseEntity.ok(calendarService.addEvent(event));
    }

    // ──────────────────────────────────────────────────────────────
    // Feature 3 – 종목별 신호 이력
    // ──────────────────────────────────────────────────────────────

    /** 종목별 최근 N일 신호 이력 */
    @GetMapping("/signals/stock/{stkCd}")
    public ResponseEntity<List<TradingSignal>> getSignalHistory(
            @PathVariable String stkCd,
            @RequestParam(defaultValue = "7") int days) {
        LocalDateTime since = LocalDateTime.now().minusDays(days);
        List<TradingSignal> history =
                signalRepository.findByStkCdAndCreatedAtAfterOrderByCreatedAtDesc(stkCd, since);
        return ResponseEntity.ok(history);
    }

    /** 전략별 성과 상세 (Feature 3 – /전략분석) */
    @GetMapping("/signals/strategy-analysis")
    public ResponseEntity<List<Object[]>> getStrategyAnalysis() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        return ResponseEntity.ok(signalRepository.getStrategyPerformanceStats(startOfDay));
    }

    // ──────────────────────────────────────────────────────────────
    // Feature 5 – 시스템 모니터링
    // ──────────────────────────────────────────────────────────────

    /** 시스템 종합 헬스 정보 */
    @GetMapping("/monitor/health")
    public ResponseEntity<Map<String, Object>> getMonitorHealth() {
        long queueDepth    = redisMarketDataService.getTelegramQueueDepth();
        long errorCount    = redisMarketDataService.getErrorQueueDepth();
        long dailySignals  = redisMarketDataService.getDailySignalCount();
        String preEvent    = redis.opsForValue().get("calendar:pre_event");
        String tradingCtrl = newsControlService.getTradingControl().name();
        String wsReconnect = redis.opsForValue().get("monitor:ws_reconnect_count");

        return ResponseEntity.ok(Map.of(
                "status",             "UP",
                "trading_control",    tradingCtrl,
                "calendar_pre_event", "true".equals(preEvent),
                "telegram_queue",     queueDepth,
                "error_queue",        errorCount,
                "daily_signals",      dailySignals,
                "ws_reconnect_today", wsReconnect != null ? Long.parseLong(wsReconnect) : 0L
        ));
    }
}
