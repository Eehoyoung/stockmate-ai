package org.invest.apiorchestrator.controller;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.EconomicEvent;
import org.invest.apiorchestrator.domain.StrategyParamHistory;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StrategyParamHistoryRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.*;
import org.invest.apiorchestrator.service.OvernightScoringService;
import org.invest.apiorchestrator.util.KstClock;
import org.invest.apiorchestrator.util.TradingDayWindow;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Slf4j
@RestController
@RequestMapping("/api/trading")
@RequiredArgsConstructor
public class TradingController {

    private final StrategyService strategyService;
    private final SignalService signalService;
    private final CandidateService candidateService;
    private final TokenService tokenService;
    private final EconomicCalendarService calendarService;
    private final NewsControlService newsControlService;
    private final RedisMarketDataService redisMarketDataService;
    private final OvernightScoringService overnightScoringService;
    private final TradingSignalRepository signalRepository;
    private final StringRedisTemplate redis;
    private final StrategyParamHistoryRepository strategyParamHistoryRepository;
    private final JdbcTemplate jdbcTemplate;
    private final OperationsHealthService operationsHealthService;
    private final StrategyExecutionOwnership strategyExecutionOwnership;
    private final WebClient internalWebClient;

    @Value("${services.ai-engine.url}")
    private String aiEngineUrl;

    // S1~S7/S10/S12는 이 컨트롤러 자체에 /run 엔드포인트가 있다. 그 외 나머지는 Python
    // ai-engine에만 구현되어 있어 서버사이드로 프록시한다 (runPythonOwnedStrategy 참고).
    private static final Set<String> PYTHON_ONLY_STRATEGY_CODES =
            Set.of("s8", "s9", "s11", "s13", "s14", "s15", "s16");

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
        var blocked = requireJavaStrategyOwner("S1_GAP_OPEN");
        if (blocked != null) return blocked;
        List<String> candidates = java.util.stream.Stream.concat(
                        candidateService.getS1Candidates("001").stream(),
                        candidateService.getS1Candidates("101").stream())
                .distinct().limit(50).collect(java.util.stream.Collectors.toList());
        List<TradingSignalDto> signals = strategyService.scanGapOpening(candidates);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S1_GAP_OPEN",
                "signals", signals, "published", cnt));
    }

    /** 전술 2 수동 실행 (VI 눌림목) – 해당 없음: 이벤트 기반 전술이므로 안내 메시지 반환 */
    @PostMapping("/strategy/s2/run")
    public ResponseEntity<Map<String, Object>> runS2() {
        return ResponseEntity.ok(Map.of(
                "strategy", "S2_VI_PULLBACK",
                "published", 0,
                "msg", "S2는 VI 이벤트 기반 전술입니다. vi_watch_queue 를 통해 자동 실행됩니다."));
    }

    /** 전술 3 수동 실행 (외인+기관) */
    @PostMapping("/strategy/s3/run")
    public ResponseEntity<Map<String, Object>> runS3(
            @RequestParam(defaultValue = "001") String market) {
        var blocked = requireJavaStrategyOwner("S3_INST_FRGN");
        if (blocked != null) return blocked;
        List<TradingSignalDto> signals = strategyService.scanInstFrgn(market);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S3_INST_FRGN",
                "signals", signals, "published", cnt));
    }

    /** 전술 4 수동 실행 (장대양봉) */
    @PostMapping("/strategy/s4/run")
    public ResponseEntity<Map<String, Object>> runS4(
            @RequestParam(defaultValue = "000") String market) {
        var blocked = requireJavaStrategyOwner("S4_BIG_CANDLE");
        if (blocked != null) return blocked;
        List<String> candidates = java.util.stream.Stream.concat(
                        candidateService.getS12Candidates("001").stream(),
                        candidateService.getS12Candidates("101").stream())
                .distinct().limit(30).collect(java.util.stream.Collectors.toList());
        int cnt = 0;
        for (String stkCd : candidates) {
            var sigOpt = strategyService.checkBigCandle(stkCd);
            if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                cnt++;
                if (cnt >= 5) break;
            }
        }
        return ResponseEntity.ok(Map.of("strategy", "S4_BIG_CANDLE", "published", cnt));
    }

    /** 전술 5 수동 실행 (프로그램+외인) */
    @PostMapping("/strategy/s5/run")
    public ResponseEntity<Map<String, Object>> runS5(
            @RequestParam(defaultValue = "001") String market) {
        var blocked = requireJavaStrategyOwner("S5_PROG_FRGN");
        if (blocked != null) return blocked;
        List<TradingSignalDto> signals = strategyService.scanProgramFrgn(market);
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S5_PROG_FRGN",
                "signals", signals, "published", cnt));
    }

    /** 전술 6 수동 실행 (테마 후발주) */
    @PostMapping("/strategy/s6/run")
    public ResponseEntity<Map<String, Object>> runS6() {
        var blocked = requireJavaStrategyOwner("S6_THEME_LAGGARD");
        if (blocked != null) return blocked;
        List<TradingSignalDto> signals = strategyService.scanThemeLaggard();
        int cnt = signalService.processSignals(signals);
        return ResponseEntity.ok(Map.of("strategy", "S6_THEME_LAGGARD",
                "signals", signals, "published", cnt));
    }

    /** 전략 7 수동 실행 (일목균형표 스윙) */
    @PostMapping("/strategy/s7/run")
    public ResponseEntity<Map<String, Object>> runS7(
            @RequestParam(defaultValue = "000") String market) {
        return ResponseEntity.ok(Map.of(
                "strategy", "S7_ICHIMOKU_BREAKOUT",
                "published", 0,
                "msg", "S7은 Python ai-engine에서 장중 자동 실행됩니다. 수동 실행은 현재 비활성화되어 있습니다."
        ));
    }

    /** 전술 10 수동 실행 (52주 신고가 돌파) */
    @PostMapping("/strategy/s10/run")
    public ResponseEntity<Map<String, Object>> runS10() {
        var blocked = requireJavaStrategyOwner("S10_NEW_HIGH");
        if (blocked != null) return blocked;
        List<String> s10pool = java.util.stream.Stream.concat(
                        candidateService.getS10Candidates("001").stream(),
                        candidateService.getS10Candidates("101").stream())
                .distinct().collect(java.util.stream.Collectors.toList());
        List<String> candidates = !s10pool.isEmpty() ? s10pool.stream().limit(30).collect(java.util.stream.Collectors.toList())
                : java.util.stream.Stream.concat(
                        candidateService.getS8Candidates("001").stream(),
                        candidateService.getS8Candidates("101").stream())
                  .distinct().limit(30).collect(java.util.stream.Collectors.toList());
        int cnt = 0;
        for (String stkCd : candidates) {
            var sigOpt = strategyService.checkNewHigh(stkCd);
            if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                cnt++;
                if (cnt >= 5) break;
            }
        }
        return ResponseEntity.ok(Map.of("strategy", "S10_NEW_HIGH", "published", cnt));
    }

    /** 전술 12 수동 실행 (종가 강도 매수) */
    @PostMapping("/strategy/s12/run")
    public ResponseEntity<Map<String, Object>> runS12() {
        var blocked = requireJavaStrategyOwner("S12_CLOSING");
        if (blocked != null) return blocked;
        List<String> candidates = java.util.stream.Stream.concat(
                        candidateService.getS12Candidates("001").stream(),
                        candidateService.getS12Candidates("101").stream())
                .distinct().collect(java.util.stream.Collectors.toList());
        int cnt = 0;
        for (String stkCd : candidates) {
            var sigOpt = strategyService.checkClosingStrength(stkCd);
            if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                cnt++;
                if (cnt >= 5) break;
            }
        }
        return ResponseEntity.ok(Map.of("strategy", "S12_CLOSING", "published", cnt));
    }

    /**
     * S8/S9/S11/S13~S16 수동 실행 — 이 전략들은 Java에 자체 구현이 없고 Python
     * ai-engine(strategy_runner.py)에만 존재하므로, 대시보드 버튼 요청을 그대로 프록시한다.
     * S1~S7/S10/S12는 위의 전용 엔드포인트가 우선 매칭되므로 이 핸들러까지 오지 않는다.
     */
    @PostMapping("/strategy/{code}/run")
    public ResponseEntity<Map<String, Object>> runPythonOwnedStrategy(@PathVariable String code) {
        String lower = code.trim().toLowerCase();
        if (!PYTHON_ONLY_STRATEGY_CODES.contains(lower)) {
            return ResponseEntity.badRequest().body(Map.of(
                    "status", "error", "msg", "지원하지 않는 전략 코드: " + code));
        }
        try {
            Map<String, Object> body = internalWebClient.post()
                    .uri(aiEngineUrl + "/strategy/" + lower + "/run")
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            return ResponseEntity.ok(body != null ? body : Map.of());
        } catch (Exception e) {
            log.warn("[Strategy] {} 수동 실행 프록시 실패: {}", lower, e.getMessage());
            return ResponseEntity.internalServerError()
                    .body(Map.of("status", "error", "msg", "ai-engine 호출 실패: " + e.getMessage()));
        }
    }

    private ResponseEntity<Map<String, Object>> requireJavaStrategyOwner(String strategy) {
        if (strategyExecutionOwnership.javaOwnsEvaluation()) {
            return null;
        }
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of(
                "status", "blocked",
                "strategy", strategy,
                "owner", strategyExecutionOwnership.owner().name(),
                "published", 0,
                "msg", "Strategy evaluation/publish is owned by Python; Java endpoint is candidate/API only"
        ));
    }

    /** WebSocket 상태 조회 (Python websocket-listener 단독 운영) */
    @PostMapping("/ws/connect")
    public ResponseEntity<Map<String, String>> connectWs() {
        return ResponseEntity.ok(Map.of("status", "ok", "msg", "Python websocket-listener 단독 운영 중"));
    }

    /** WebSocket 구독 시작 (telegram-bot /ws시작 연동) */
    @PostMapping("/ws/start")
    public ResponseEntity<Map<String, String>> startWs() {
        return ResponseEntity.ok(Map.of("status", "ok", "msg", "Python websocket-listener 단독 운영 중"));
    }

    /** WebSocket 구독 해제 */
    @PostMapping("/ws/disconnect")
    public ResponseEntity<Map<String, String>> disconnectWs() {
        return ResponseEntity.ok(Map.of("status", "ok", "msg", "Python websocket-listener 단독 운영 중"));
    }

    /** WebSocket 구독 종료 (telegram-bot /ws종료 연동) */
    @PostMapping("/ws/stop")
    public ResponseEntity<Map<String, String>> stopWs() {
        return ResponseEntity.ok(Map.of("status", "ok", "msg", "Python websocket-listener 단독 운영 중"));
    }

    /** 후보 종목 조회 (전략 태그 포함) */
    @GetMapping("/candidates")
    public ResponseEntity<Map<String, Object>> getCandidates(
            @RequestParam(defaultValue = "000") String market) {
        List<Map<String, Object>> withTags = candidateService.getCandidatesWithTags(market);
        List<String> codes = withTags.stream()
                .map(m -> (String) m.get("code"))
                .toList();
        return ResponseEntity.ok(Map.of(
                "market", market,
                "count", codes.size(),
                "codes", codes,
                "candidates", withTags));
    }

    /** 헬스체크 */
    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return ResponseEntity.ok(operationsHealthService.buildHealthSnapshot());
    }

    /**
     * 매매 제어 수동 전환 (CONTINUE / CAUTIOUS / PAUSE)
     * 텔레그램 /매매중단, /매매재개 명령에서 호출
     */
    @PostMapping("/control/{mode}")
    public ResponseEntity<Map<String, String>> setTradingControl(@PathVariable String mode) {
        String upperMode = mode.trim().toUpperCase();
        if (!upperMode.equals("CONTINUE") && !upperMode.equals("CAUTIOUS") && !upperMode.equals("PAUSE")) {
            return ResponseEntity.badRequest()
                    .body(Map.of("status", "error", "msg", "유효하지 않은 모드: " + mode + " (CONTINUE/CAUTIOUS/PAUSE)"));
        }
        try {
            String prev = redis.opsForValue().get("news:trading_control");
            redis.opsForValue().set("news:trading_control", upperMode);
            // Python news_scheduler 의 prev_control 도 동기화하여 상태 불일치 방지
            redis.opsForValue().set("news:prev_control", upperMode);
            log.info("[Control] 매매 제어 수동 변경: {} → {}", prev, upperMode);

            // NEWS_ALERT 발행으로 변경 사항 텔레그램 전송
            String emoji = switch (upperMode) {
                case "PAUSE"    -> "🚨";
                case "CAUTIOUS" -> "⚠️";
                default         -> "✅";
            };
            String label = switch (upperMode) {
                case "PAUSE"    -> "매매 중단";
                case "CAUTIOUS" -> "신중 매매";
                default         -> "정상 매매";
            };
            String message = String.format("%s [매매 제어 수동 변경]\n%s → <b>%s</b>\n관리자 명령에 의해 변경되었습니다.",
                    emoji, prev != null ? prev : "CONTINUE", label);

            com.fasterxml.jackson.databind.ObjectMapper om = new com.fasterxml.jackson.databind.ObjectMapper();
            String alert = om.writeValueAsString(java.util.Map.of(
                    "type",            "NEWS_ALERT",
                    "trading_control", upperMode,
                    "message",         message
            ));
            log.info("[Control] ai-engine scheduled brief owns user-facing news delivery; NEWS_ALERT push skipped");

            return ResponseEntity.ok(Map.of("status", "ok", "mode", upperMode, "prev", prev != null ? prev : "CONTINUE"));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(Map.of("status", "error", "msg", e.getMessage()));
        }
    }

    // ──────────────────────────────────────────────────────────────
    // Feature 1 – 신호 성과 추적
    // ──────────────────────────────────────────────────────────────

    /** 오늘 신호 + 가상 P&L 목록 */
    @GetMapping("/signals/performance")
    public ResponseEntity<List<TradingSignal>> getSignalPerformance() {
        TradingDayWindow window = TradingDayWindow.of(KstClock.today());
        List<TradingSignal> signals = signalRepository.findSignalsCreatedBetween(window.start(), window.end());
        return ResponseEntity.ok(signals);
    }

    /** 오늘 신호를 신규 G family로 조회. 기존 setup 조회 계약은 그대로 유지한다. */
    @GetMapping("/signals/performance/family/{familyId}")
    public ResponseEntity<?> getSignalPerformanceByFamily(@PathVariable String familyId) {
        String normalized = familyId == null ? "" : familyId.trim().toUpperCase();
        if (!normalized.matches("G0[1-7]")) {
            return ResponseEntity.badRequest().body(Map.of(
                    "status", "error",
                    "msg", "familyId must be G01 through G07"));
        }
        TradingDayWindow window = TradingDayWindow.of(KstClock.today());
        return ResponseEntity.ok(signalRepository.findSignalsByFamilyCreatedBetween(
                normalized, window.start(), window.end()));
    }

    /** 전략별 가상 성과 요약 */
    @GetMapping("/signals/performance/summary")
    public ResponseEntity<List<Object[]>> getPerformanceSummary() {
        TradingDayWindow window = TradingDayWindow.of(KstClock.today());
        return ResponseEntity.ok(signalRepository.getStrategyPerformanceStats(window.start(), window.end()));
    }

    /** 신규 G family별 가상 성과 요약. legacy endpoint의 S별 집계는 변경하지 않는다. */
    @GetMapping("/signals/performance/summary/family")
    public ResponseEntity<List<Object[]>> getFamilyPerformanceSummary() {
        TradingDayWindow window = TradingDayWindow.of(KstClock.today());
        return ResponseEntity.ok(signalRepository.getFamilyPerformanceStats(window.start(), window.end()));
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
        LocalDateTime since = KstClock.now().minusDays(days);
        List<TradingSignal> history =
                signalRepository.findByStkCdAndCreatedAtAfterOrderByCreatedAtDesc(stkCd, since);
        return ResponseEntity.ok(history);
    }

    /** 전략별 성과 상세 (Feature 3 – /전략분석) */
    @GetMapping("/signals/strategy-analysis")
    public ResponseEntity<List<Object[]>> getStrategyAnalysis() {
        TradingDayWindow window = TradingDayWindow.of(KstClock.today());
        return ResponseEntity.ok(signalRepository.getStrategyPerformanceStats(window.start(), window.end()));
    }

    // ──────────────────────────────────────────────────────────────
    // 종목 오버나잇 점수 조회 (개인 종목 수동 확인)
    // ──────────────────────────────────────────────────────────────

    /**
     * GET /api/trading/score/{stkCd}
     * 전략·진입가 없이 실시간 시세만으로 오버나잇 가능성 점수 반환.
     * 텔레그램 /점수 명령어에서 호출.
     */
    @GetMapping("/score/{stkCd}")
    public ResponseEntity<Map<String, Object>> scoreStock(@PathVariable String stkCd) {
        // ws_solver.md 4.3: 조회 시 watchlist에 추가 → Python _watchlist_poller가 30초 내 WS 구독
        redis.opsForSet().add("candidates:watchlist", stkCd);
        redis.expire("candidates:watchlist", java.time.Duration.ofHours(2));
        Map<String, Object> result = overnightScoringService.calcManualScore(stkCd);
        return ResponseEntity.ok(result);
    }

    /** 텔레그램 /score와 동일한 Python 통합 분석을 웹에 제공한다. */
    @GetMapping("/score/full/{stkCd}")
    @SuppressWarnings("unchecked")
    public ResponseEntity<?> scoreStockFull(
            @PathVariable String stkCd,
            @RequestParam(defaultValue = "deep") String mode,
            @RequestParam(defaultValue = "false") boolean refresh) {
        String normalized = stkCd == null ? "" : stkCd.trim();
        if (!normalized.matches("\\d{6}")) {
            return ResponseEntity.badRequest().body(Map.of("error", "6자리 종목코드가 필요합니다."));
        }
        String normalizedMode = mode == null ? "deep" : mode.trim().toLowerCase();
        if (!Set.of("fast", "deep").contains(normalizedMode)) {
            return ResponseEntity.badRequest().body(Map.of("error", "mode는 fast 또는 deep만 가능합니다."));
        }
        try {
            Map<String, Object> result = internalWebClient.get()
                    .uri(aiEngineUrl + "/score/" + normalized
                            + "?ai=" + "deep".equals(normalizedMode)
                            + "&refresh=" + refresh)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block(Duration.ofSeconds(110));
            return ResponseEntity.ok(result == null ? Map.of("error", "분석 결과가 없습니다.") : result);
        } catch (Exception e) {
            log.warn("[ScoreProxy] full score failed stkCd={} mode={}: {}", normalized, normalizedMode, e.getMessage());
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .body(Map.of("error", "AI 통합 분석 연결 실패", "detail", e.getMessage()));
        }
    }

    // ──────────────────────────────────────────────────────────────
    // Feature 5 – 시스템 모니터링
    // ──────────────────────────────────────────────────────────────

    /** 후보 풀 모니터링 – 전략별 candidates:s{N}:{market} 키 크기 반환 */
    @GetMapping("/candidates/pool-status")
    public ResponseEntity<Map<String, Object>> getCandidatePoolStatus() {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        String[] strategies = {"s1","s2","s3","s4","s5","s6","s7","s8","s9","s10","s11","s12","s13","s14","s15","s16"};
        String[] markets    = {"001","101"};
        for (String s : strategies) {
            for (String m : markets) {
                String key = "candidates:" + s + ":" + m;
                Long size  = redis.opsForList().size(key);
                result.put(s + "_" + m, size != null ? size : 0L);
            }
        }
        return ResponseEntity.ok(result);
    }

    // ──────────────────────────────────────────────────────────────
    // Feature D2 – 전략 파라미터 변경 이력 (StrategyParamHistory)
    // ──────────────────────────────────────────────────────────────

    /**
     * GET /api/trading/strategy-params/{strategy}
     * 전략별 파라미터 변경 이력 조회
     */
    @GetMapping("/strategy-params/{strategy}")
    public ResponseEntity<List<StrategyParamHistory>> getStrategyParams(
            @PathVariable String strategy,
            @RequestParam(required = false) String paramName) {
        List<StrategyParamHistory> result = paramName != null && !paramName.isBlank()
                ? strategyParamHistoryRepository.findByStrategyAndParamNameOrderByChangedAtDesc(strategy, paramName)
                : strategyParamHistoryRepository.findByStrategyOrderByChangedAtDesc(strategy);
        return ResponseEntity.ok(result);
    }

    /**
     * POST /api/trading/strategy-params
     * 전략 파라미터 변경 이력 기록
     * body: { "strategy":"S10_NEW_HIGH", "param_name":"threshold", "old_value":"65.0", "new_value":"70.0",
     *         "changed_by":"admin", "reason":"백테스트 결과 반영" }
     */
    @PostMapping("/strategy-params")
    public ResponseEntity<StrategyParamHistory> recordStrategyParam(@RequestBody Map<String, Object> body) {
        StrategyParamHistory record = StrategyParamHistory.builder()
                .strategy(String.valueOf(body.get("strategy")))
                .paramName(String.valueOf(body.get("param_name")))
                .oldValue(body.containsKey("old_value") ? String.valueOf(body.get("old_value")) : null)
                .newValue(String.valueOf(body.get("new_value")))
                .changedBy(body.containsKey("changed_by") ? String.valueOf(body.get("changed_by")) : "API")
                .reason(body.containsKey("reason") ? String.valueOf(body.get("reason")) : null)
                .build();
        return ResponseEntity.ok(strategyParamHistoryRepository.save(record));
    }

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

    @GetMapping("/db/table-status")
    public ResponseEntity<Map<String, Object>> getTableStatus() {
        String[] tables = {
                "candidate_pool_history",
                "daily_indicators",
                "daily_pnl",
                "economic_events",
                "kiwoom_tokens",
                "market_daily_context",
                "news_analysis",
                "open_positions",
                "overnight_evaluations",
                "portfolio_config",
                "risk_events",
                "signal_score_components",
                "stock_master",
                "strategy_daily_stats",
                "strategy_param_history",
                "trading_signals",
                "vi_events",
                "ws_tick_data"
        };
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (String table : tables) {
            Long count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM " + table, Long.class);
            Long bytes = jdbcTemplate.queryForObject("SELECT pg_total_relation_size(?::regclass)", Long.class, table);
            Map<String, Object> entry = new java.util.LinkedHashMap<>();
            entry.put("rows", count != null ? count : 0L);
            entry.put("bytes", bytes != null ? bytes : 0L);
            result.put(table, entry);
        }
        return ResponseEntity.ok(result);
    }
}
