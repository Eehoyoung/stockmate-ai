package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.MarketDailyContext;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.dto.res.KiwoomSupplementalResponses;
import org.invest.apiorchestrator.repository.MarketDailyContextRepository;
import org.invest.apiorchestrator.service.CandidateService;
import org.invest.apiorchestrator.service.DailyAggregationService;
import org.invest.apiorchestrator.service.EconomicCalendarService;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.SignalService;
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
    private final KiwoomApiService kiwoomApiService;
    private final RedisMarketDataService redisMarketDataService;
    private final EconomicCalendarService calendarService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final MarketDailyContextRepository marketDailyContextRepository;
    private final DailyAggregationService dailyAggregationService;

    private static final ExecutorService PRELOAD_POOL = Executors.newFixedThreadPool(5);

    @Scheduled(cron = "0 30 7 * * MON-FRI", zone = "Asia/Seoul")
    public void startPreMarketSubscription() {
        log.info("=== pre-market start (07:30) / python websocket-listener owned ===");
    }

    /**
     * 07:50 최초 시도. ka10029(stkCnd=16, 예상체결등락률)는 이 시각에는 구조적으로
     * 데이터가 비어 있는 경우가 대부분이라(2026-07-20~24 5거래일 전수 실패 확인),
     * 결과 없음을 장애로 취급하지 않고 INFO 로 남긴다. 실제 재적재는 08:26부터
     * 시작되는 {@link #recoverS1PoolUntil0930()} 의 2분 간격 재시도가 담당한다.
     */
    @Scheduled(cron = "0 50 7 * * MON-FRI", zone = "Asia/Seoul")
    public void preloadAuctionCandidates() {
        if (!candidateService.javaOwnsCandidatePools()) {
            log.debug("[Pool] Python owns candidate pools; Java preload skipped");
            return;
        }
        log.info("=== preload S1 candidate pools (07:50) ===");
        int totalLoaded = 0;
        for (String market : new String[]{"001", "101"}) {
            int count = candidateService.preloadS1Candidates(market);
            if (count > 0) {
                log.info("[Pool] S1 preload OK [market={}] count={}", market, count);
                totalLoaded += count;
            } else if (count == 0) {
                log.info("[Pool] S1 preload 결과 없음(예상됨, ka10029 데이터 미가용 시간대) [market={}] — 08:26부터 재시도", market);
            }
        }
        if (totalLoaded == 0) {
            log.info("[Pool] S1 preload 07:50 시점 전체 0건(예상됨) — 08:26부터 2분 간격 재시도");
        } else {
            log.info("[Pool] S1 preload complete total={}", totalLoaded);
        }
    }

    /** S1 풀 비었을 때 08:20 재시도 */
    @Scheduled(cron = "0 20 8 * * MON-FRI", zone = "Asia/Seoul")
    public void retryS1PoolIfEmpty() {
        if (!candidateService.javaOwnsCandidatePools()) return;
        for (String market : new String[]{"001", "101"}) {
            Long llen = redis.opsForList().size("candidates:s1:" + market);
            if (llen == null || llen == 0) {
                log.warn("[Pool] S1 풀 비어 있음 [market={}] — 재적재 시도", market);
                int count = candidateService.preloadS1Candidates(market);
                if (count > 0) {
                    log.info("[Pool] S1 재적재 성공 [market={}] count={}", market, count);
                } else {
                    log.error("[Pool] S1 재적재 실패 [market={}] count={} — 08:25 최종 재시도 예정", market, count);
                }
            }
        }
    }

    /** S1 풀 비었을 때 08:25 최종 재시도 (08:30 스캔 직전 마지막 기회) */
    @Scheduled(cron = "0 25 8 * * MON-FRI", zone = "Asia/Seoul")
    public void finalRetryS1PoolBeforeScan() {
        if (!candidateService.javaOwnsCandidatePools()) return;
        for (String market : new String[]{"001", "101"}) {
            Long llen = redis.opsForList().size("candidates:s1:" + market);
            if (llen == null || llen == 0) {
                log.warn("[Pool] S1 풀 비어 있음 [market={}] — 08:25 최종 재시도", market);
                int count = candidateService.preloadS1Candidates(market);
                if (count > 0) {
                    log.info("[Pool] S1 최종 재적재 성공 [market={}] count={}", market, count);
                } else {
                    log.error("[Pool] S1 최종 재적재 실패 [market={}] count={} — 08:30 스캔 풀 없음", market, count);
                }
            }
        }
    }

    /**
     * Python owns S1 candidate writes. Java keeps this recovery hook only for
     * the explicit CANDIDATE_POOL_OWNER=JAVA rollback configuration; under the
     * production default it exits before making a Kiwoom request.
     *
     * <p>2026-07-20~24 로그 분석 결과 07:50/08:20/08:25 세 차례 시도가 5거래일
     * 모두 0건이었고, 08:30 S1 스캔 시작 이후에도 08:45 {@link #preparePreOpenData()}가
     * 우연히 {@code getS1Candidates()} 를 호출해서야(일부 거래일) 풀이 채워졌다.
     * 08:25~08:50 사이 25분간 명시적 재시도가 없던 공백을 없애기 위해 시작 시각을
     * 08:26 으로 앞당긴다(cron 자체는 08:00부터 2분 간격으로 이미 fire 하고 있었고,
     * 이 가드만 완화하면 됨).
     */
    @Scheduled(cron = "0 */2 8-9 * * MON-FRI", zone = "Asia/Seoul")
    public void recoverS1PoolUntil0930() {
        if (!candidateService.javaOwnsCandidatePools()) return;
        LocalTime now = KstClock.nowTime();
        if (now.isBefore(LocalTime.of(8, 26)) || now.isAfter(LocalTime.of(9, 30))) {
            return;
        }

        for (String market : new String[]{"001", "101"}) {
            Long llen = redis.opsForList().size("candidates:s1:" + market);
            if (llen != null && llen > 0) {
                continue;
            }

            log.warn("[Pool] S1 empty [market={}] - Java recovery retry until 09:30", market);
            int count = candidateService.preloadS1Candidates(market);
            if (count > 0) {
                log.info("[Pool] S1 Java recovery OK [market={}] count={}", market, count);
            } else {
                log.warn("[Pool] S1 Java recovery still empty [market={}] count={}", market, count);
            }
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

    @Scheduled(cron = "0 5 9 * * MON-FRI", zone = "Asia/Seoul")
    public void updateMarketContextAtOpen() {
        try {
            LocalDate today = KstClock.today();
            MarketDailyContext ctx = marketDailyContextRepository.findByDate(today).orElse(null);
            if (ctx == null) return;
            BreadthSnapshot breadth = loadBreadthSnapshot();
            MarketDailyContext updated = copyContext(ctx)
                    .advancingStocks(breadth.advancing())
                    .decliningStocks(breadth.declining())
                    .unchangedStocks(breadth.unchanged())
                    .advanceDeclineRatio(breadth.ratio())
                    .vixEquivalent(breadth.vixEquivalent())
                    .build();
            marketDailyContextRepository.save(updated);
            log.info("[MarketCtx] open breadth snapshot updated advancing={}", breadth.advancing());
        } catch (Exception e) {
            log.warn("[MarketCtx] open snapshot update failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 40 15 * * MON-FRI", zone = "Asia/Seoul")
    public void updateMarketContextAtClose() {
        try {
            LocalDate today = KstClock.today();
            MarketDailyContext ctx = marketDailyContextRepository.findByDate(today).orElse(null);
            if (ctx == null) return;
            String officialSnapshot     = loadOfficialMarketSnapshot();
            boolean officialComplete    = isOfficialSnapshotComplete(officialSnapshot);
            BreadthSnapshot breadth     = loadBreadthSnapshot();
            NetBuySnapshot kospiNetBuy  = loadNetBuySnapshot("001");
            NetBuySnapshot kosdaqNetBuy = loadNetBuySnapshot("101");
            MarketDailyContext updated = copyContext(ctx)
                    .advancingStocks(breadth.advancing())
                    .decliningStocks(breadth.declining())
                    .unchangedStocks(breadth.unchanged())
                    .advanceDeclineRatio(breadth.ratio())
                    .vixEquivalent(breadth.vixEquivalent())
                    .frgnNetBuyKospi(kospiNetBuy.foreignNetBuy())
                    .instNetBuyKospi(kospiNetBuy.instNetBuy())
                    .frgnNetBuyKosdaq(kosdaqNetBuy.foreignNetBuy())
                    .instNetBuyKosdaq(kosdaqNetBuy.instNetBuy())
                    .primarySource(officialSource(officialComplete))
                    .officialSnapshot(officialSnapshot)
                    .sourceComplete(officialComplete)
                    .build();
            marketDailyContextRepository.save(updated);
            log.info("[MarketCtx] close official snapshot updated complete={} advancing={}", officialComplete, breadth.advancing());
        } catch (Exception e) {
            log.warn("[MarketCtx] close snapshot update failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 0 9 * * MON-FRI", zone = "Asia/Seoul")
    public void startMarketHours() {
        log.info("=== market open (09:00) / python websocket-listener owned ===");
    }

    @Scheduled(cron = "0 5/15 9-15 * * MON-FRI", zone = "Asia/Seoul")
    public void preloadCandidatePools() {
        LocalTime now = KstClock.nowTime();
        if (now.isAfter(LocalTime.of(15, 10))) {
            return;
        }

        log.debug("[Pool] intraday preload start");
        try {
            PRELOAD_POOL.submit(() -> {
                boolean intradayWindow = !now.isAfter(LocalTime.of(14, 30));
                for (String market : new String[]{"001", "101"}) {
                    if (intradayWindow) {
                        try { candidateService.getS4Candidates(market); }  catch (Exception e) { log.warn("[Pool] S4 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS8Candidates(market); }  catch (Exception e) { log.warn("[Pool] S8 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS9Candidates(market); }  catch (Exception e) { log.warn("[Pool] S9 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS10Candidates(market); } catch (Exception e) { log.warn("[Pool] S10 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS11Candidates(market); } catch (Exception e) { log.warn("[Pool] S11 {} error: {}", market, e.getMessage()); }
                    }
                    try { candidateService.getS12Candidates(market); } catch (Exception e) { log.warn("[Pool] S12 {} error: {}", market, e.getMessage()); }
                    if (intradayWindow) {
                        try { candidateService.getS13Candidates(market); } catch (Exception e) { log.warn("[Pool] S13 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS14Candidates(market); } catch (Exception e) { log.warn("[Pool] S14 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS15Candidates(market); } catch (Exception e) { log.warn("[Pool] S15 {} error: {}", market, e.getMessage()); }
                        try { candidateService.getS16Candidates(market); } catch (Exception e) { log.warn("[Pool] S16 {} error: {}", market, e.getMessage()); }
                    }
                }
                log.info("[Pool] intraday preload complete");
            });
        } catch (Exception e) {
            log.error("[Pool] intraday preload failed: {}", e.getMessage());
        }
    }

    /**
     * 08:30~09:00 동시호가: 예상체결가로 지수 예상 등락률 산출 (3분 주기).
     * S1 갭전략은 시초가 결정 전 동시호가 데이터로 레짐 판단이 더 정확하다.
     */
    @Scheduled(cron = "0 30-59/3 8 * * MON-FRI", zone = "Asia/Seoul")
    public void pollPreMarketIndexExpFluRt() {
        for (String[] pair : new String[][]{
                {KOSPI_PROXY_CODE, "market:kospi_exp_flu_rt"},
                {KOSDAQ_PROXY_CODE, "market:kosdaq_exp_flu_rt"}
        }) {
            try {
                KiwoomApiResponses.StkBasicInfoResponse res = kiwoomApiService.fetchKa10001(pair[0]);
                if (res == null || !res.isSuccess()) continue;
                Double expPric  = dbl(res.getExpCntrPric());
                Double basePric = dbl(res.getBasePric());
                if (expPric != null && basePric != null && basePric != 0) {
                    double expFluRt = (expPric - basePric) / basePric * 100.0;
                    redis.opsForValue().set(pair[1], String.format("%.2f", expFluRt), Duration.ofMinutes(5));
                    log.debug("[PreMktIdx] {} exp_flu_rt={}", pair[0], String.format("%.2f", expFluRt));
                }
            } catch (Exception e) {
                log.debug("[PreMktIdx] poll failed [{}]: {}", pair[0], e.getMessage());
            }
        }
    }

    /**
     * KOSPI200/코스닥150 ETF 프록시(069500/229200) 기반 등락률 — 실제 지수가 아닌
     * 추적오차가 섞인 대용값이다. TossMarketScheduler.pollTossRegimeCrossCheck()가
     * 이 스케줄러 20초 뒤에 실행되어 진짜 KOSPI/KOSDAQ 지수 값으로 같은 canonical
     * 키를 덮어쓰므로, 이 Kiwoom 값은 토스 호출 실패 시의 안전망 역할이다
     * (2026-08-11, 토스 실지수 연동).
     */
    @Scheduled(cron = "0 */5 9-15 * * MON-FRI", zone = "Asia/Seoul")
    public void pollMarketIndexFluRt() {
        if (KstClock.nowTime().isAfter(LocalTime.of(15, 10))) {
            return;
        }
        for (String[] pair : new String[][]{
                {KOSPI_PROXY_CODE, "market:kospi_flu_rt"},
                {KOSDAQ_PROXY_CODE, "market:kosdaq_flu_rt"}
        }) {
            try {
                KiwoomApiResponses.StkBasicInfoResponse res = kiwoomApiService.fetchKa10001(pair[0]);
                if (res != null && res.isSuccess()) {
                    Double val = dbl(res.getFluRt());
                    if (val != null) {
                        redis.opsForValue().set(pair[1], String.valueOf(val), Duration.ofMinutes(7));
                        redis.opsForValue().set(pair[1] + "_source", "kiwoom_proxy", Duration.ofMinutes(7));
                    }
                }
            } catch (Exception e) {
                log.debug("[MarketIdx] poll failed [{}]: {}", pair[0], e.getMessage());
            }
        }
        log.debug("[MarketIdx] index flu_rt refreshed");
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
                    log.info("strategy stat strategy={} executedCount={} avgAiScore={}", row[0], row[1], row[2]));
        } catch (Exception e) {
            log.error("end-of-day processing failed: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 38 15 * * MON-FRI", zone = "Asia/Seoul")
    public void compileDailySummary() {
        log.info("=== compile daily summary (15:38) ===");
        try {
            LocalDate summaryDate = KstClock.today();
            DailyAggregationService.DailyAggregation aggregation = dailyAggregationService.aggregate(summaryDate);

            long totalSignals = aggregation.totalSignals();
            long enterCount = aggregation.enterCount();
            long cancelCount = aggregation.cancelCount();
            long closedCount = aggregation.closedCount();
            double totalScore = 0;
            int scoreCount = 0;
            Map<String, Long> byStrategy = new java.util.LinkedHashMap<>();

            for (Map.Entry<String, DailyAggregationService.StrategyAggregation> entry : aggregation.byStrategy().entrySet()) {
                long count = entry.getValue().signals().size();
                byStrategy.put(entry.getKey(), count);
                for (org.invest.apiorchestrator.domain.TradingSignal signal : entry.getValue().signals()) {
                    BigDecimal score = signal.getAiScore() != null ? signal.getAiScore() : signal.getRuleScore();
                    if (score != null) {
                        totalScore += score.doubleValue();
                        scoreCount++;
                    }
                }
            }
            double avgScore = scoreCount > 0 ? totalScore / scoreCount : 0.0;

            String today = summaryDate.format(DateTimeFormatter.ofPattern("yyyyMMdd"));
            String summaryKey = "daily_summary:" + today;

            redis.opsForHash().put(summaryKey, "total_signals", String.valueOf(totalSignals));
            redis.opsForHash().put(summaryKey, "enter_count", String.valueOf(enterCount));
            redis.opsForHash().put(summaryKey, "cancel_count", String.valueOf(cancelCount));
            redis.opsForHash().put(summaryKey, "closed_count", String.valueOf(closedCount));
            redis.opsForHash().put(summaryKey, "avg_score", String.format("%.1f", avgScore));
            try {
                redis.opsForHash().put(summaryKey, "by_strategy", objectMapper.writeValueAsString(byStrategy));
            } catch (Exception e) {
                redis.opsForHash().put(summaryKey, "by_strategy", byStrategy.toString());
            }
            redis.expire(summaryKey, Duration.ofDays(7));

            long totalWins = aggregation.tpHitCount();
            long totalLosses = aggregation.slHitCount() + aggregation.forceCloseCount();
            double avgPnl = aggregation.avgPnlPct() != null ? aggregation.avgPnlPct().doubleValue() : 0.0;

            try {
                Map<String, Object> report = new java.util.LinkedHashMap<>();
                report.put("type", "DAILY_REPORT");
                report.put("date", today);
                report.put("total_signals", totalSignals);
                report.put("enter_count", enterCount);
                report.put("cancel_count", cancelCount);
                report.put("closed_count", closedCount);
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
                    "[DailySummary] done totalSignals={} enterCount={} cancelCount={} closedCount={} avgScore={} wins={} losses={} avgPnl={}",
                    totalSignals,
                    enterCount,
                    cancelCount,
                    closedCount,
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

            String officialSnapshot = loadOfficialMarketSnapshot();
            MarketProxySnapshot kospiProxy = loadMarketProxy(KOSPI_PROXY_CODE);
            MarketProxySnapshot kosdaqProxy = loadMarketProxy(KOSDAQ_PROXY_CODE);
            String proxySnapshot = objectMapper.writeValueAsString(Map.of("kospi", kospiProxy, "kosdaq", kosdaqProxy));
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
                    // ETF prices are retained only in proxy_snapshot. They are not index levels.
                    .kospiOpen(null)
                    .kospiClose(null)
                    .kospiChangePct(null)
                    .kospiVolume(null)
                    .kosdaqOpen(null)
                    .kosdaqClose(null)
                    .kosdaqChangePct(null)
                    .kosdaqVolume(null)
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
                    .contextVersion(2)
                    .primarySource(officialSource(isOfficialSnapshotComplete(officialSnapshot)))
                    .officialSnapshot(officialSnapshot)
                    .proxySnapshot(proxySnapshot)
                    .sourceComplete(isOfficialSnapshotComplete(officialSnapshot))
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
                .contextVersion(ctx.getContextVersion())
                .primarySource(ctx.getPrimarySource())
                .officialSnapshot(ctx.getOfficialSnapshot())
                .proxySnapshot(ctx.getProxySnapshot())
                .sourceComplete(ctx.getSourceComplete())
                .recordedAt(ctx.getRecordedAt());
    }

    private String loadOfficialMarketSnapshot() {
        try {
            var indices = new java.util.ArrayList<Map<String, String>>();
            for (String code : List.of("001", "101")) {
                var response = kiwoomApiService.fetchKa20003(
                        StrategyRequests.AllSectorIndexRequest.builder().indsCd(code).build());
                if (response == null || !response.isSuccess() || response.getItems() == null) continue;
                response.getItems().stream()
                        .filter(item -> code.equals(item.getStkCd()))
                        .findFirst()
                        .ifPresent(item -> indices.add(Map.of(
                                "code", item.getStkCd(),
                                "name", item.getStkNm() == null ? "" : item.getStkNm(),
                                "price", item.getCurPrc() == null ? "" : item.getCurPrc(),
                                "change_pct", item.getFluRt() == null ? "" : item.getFluRt(),
                                "volume", item.getTrdeQty() == null ? "" : item.getTrdeQty())));
            }
            return objectMapper.writeValueAsString(Map.of("api_id", "ka20003", "indices", indices));
        } catch (Exception e) {
            log.debug("[MarketCtx] official index load failed: {}", e.getMessage());
            return "{}";
        }
    }

    private boolean isOfficialSnapshotComplete(String snapshot) {
        return snapshot != null
                && snapshot.contains("\"code\":\"001\"")
                && snapshot.contains("\"code\":\"101\"");
    }

    private String officialSource(boolean complete) {
        return complete
                ? "KIWOOM_KA20003_OFFICIAL"
                : "KIWOOM_KA20003_INCOMPLETE";
    }

    private MarketProxySnapshot loadMarketProxy(String stkCd) {
        try {
            KiwoomApiResponses.StkBasicInfoResponse response = kiwoomApiService.fetchKa10001(stkCd);
            if (response == null || !response.isSuccess()) {
                return MarketProxySnapshot.empty();
            }
            return new MarketProxySnapshot(
                    absDec(response.getOpenPric(), 2),
                    absDec(response.getCurPrc(), 2),
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

    private BigDecimal absDec(Object value, int scale) {
        BigDecimal parsed = dec(value, scale);
        return parsed == null ? null : parsed.abs();
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
