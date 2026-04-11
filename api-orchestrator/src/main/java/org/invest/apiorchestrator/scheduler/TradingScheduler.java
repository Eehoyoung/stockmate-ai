package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.MarketDailyContext;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.MarketDailyContextRepository;
import org.invest.apiorchestrator.service.*;
import org.invest.apiorchestrator.service.NewsControlService.TradingControl;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;

/**
 * TradingScheduler – Java 보조 역할 전담
 *
 * 역할 분리 (2026-04-03):
 *   Java: 토큰 관리 · 후보 풀 적재 · 브리핑/리포트
 *   Python: 전략 스캔 S1~S15 (strategy_runner.py) · S2 VI 감시 (vi_watch_worker.py)
 *
 * 후보 풀 키 규약:
 *   candidates:s{N}:{market}  – Python strategy_runner 가 읽음
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TradingScheduler {

    private final SignalService signalService;
    private final CandidateService candidateService;
    private final TokenService tokenService;
    private final KiwoomApiService kiwoomApiService;
    private final RedisMarketDataService redisMarketDataService;
    private final NewsControlService newsControlService;
    private final EconomicCalendarService calendarService;
    private final KiwoomProperties properties;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final MarketDailyContextRepository marketDailyContextRepository;

    private static final ExecutorService PRELOAD_POOL = Executors.newFixedThreadPool(5);

    // ─────────────────────────────────────────────
    // 시스템 준비
    // ─────────────────────────────────────────────

    /** 06:50 - 다음 거래일 준비 (토큰 사전 발급) */
    @Scheduled(cron = "0 50 6 * * MON-FRI")
    public void dailyPrepare() {
        log.info("=== 일일 준비 (06:50) ===");
        try {
            tokenService.refreshToken();
        } catch (Exception e) {
            log.error("사전 토큰 발급 실패: {}", e.getMessage());
        }
    }

    /** 07:25 - 토큰 갱신 */
    @Scheduled(cron = "0 25 7 * * MON-FRI")
    public void prepareSystem() {
        log.info("=== 시스템 준비 시작 (07:25) ===");
        try {
            tokenService.refreshToken();
        } catch (Exception e) {
            log.error("토큰 갱신 실패: {}", e.getMessage());
        }
    }

    /** 07:30 - Python strategy_runner 를 위해 S1·S7 후보 풀 사전 적재 */
    @Scheduled(cron = "0 30 7 * * MON-FRI")
    public void startPreMarketSubscription() {
        log.info("=== 장전 시작 (07:30) – Python websocket-listener 운영 중 ===");
        // S1 (갭상승 08:30~09:10) · S7 (동시호가 08:30~09:00) 풀은
        // preloadCandidatePools 가 09:05 부터 실행되므로 여기서 미리 적재
        try {
            for (String mkt : new String[]{"001", "101"}) {
                try { candidateService.getS1Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S1 {} 오류: {}", mkt, e.getMessage()); }
                try { candidateService.getS7Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S7 {} 오류: {}", mkt, e.getMessage()); }
            }
            log.info("[Pool] S1/S7 사전 적재 완료");
        } catch (Exception e) {
            log.error("[Pool] S1/S7 사전 적재 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 장전 데이터 준비
    // ─────────────────────────────────────────────

    /** 08:00 – 후보 종목 전일종가 일괄 수집 후 Redis 저장 (S1 갭 계산용) */
    @Scheduled(cron = "0 0 8 * * MON-FRI")
    public void preparePreOpenData() {
        log.info("=== 장전 전일종가 사전 저장 시작 (08:00) ===");
        try {
            // getAllCandidates()는 candidates:001/101 (구형 키, 미적재)를 읽어 항상 0개 반환.
            // 전일종가가 필요한 전략은 S1·S7(갭 계산)이므로 해당 풀을 직접 조회한다.
            // getS1/S7Candidates()는 캐시 만료 시 ka10029를 재호출하여 풀을 갱신한다.
            java.util.Set<String> candidateSet = new java.util.LinkedHashSet<>();
            for (String mkt : new String[]{"001", "101"}) {
                candidateSet.addAll(candidateService.getS1Candidates(mkt));
                candidateSet.addAll(candidateService.getS7Candidates(mkt));
            }
            List<String> candidates = new ArrayList<>(candidateSet);
            log.info("[PreOpen] S1+S7 후보 종목 {}개에 대해 전일종가 수집 시작", candidates.size());

            List<CompletableFuture<Void>> futures = new ArrayList<>();
            for (String stkCd : candidates) {
                CompletableFuture<Void> f = CompletableFuture.runAsync(() -> {
                    try {
                        KiwoomApiResponses.StkBasicInfoResponse info =
                                kiwoomApiService.fetchKa10001(stkCd);
                        if (info != null && info.getBasePric() != null) {
                            String key = "ws:expected:" + stkCd;
                            redis.opsForHash().put(key, "pred_pre_pric", info.getBasePric());
                            redis.expire(key, Duration.ofHours(12));
                        }
                    } catch (Exception e) {
                        log.debug("[PreOpen] {} 전일종가 조회 실패: {}", stkCd, e.getMessage());
                    }
                }, PRELOAD_POOL);
                futures.add(f);
            }
            CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
            log.info("[PreOpen] 전일종가 사전 저장 완료 – {}개 처리", futures.size());
        } catch (Exception e) {
            log.error("[PreOpen] 전일종가 사전 저장 실패: {}", e.getMessage());
        }
    }

    /** 08:30 - 장전 뉴스 브리핑 발행 */
    @Scheduled(cron = "0 30 8 * * MON-FRI")
    public void preMarketNewsBrief() {
        log.info("=== 장전 뉴스 브리핑 발행 (08:30) ===");
        try {
            String control    = redis.opsForValue().get("news:trading_control");
            String sentiment  = redis.opsForValue().get("news:market_sentiment");
            String sectorsRaw = redis.opsForValue().get("news:sector_recommend");
            String analysisRaw = redis.opsForValue().get("news:analysis");
            if (control == null) control = "CONTINUE";
            if (sentiment == null) sentiment = "NEUTRAL";

            List<String> sectors = List.of();
            if (sectorsRaw != null && !sectorsRaw.isBlank()) {
                try { sectors = objectMapper.readValue(sectorsRaw, new TypeReference<List<String>>() {}); }
                catch (Exception e) { /* ignore */ }
            }
            String summary = "";
            if (analysisRaw != null) {
                try {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> analysis = objectMapper.readValue(analysisRaw, Map.class);
                    Object s = analysis.get("summary");
                    if (s != null && !s.toString().equals("null")) summary = s.toString();
                } catch (Exception e) { /* ignore */ }
            }

            String ctrlEmoji = switch (control) {
                case "PAUSE"    -> "🚨";
                case "CAUTIOUS" -> "⚠️";
                default         -> "✅";
            };
            String ctrlLabel = switch (control) {
                case "PAUSE"    -> "매매 중단";
                case "CAUTIOUS" -> "신중 매매";
                default         -> "정상 매매";
            };
            String sentLabel = "BULLISH".equals(sentiment) ? "강세 📈"
                    : "BEARISH".equals(sentiment) ? "약세 📉" : "중립 ➡️";

            StringBuilder sb = new StringBuilder("📰 <b>[장전 뉴스 브리핑] 08:30</b>\n\n");
            sb.append(ctrlEmoji).append(" 매매 상태: <b>").append(ctrlLabel).append("</b>\n");
            sb.append("시장 심리: ").append(sentLabel).append("\n");
            if (!sectors.isEmpty()) {
                sb.append("추천 섹터: ").append(String.join(", ", sectors)).append("\n");
            }
            if (!summary.isBlank()) {
                sb.append("\n").append(summary);
            } else {
                sb.append("\n⚠️ 뉴스 분석 데이터 없음 – ai-engine 확인 필요");
            }
            String eventLine = buildTodayEventLine();
            if (!eventLine.isBlank()) sb.append("\n\n📅 오늘 이벤트: ").append(eventLine);

            Map<String, Object> msg = Map.of(
                    "type",    "PRE_MARKET_BRIEF",
                    "message", sb.toString().trim()
            );
            redisMarketDataService.pushScoredQueue(objectMapper.writeValueAsString(msg));
            log.info("[PreMarketBrief] 장전 뉴스 브리핑 발행 완료 – control={} sentiment={}", control, sentiment);

            // MarketDailyContext 장전 스냅샷 저장 (당일 행이 없을 때만 INSERT)
            saveMarketDailyContextMorning(sentiment, control);
        } catch (Exception e) {
            log.error("[PreMarketBrief] 장전 뉴스 브리핑 실패: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 정규장 진입 (09:00)
    // ─────────────────────────────────────────────

    /** 09:00 - 정규장 시작 로그 (Python websocket-listener 단독 운영) */
    @Scheduled(cron = "0 0 9 * * MON-FRI")
    public void startMarketHours() {
        log.info("=== 정규장 시작 (09:00) – Python websocket-listener 운영 중 ===");
    }

    /** 09:01 - 장시작 브리핑 자동 알림 */
    @Scheduled(cron = "0 1 9 * * MON-FRI")
    public void marketOpenBrief() {
        log.info("=== 장시작 브리핑 발행 (09:01) ===");
        try {
            List<String> kospi  = candidateService.getCandidates("001");
            List<String> kosdaq = candidateService.getCandidates("101");

            TradingControl control = newsControlService.getTradingControl();
            String sentiment  = redis.opsForValue().get("news:market_sentiment");
            String sectorsRaw = redis.opsForValue().get("news:sector_recommend");

            List<String> sectors = List.of();
            try {
                if (sectorsRaw != null && !sectorsRaw.isBlank())
                    sectors = objectMapper.readValue(sectorsRaw, new TypeReference<List<String>>() {});
            } catch (Exception e) { /* ignore */ }

            String ctrlLabel = switch (control) {
                case PAUSE    -> "🚨 매매 중단";
                case CAUTIOUS -> "⚠️ 신중 매매";
                default       -> "✅ 정상 매매";
            };
            String sentLabel = "BULLISH".equals(sentiment) ? "강세 📈"
                    : "BEARISH".equals(sentiment) ? "약세 📉" : "중립 ➡️";

            StringBuilder sb = new StringBuilder("📢 <b>[장시작 브리핑] 09:00</b>\n\n");
            sb.append("매매 상태: ").append(ctrlLabel).append("\n");
            sb.append("시장 심리: ").append(sentLabel).append("\n");
            sb.append("후보 종목: 코스피 ").append(kospi.size()).append("개 / 코스닥 ").append(kosdaq.size()).append("개\n");
            if (!sectors.isEmpty()) {
                sb.append("추천 섹터: ").append(String.join(", ", sectors)).append("\n");
            }

            String eventLine = buildTodayEventLine();
            if (!eventLine.isBlank()) sb.append("오늘 이벤트: ").append(eventLine);

            Map<String, Object> msg = Map.of(
                    "type",    "MARKET_OPEN_BRIEF",
                    "message", sb.toString().trim()
            );
            redisMarketDataService.pushScoredQueue(objectMapper.writeValueAsString(msg));
            log.info("[OpenBrief] 장시작 브리핑 발행 완료");
        } catch (Exception e) {
            log.error("[OpenBrief] 브리핑 발행 실패: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 후보 풀 적재 – Python strategy_runner 가 읽음 (09:05~14:30, 15분마다)
    // ─────────────────────────────────────────────

    /**
     * 09:05 ~ 14:30 매 15분 – S8~S15 스윙 후보 풀 갱신.
     * Python strategy_runner 가 언제 실행되더라도 candidates:s*:{market} 풀이
     * Redis 에 존재하도록 보장. S1/S7 은 startPreMarketSubscription(07:30) 에서 적재.
     */
    @Scheduled(cron = "0 5/15 9-14 * * MON-FRI")
    public void preloadCandidatePools() {
        LocalTime now = LocalTime.now();
        if (now.isAfter(LocalTime.of(14, 30))) return;
        log.debug("[Pool] 후보 풀 사전 적재 시작");
        try {
            PRELOAD_POOL.submit(() -> {
                for (String mkt : new String[]{"001", "101"}) {
                    try { candidateService.getS4Candidates(mkt); }  catch (Exception e) { log.warn("[Pool] S4 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS8Candidates(mkt); }  catch (Exception e) { log.warn("[Pool] S8 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS9Candidates(mkt); }  catch (Exception e) { log.warn("[Pool] S9 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS10Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S10 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS11Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S11 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS12Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S12 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS13Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S13 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS14Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S14 {} 오류: {}", mkt, e.getMessage()); }
                    try { candidateService.getS15Candidates(mkt); } catch (Exception e) { log.warn("[Pool] S15 {} 오류: {}", mkt, e.getMessage()); }
                }
                log.info("[Pool] 후보 풀 사전 적재 완료");
            });
        } catch (Exception e) {
            log.error("[Pool] 사전 적재 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 공통 유지보수 스케줄
    // ─────────────────────────────────────────────

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

    /** 12:30 – 오전 신호 현황 중간 보고 */
    @Scheduled(cron = "0 30 12 * * MON-FRI")
    public void compileMiddayReport() {
        log.info("=== 오전 중간 보고 (12:30) ===");
        try {
            List<Object[]> stats = signalService.getTodayStats();
            long dailyCount = redisMarketDataService.getDailySignalCount();
            int maxDaily    = properties.getTrading().getMaxDailySignals();
            TradingControl control = newsControlService.getTradingControl();

            long totalSignals = stats.stream()
                    .mapToLong(r -> r[1] instanceof Number ? ((Number) r[1]).longValue() : 0L)
                    .sum();

            List<org.invest.apiorchestrator.domain.TradingSignal> todaySignals = signalService.getTodaySignals();
            List<String> topLines = todaySignals.stream()
                    .filter(s -> s.getSignalScore() != null)
                    .sorted((a, b) -> Double.compare(
                            b.getSignalScore() != null ? b.getSignalScore() : 0,
                            a.getSignalScore()))
                    .limit(2)
                    .map(s -> String.format("  %s [%s] %.0f점",
                            s.getStkNm() != null ? s.getStkNm() : s.getStkCd(),
                            s.getStrategy(), s.getSignalScore()))
                    .toList();

            String ctrlLabel = switch (control) {
                case PAUSE    -> "🚨 매매 중단";
                case CAUTIOUS -> "⚠️ 신중 매매";
                default       -> "✅ 정상 매매";
            };

            StringBuilder sb = new StringBuilder("📊 <b>[오전 신호 현황] 12:30</b>\n\n");
            sb.append("총 신호: ").append(totalSignals).append("건");
            sb.append(" (남은 한도: ").append(Math.max(0, maxDaily - dailyCount)).append("건)\n");
            sb.append("매매 제어: ").append(ctrlLabel).append("\n");

            if (!topLines.isEmpty()) {
                sb.append("\nTOP 신호:\n").append(String.join("\n", topLines)).append("\n");
            }

            Map<String, Long> sectorCount = todaySignals.stream()
                    .filter(s -> s.getThemeName() != null)
                    .collect(java.util.stream.Collectors.groupingBy(
                            s -> s.getThemeName().length() > 6 ? s.getThemeName().substring(0, 6) : s.getThemeName(),
                            java.util.stream.Collectors.counting()))
                    .entrySet().stream()
                    .sorted(Map.Entry.<String, Long>comparingByValue().reversed())
                    .limit(3)
                    .collect(java.util.stream.Collectors.toMap(
                            Map.Entry::getKey, Map.Entry::getValue,
                            (a, b) -> a, java.util.LinkedHashMap::new));

            if (!sectorCount.isEmpty()) {
                sb.append("\n집중 테마:\n");
                sectorCount.forEach((k, v) -> sb.append("  ").append(k).append(": ").append(v).append("건\n"));
            }

            Map<String, Object> msg = Map.of(
                    "type",    "MIDDAY_REPORT",
                    "message", sb.toString().trim()
            );
            redisMarketDataService.pushScoredQueue(objectMapper.writeValueAsString(msg));
            log.info("[Midday] 오전 중간 보고 발행 완료 (총 {}건)", totalSignals);
        } catch (Exception e) {
            log.error("[Midday] 오전 중간 보고 실패: {}", e.getMessage());
        }
    }

    /** 15:30 - 장 종료 처리 */
    @Scheduled(cron = "0 30 15 * * MON-FRI")
    public void endOfDay() {
        log.info("=== 장 종료 처리 (15:30) ===");
        try {
            signalService.expireOldSignals();

            // 당일 통계 로그
            signalService.getTodayStats().forEach(row ->
                    log.info("전략별 성과 - strategy={} count={} avgPnl={}",
                            row[0], row[1], row[2]));
        } catch (Exception e) {
            log.error("장 종료 처리 실패: {}", e.getMessage());
        }
    }

    /** 15:35 – 당일 신호 통계 집계 후 Redis + ai_scored_queue 발행 */
    @Scheduled(cron = "0 35 15 * * MON-FRI")
    public void compileDailySummary() {
        log.info("=== 일별 성과 집계 시작 (15:35) ===");
        try {
            List<Object[]> stats = signalService.getTodayStats();

            long totalSignals = 0;
            double totalScore = 0;
            int scoreCount = 0;
            java.util.Map<String, Long> byStrategy = new java.util.LinkedHashMap<>();

            for (Object[] row : stats) {
                String strategy = String.valueOf(row[0]);
                long count = row[1] instanceof Number ? ((Number) row[1]).longValue() : 0L;
                totalSignals += count;
                byStrategy.put(strategy, count);
                if (row[2] instanceof Number) {
                    totalScore += ((Number) row[2]).doubleValue() * count;
                    scoreCount += (int) count;
                }
            }
            double avgScore = scoreCount > 0 ? totalScore / scoreCount : 0.0;

            String today = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
            String summaryKey = "daily_summary:" + today;

            redis.opsForHash().put(summaryKey, "total_signals", String.valueOf(totalSignals));
            redis.opsForHash().put(summaryKey, "avg_score", String.format("%.1f", avgScore));
            try {
                redis.opsForHash().put(summaryKey, "by_strategy",
                        objectMapper.writeValueAsString(byStrategy));
            } catch (Exception ex) {
                redis.opsForHash().put(summaryKey, "by_strategy", byStrategy.toString());
            }
            redis.expire(summaryKey, Duration.ofDays(7));

            long totalWins = 0, totalLosses = 0;
            double totalPnl = 0.0;
            int pnlCount = 0;
            try {
                List<Object[]> perfStats = signalService.getPerformanceStats();
                for (Object[] row : perfStats) {
                    long wins   = row[2] instanceof Number ? ((Number) row[2]).longValue() : 0L;
                    long losses = row[3] instanceof Number ? ((Number) row[3]).longValue() : 0L;
                    double pnl  = row[4] instanceof Number ? ((Number) row[4]).doubleValue() : 0.0;
                    totalWins   += wins;
                    totalLosses += losses;
                    if (wins + losses > 0) { totalPnl += pnl; pnlCount++; }
                }
            } catch (Exception ex) {
                log.debug("[DailySummary] P&L 집계 오류 (무시): {}", ex.getMessage());
            }
            double avgPnl = pnlCount > 0 ? totalPnl / pnlCount : 0.0;

            try {
                java.util.Map<String, Object> report = new java.util.LinkedHashMap<>();
                report.put("type", "DAILY_REPORT");
                report.put("date", today);
                report.put("total_signals", totalSignals);
                report.put("avg_score", avgScore);
                report.put("by_strategy", byStrategy);
                report.put("total_wins",   totalWins);
                report.put("total_losses", totalLosses);
                report.put("avg_pnl",      avgPnl);
                redisMarketDataService.pushTelegramQueue(objectMapper.writeValueAsString(report));
            } catch (Exception ex) {
                log.warn("[DailySummary] 리포트 큐 발행 실패: {}", ex.getMessage());
            }

            // MarketDailyContext 당일 성과 요약 업데이트
            updateMarketDailyContextPerf(totalSignals, totalWins, totalLosses, avgPnl);

            log.info("[DailySummary] 집계 완료 – totalSignals={} avgScore={} wins={} losses={} avgPnl={}",
                    totalSignals, String.format("%.1f", avgScore), totalWins, totalLosses,
                    String.format("%.2f", avgPnl));
        } catch (Exception e) {
            log.error("[DailySummary] 집계 실패: {}", e.getMessage());
        }
    }

    /** 08:30 – MarketDailyContext 장전 뉴스 스냅샷 INSERT (중복 방지) */
    private void saveMarketDailyContextMorning(String sentiment, String control) {
        try {
            LocalDate today = LocalDate.now();
            if (marketDailyContextRepository.existsByDate(today)) return;

            boolean hasEconEvent = false;
            String econEventNm   = null;
            try {
                List<org.invest.apiorchestrator.domain.EconomicEvent> events = calendarService.getTodayEvents();
                if (!events.isEmpty()) {
                    hasEconEvent = true;
                    econEventNm  = events.get(0).getEventName();
                }
            } catch (Exception ignored) {}

            MarketDailyContext ctx = MarketDailyContext.builder()
                    .date(today)
                    .newsSentiment(sentiment)
                    .newsTradingCtrl(control)
                    .economicEventToday(hasEconEvent)
                    .economicEventNm(econEventNm)
                    .build();
            marketDailyContextRepository.save(ctx);
            log.info("[MarketCtx] 장전 스냅샷 저장 – sentiment={} ctrl={}", sentiment, control);
        } catch (Exception e) {
            log.warn("[MarketCtx] 장전 스냅샷 저장 실패 (무시): {}", e.getMessage());
        }
    }

    /** 15:35 – MarketDailyContext 당일 성과 요약 업데이트 */
    private void updateMarketDailyContextPerf(long totalSignals, long wins, long losses, double avgPnl) {
        try {
            LocalDate today = LocalDate.now();
            MarketDailyContext ctx = marketDailyContextRepository.findByDate(today).orElse(null);
            if (ctx == null) {
                ctx = MarketDailyContext.builder().date(today).build();
            }
            BigDecimal winRate = (wins + losses) > 0
                    ? BigDecimal.valueOf((double) wins / (wins + losses) * 100)
                            .setScale(2, java.math.RoundingMode.HALF_UP)
                    : null;
            // MarketDailyContext는 setter가 없으므로 새 객체를 저장 (id 유지)
            ctx = MarketDailyContext.builder()
                    .id(ctx.getId())
                    .date(today)
                    .newsSentiment(ctx.getNewsSentiment())
                    .newsTradingCtrl(ctx.getNewsTradingCtrl())
                    .economicEventToday(ctx.getEconomicEventToday())
                    .economicEventNm(ctx.getEconomicEventNm())
                    .totalSignalsToday((int) totalSignals)
                    .signalWinRateToday(winRate)
                    .avgPnlPctToday(BigDecimal.valueOf(avgPnl).setScale(4, java.math.RoundingMode.HALF_UP))
                    .build();
            marketDailyContextRepository.save(ctx);
            log.info("[MarketCtx] 성과 업데이트 – signals={} winRate={} avgPnl={}",
                    totalSignals, winRate, String.format("%.2f", avgPnl));
        } catch (Exception e) {
            log.warn("[MarketCtx] 성과 업데이트 실패 (무시): {}", e.getMessage());
        }
    }

    /**
     * 오늘 경제 이벤트 한 줄 요약 (장시작 브리핑용)
     */
    private String buildTodayEventLine() {
        try {
            List<org.invest.apiorchestrator.domain.EconomicEvent> events = calendarService.getTodayEvents();
            if (events.isEmpty()) return "";
            return events.stream()
                    .limit(2)
                    .map(e -> {
                        String impact = e.getExpectedImpact() ==
                                org.invest.apiorchestrator.domain.EconomicEvent.ImpactLevel.HIGH ? "🔴" : "🟡";
                        String time = e.getEventTime() != null
                                ? e.getEventTime().toString().substring(0, 5) + " " : "";
                        return impact + " " + time + e.getEventName();
                    })
                    .collect(Collectors.joining(" / "));
        } catch (Exception e) {
            return "";
        }
    }
}
