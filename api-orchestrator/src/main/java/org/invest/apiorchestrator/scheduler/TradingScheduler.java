package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.MarketDailyContext;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.MarketDailyContextRepository;
import org.invest.apiorchestrator.service.CandidateService;
import org.invest.apiorchestrator.service.EconomicCalendarService;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.SignalService;
import org.invest.apiorchestrator.service.TokenService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
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

@Slf4j
@Component
@RequiredArgsConstructor
public class TradingScheduler {

    private static final String KOSPI_PROXY_CODE = "069500";
    private static final String KOSDAQ_PROXY_CODE = "229200";

    private final SignalService signalService;
    private final CandidateService candidateService;
    private final TokenService tokenService;
    private final KiwoomApiService kiwoomApiService;
    private final RedisMarketDataService redisMarketDataService;
    private final EconomicCalendarService calendarService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final MarketDailyContextRepository marketDailyContextRepository;

    private static final ExecutorService PRELOAD_POOL = Executors.newFixedThreadPool(5);

    @Scheduled(cron = "0 50 6 * * MON-FRI", zone = "Asia/Seoul")
    public void dailyPrepare() {
        log.info("=== daily prepare (06:50) ===");
        try {
            tokenService.refreshToken();
        } catch (Exception e) {
            log.error("pre-market token refresh failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 25 7 * * MON-FRI", zone = "Asia/Seoul")
    public void prepareSystem() {
        log.info("=== system prepare (07:25) ===");
        try {
            tokenService.refreshToken();
        } catch (Exception e) {
            log.error("token refresh failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 30 7 * * MON-FRI", zone = "Asia/Seoul")
    public void startPreMarketSubscription() {
        log.info("=== pre-market start (07:30) / python websocket-listener owned ===");
    }

    @Scheduled(cron = "0 50 7 * * MON-FRI", zone = "Asia/Seoul")
    public void preloadAuctionCandidates() {
        log.info("=== preload S1 candidate pools (07:50) ===");
        try {
            for (String market : new String[]{"001", "101"}) {
                try {
                    candidateService.getS1Candidates(market);
                } catch (Exception e) {
                    log.warn("[Pool] S1 {} error: {}", market, e.getMessage());
                }
            }
            log.info("[Pool] S1 preload complete");
        } catch (Exception e) {
            log.error("[Pool] S1 preload failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 45 8 * * MON-FRI", zone = "Asia/Seoul")
    public void preparePreOpenData() {
        log.info("=== prepare pre-open data (08:45) ===");
        try {
            java.util.Set<String> candidateSet = new java.util.LinkedHashSet<>();
            for (String market : new String[]{"001", "101"}) {
                candidateSet.addAll(candidateService.getS1Candidates(market));
            }

            List<String> candidates = new ArrayList<>(candidateSet);
            List<CompletableFuture<Void>> futures = new ArrayList<>();
            for (String stkCd : candidates) {
                CompletableFuture<Void> future = CompletableFuture.runAsync(() -> {
                    try {
                        KiwoomApiResponses.StkBasicInfoResponse info = kiwoomApiService.fetchKa10001(stkCd);
                        if (info != null && info.getBasePric() != null) {
                            String key = "ws:expected:" + stkCd;
                            redis.opsForHash().put(key, "pred_pre_pric", info.getBasePric());
                            redis.expire(key, Duration.ofHours(12));
                        }
                    } catch (Exception e) {
                        log.debug("[PreOpen] {} fetch failed: {}", stkCd, e.getMessage());
                    }
                }, PRELOAD_POOL);
                futures.add(future);
            }
            CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
            log.info("[PreOpen] expected-price preload complete count={}", futures.size());
        } catch (Exception e) {
            log.error("[PreOpen] expected-price preload failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 55 7 * * MON-FRI", zone = "Asia/Seoul")
    public void captureMorningMarketContext() {
        try {
            String control = redis.opsForValue().get("news:trading_control");
            String sentiment = redis.opsForValue().get("news:market_sentiment");
            saveMarketDailyContextMorning(
                    sentiment != null ? sentiment : "NEUTRAL",
                    control != null ? control : "CONTINUE"
            );
        } catch (Exception e) {
            log.error("[MarketCtx] morning snapshot failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 0 9 * * MON-FRI", zone = "Asia/Seoul")
    public void startMarketHours() {
        log.info("=== market open (09:00) / python websocket-listener owned ===");
    }

    @Scheduled(cron = "0 5/15 9-14 * * MON-FRI", zone = "Asia/Seoul")
    public void preloadCandidatePools() {
        LocalTime now = KstClock.nowTime();
        if (now.isAfter(LocalTime.of(14, 30))) {
            return;
        }

        log.debug("[Pool] intraday preload start");
        try {
            PRELOAD_POOL.submit(() -> {
                for (String market : new String[]{"001", "101"}) {
                    try { candidateService.getS4Candidates(market); }  catch (Exception e) { log.warn("[Pool] S4 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS8Candidates(market); }  catch (Exception e) { log.warn("[Pool] S8 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS9Candidates(market); }  catch (Exception e) { log.warn("[Pool] S9 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS10Candidates(market); } catch (Exception e) { log.warn("[Pool] S10 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS11Candidates(market); } catch (Exception e) { log.warn("[Pool] S11 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS12Candidates(market); } catch (Exception e) { log.warn("[Pool] S12 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS13Candidates(market); } catch (Exception e) { log.warn("[Pool] S13 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS14Candidates(market); } catch (Exception e) { log.warn("[Pool] S14 {} error: {}", market, e.getMessage()); }
                    try { candidateService.getS15Candidates(market); } catch (Exception e) { log.warn("[Pool] S15 {} error: {}", market, e.getMessage()); }
                }
                log.info("[Pool] intraday preload complete");
            });
        } catch (Exception e) {
            log.error("[Pool] intraday preload failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 0 * * * MON-FRI", zone = "Asia/Seoul")
    public void expireOldSignals() {
        try {
            int count = signalService.expireOldSignals();
            if (count > 0) {
                log.info("expired old signals count={}", count);
            }
        } catch (Exception e) {
            log.error("expire old signals failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 30 15 * * MON-FRI", zone = "Asia/Seoul")
    public void endOfDay() {
        log.info("=== end of day (15:30) ===");
        try {
            signalService.expireOldSignals();
            signalService.getTodayStats().forEach(row ->
                    log.info("strategy stat strategy={} count={} avgPnl={}", row[0], row[1], row[2]));
        } catch (Exception e) {
            log.error("end-of-day processing failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 35 15 * * MON-FRI", zone = "Asia/Seoul")
    public void compileDailySummary() {
        log.info("=== compile daily summary (15:35) ===");
        try {
            List<Object[]> stats = signalService.getTodayStats();

            long totalSignals = 0;
            double totalScore = 0;
            int scoreCount = 0;
            Map<String, Long> byStrategy = new java.util.LinkedHashMap<>();

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

            String today = KstClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
            String summaryKey = "daily_summary:" + today;

            redis.opsForHash().put(summaryKey, "total_signals", String.valueOf(totalSignals));
            redis.opsForHash().put(summaryKey, "avg_score", String.format("%.1f", avgScore));
            try {
                redis.opsForHash().put(summaryKey, "by_strategy", objectMapper.writeValueAsString(byStrategy));
            } catch (Exception e) {
                redis.opsForHash().put(summaryKey, "by_strategy", byStrategy.toString());
            }
            redis.expire(summaryKey, Duration.ofDays(7));

            long totalWins = 0;
            long totalLosses = 0;
            double totalPnl = 0.0;
            int pnlCount = 0;
            try {
                List<Object[]> perfStats = signalService.getPerformanceStats();
                for (Object[] row : perfStats) {
                    long wins = row[2] instanceof Number ? ((Number) row[2]).longValue() : 0L;
                    long losses = row[3] instanceof Number ? ((Number) row[3]).longValue() : 0L;
                    double pnl = row[4] instanceof Number ? ((Number) row[4]).doubleValue() : 0.0;
                    totalWins += wins;
                    totalLosses += losses;
                    if (wins + losses > 0) {
                        totalPnl += pnl;
                        pnlCount++;
                    }
                }
            } catch (Exception e) {
                log.debug("[DailySummary] performance stat error ignored: {}", e.getMessage());
            }
            double avgPnl = pnlCount > 0 ? totalPnl / pnlCount : 0.0;

            try {
                Map<String, Object> report = new java.util.LinkedHashMap<>();
                report.put("type", "DAILY_REPORT");
                report.put("date", today);
                report.put("total_signals", totalSignals);
                report.put("avg_score", avgScore);
                report.put("by_strategy", byStrategy);
                report.put("total_wins", totalWins);
                report.put("total_losses", totalLosses);
                report.put("avg_pnl", avgPnl);
                redisMarketDataService.pushTelegramQueue(objectMapper.writeValueAsString(report));
                redis.opsForValue().set("ops:scheduler:daily_summary:last_status", "OK", Duration.ofDays(2));
                redis.opsForValue().set("ops:scheduler:daily_summary:last_success_at", KstClock.nowOffset().toString(), Duration.ofDays(2));
            } catch (Exception e) {
                log.warn("[DailySummary] report publish failed: {}", e.getMessage());
                redis.opsForValue().set("ops:scheduler:daily_summary:last_status", "ERROR", Duration.ofDays(2));
            }

            updateMarketDailyContextPerf(totalSignals, totalWins, totalLosses, avgPnl);
            log.info(
                    "[DailySummary] done totalSignals={} avgScore={} wins={} losses={} avgPnl={}",
                    totalSignals,
                    String.format("%.1f", avgScore),
                    totalWins,
                    totalLosses,
                    String.format("%.2f", avgPnl)
            );
        } catch (Exception e) {
            log.error("[DailySummary] failed: {}", e.getMessage());
        }
    }

    private void saveMarketDailyContextMorning(String sentiment, String control) {
        try {
            LocalDate today = KstClock.today();
            if (marketDailyContextRepository.existsByDate(today)) {
                return;
            }

            MarketProxySnapshot kospi = loadMarketProxy(KOSPI_PROXY_CODE);
            MarketProxySnapshot kosdaq = loadMarketProxy(KOSDAQ_PROXY_CODE);
            BreadthSnapshot breadth = loadBreadthSnapshot();
            NetBuySnapshot kospiNetBuy = loadNetBuySnapshot("001");
            NetBuySnapshot kosdaqNetBuy = loadNetBuySnapshot("101");

            boolean hasEconEvent = false;
            String econEventName = null;
            try {
                List<org.invest.apiorchestrator.domain.EconomicEvent> events = calendarService.getTodayEvents();
                if (!events.isEmpty()) {
                    hasEconEvent = true;
                    econEventName = events.get(0).getEventName();
                }
            } catch (Exception ignored) {
            }

            MarketDailyContext context = MarketDailyContext.builder()
                    .date(today)
                    .kospiOpen(kospi.open())
                    .kospiClose(kospi.close())
                    .kospiChangePct(kospi.changePct())
                    .kospiVolume(kospi.volume())
                    .kosdaqOpen(kosdaq.open())
                    .kosdaqClose(kosdaq.close())
                    .kosdaqChangePct(kosdaq.changePct())
                    .kosdaqVolume(kosdaq.volume())
                    .advancingStocks(breadth.advancing())
                    .decliningStocks(breadth.declining())
                    .unchangedStocks(breadth.unchanged())
                    .advanceDeclineRatio(breadth.ratio())
                    .frgnNetBuyKospi(kospiNetBuy.foreignNetBuy())
                    .instNetBuyKospi(kospiNetBuy.instNetBuy())
                    .frgnNetBuyKosdaq(kosdaqNetBuy.foreignNetBuy())
                    .instNetBuyKosdaq(kosdaqNetBuy.instNetBuy())
                    .newsSentiment(sentiment)
                    .newsTradingCtrl(control)
                    .vixEquivalent(breadth.vixEquivalent())
                    .economicEventToday(hasEconEvent)
                    .economicEventNm(econEventName)
                    .build();
            marketDailyContextRepository.save(context);
            log.info("[MarketCtx] morning snapshot saved sentiment={} control={}", sentiment, control);
        } catch (Exception e) {
            log.warn("[MarketCtx] morning snapshot save failed: {}", e.getMessage());
        }
    }

    private void updateMarketDailyContextPerf(long totalSignals, long wins, long losses, double avgPnl) {
        try {
            LocalDate today = KstClock.today();
            MarketDailyContext context = marketDailyContextRepository.findByDate(today).orElse(null);
            if (context == null) {
                context = MarketDailyContext.builder().date(today).build();
            }

            BigDecimal winRate = (wins + losses) > 0
                    ? BigDecimal.valueOf((double) wins / (wins + losses) * 100).setScale(2, RoundingMode.HALF_UP)
                    : null;

            context = copyContext(context)
                    .totalSignalsToday((int) totalSignals)
                    .signalWinRateToday(winRate)
                    .avgPnlPctToday(BigDecimal.valueOf(avgPnl).setScale(4, RoundingMode.HALF_UP))
                    .build();
            marketDailyContextRepository.save(context);
            log.info("[MarketCtx] performance updated signals={} winRate={} avgPnl={}", totalSignals, winRate, String.format("%.2f", avgPnl));
        } catch (Exception e) {
            log.warn("[MarketCtx] performance update failed: {}", e.getMessage());
        }
    }

    private MarketDailyContext.MarketDailyContextBuilder copyContext(MarketDailyContext ctx) {
        return MarketDailyContext.builder()
                .id(ctx.getId())
                .date(ctx.getDate())
                .kospiOpen(ctx.getKospiOpen())
                .kospiClose(ctx.getKospiClose())
                .kospiChangePct(ctx.getKospiChangePct())
                .kospiVolume(ctx.getKospiVolume())
                .kosdaqOpen(ctx.getKosdaqOpen())
                .kosdaqClose(ctx.getKosdaqClose())
                .kosdaqChangePct(ctx.getKosdaqChangePct())
                .kosdaqVolume(ctx.getKosdaqVolume())
                .advancingStocks(ctx.getAdvancingStocks())
                .decliningStocks(ctx.getDecliningStocks())
                .unchangedStocks(ctx.getUnchangedStocks())
                .advanceDeclineRatio(ctx.getAdvanceDeclineRatio())
                .frgnNetBuyKospi(ctx.getFrgnNetBuyKospi())
                .instNetBuyKospi(ctx.getInstNetBuyKospi())
                .frgnNetBuyKosdaq(ctx.getFrgnNetBuyKosdaq())
                .instNetBuyKosdaq(ctx.getInstNetBuyKosdaq())
                .newsSentiment(ctx.getNewsSentiment())
                .newsTradingCtrl(ctx.getNewsTradingCtrl())
                .vixEquivalent(ctx.getVixEquivalent())
                .economicEventToday(ctx.getEconomicEventToday())
                .economicEventNm(ctx.getEconomicEventNm())
                .totalSignalsToday(ctx.getTotalSignalsToday())
                .signalWinRateToday(ctx.getSignalWinRateToday())
                .avgPnlPctToday(ctx.getAvgPnlPctToday())
                .recordedAt(ctx.getRecordedAt());
    }

    private MarketProxySnapshot loadMarketProxy(String stkCd) {
        try {
            KiwoomApiResponses.StkBasicInfoResponse response = kiwoomApiService.fetchKa10001(stkCd);
            if (response == null || !response.isSuccess()) {
                return MarketProxySnapshot.empty();
            }
            return new MarketProxySnapshot(
                    dec(response.getOpenPric(), 2),
                    dec(response.getCurPrc(), 2),
                    dec(response.getFluRt(), 3),
                    lng(response.getTrdeQty())
            );
        } catch (Exception e) {
            log.debug("[MarketCtx] proxy load failed [{}]: {}", stkCd, e.getMessage());
            return MarketProxySnapshot.empty();
        }
    }

    private BreadthSnapshot loadBreadthSnapshot() {
        try {
            java.util.Set<String> codes = new java.util.LinkedHashSet<>();
            addAllCodes(codes, redis.opsForSet().members("candidates:watchlist"));
            addAllCodes(codes, redis.opsForSet().members("candidates:watchlist:priority"));
            signalService.getTodaySignals().stream()
                    .map(org.invest.apiorchestrator.domain.TradingSignal::getStkCd)
                    .filter(value -> value != null && !value.isBlank())
                    .forEach(codes::add);

            int advancing = 0;
            int declining = 0;
            int unchanged = 0;
            double absSum = 0.0;
            int absCount = 0;

            for (String code : codes) {
                Map<Object, Object> tick = redisMarketDataService.getTickData(code).orElse(null);
                if (tick == null) {
                    continue;
                }
                Double fluRt = dbl(tick.get("flu_rt"));
                if (fluRt == null) {
                    continue;
                }
                if (fluRt > 0) {
                    advancing++;
                } else if (fluRt < 0) {
                    declining++;
                } else {
                    unchanged++;
                }
                absSum += Math.abs(fluRt);
                absCount++;
            }

            BigDecimal ratio = declining > 0
                    ? BigDecimal.valueOf((double) advancing / declining).setScale(3, RoundingMode.HALF_UP)
                    : (advancing > 0 ? BigDecimal.valueOf(999.0).setScale(3, RoundingMode.HALF_UP) : null);
            BigDecimal vixEquivalent = absCount > 0
                    ? BigDecimal.valueOf((absSum / absCount) * 10.0).setScale(2, RoundingMode.HALF_UP)
                    : null;
            return new BreadthSnapshot(advancing, declining, unchanged, ratio, vixEquivalent);
        } catch (Exception e) {
            log.debug("[MarketCtx] breadth snapshot failed: {}", e.getMessage());
            return new BreadthSnapshot(0, 0, 0, null, null);
        }
    }

    private NetBuySnapshot loadNetBuySnapshot(String market) {
        try {
            KiwoomApiResponses.FrgnInstUpperResponse response = kiwoomApiService.post(
                    "ka90009",
                    "/api/dostk/rkinfo",
                    StrategyRequests.FrgnInstUpperRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.FrgnInstUpperResponse.class
            );
            if (response == null || !response.isSuccess() || response.getItems() == null) {
                return NetBuySnapshot.empty();
            }

            BigDecimal foreign = response.getItems().stream()
                    .map(item -> dec(item.getForBuyAmt(), 0))
                    .filter(java.util.Objects::nonNull)
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
            BigDecimal institutional = response.getItems().stream()
                    .map(item -> dec(item.getOrgBuyAmt(), 0))
                    .filter(java.util.Objects::nonNull)
                    .reduce(BigDecimal.ZERO, BigDecimal::add);

            return new NetBuySnapshot(
                    foreign.compareTo(BigDecimal.ZERO) == 0 ? null : foreign,
                    institutional.compareTo(BigDecimal.ZERO) == 0 ? null : institutional
            );
        } catch (Exception e) {
            log.debug("[MarketCtx] net buy snapshot failed [{}]: {}", market, e.getMessage());
            return NetBuySnapshot.empty();
        }
    }

    private void addAllCodes(java.util.Set<String> target, java.util.Set<String> source) {
        if (source == null) {
            return;
        }
        source.stream()
                .filter(value -> value != null && !value.isBlank())
                .forEach(target::add);
    }

    private BigDecimal dec(Object value, int scale) {
        Double parsed = dbl(value);
        if (parsed == null) {
            return null;
        }
        return BigDecimal.valueOf(parsed).setScale(scale, RoundingMode.HALF_UP);
    }

    private Double dbl(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Double.parseDouble(value.toString().replace(",", "").replace("+", "").trim());
        } catch (Exception e) {
            return null;
        }
    }

    private Long lng(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Long.parseLong(value.toString().replace(",", "").replace("+", "").trim());
        } catch (Exception e) {
            return null;
        }
    }

    private record MarketProxySnapshot(BigDecimal open, BigDecimal close, BigDecimal changePct, Long volume) {
        private static MarketProxySnapshot empty() {
            return new MarketProxySnapshot(null, null, null, null);
        }
    }

    private record NetBuySnapshot(BigDecimal foreignNetBuy, BigDecimal instNetBuy) {
        private static NetBuySnapshot empty() {
            return new NetBuySnapshot(null, null);
        }
    }

    private record BreadthSnapshot(
            int advancing,
            int declining,
            int unchanged,
            BigDecimal ratio,
            BigDecimal vixEquivalent
    ) {
    }
}
