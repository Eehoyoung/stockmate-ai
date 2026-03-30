package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import com.fasterxml.jackson.core.type.TypeReference;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.service.*;
import org.invest.apiorchestrator.service.NewsControlService.TradingControl;
import org.invest.apiorchestrator.websocket.WebSocketSubscriptionManager;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;

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
    private final VolSurgeService volSurgeService;
    private final PriceSurgeService priceSurgeService;
    private final BidUpperService bidUpperService;
    private final KiwoomApiService kiwoomApiService;
    private final RedisMarketDataService redisMarketDataService;
    private final NewsControlService newsControlService;
    private final EconomicCalendarService calendarService;
    private final KiwoomProperties properties;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    private static final ExecutorService PRELOAD_POOL = Executors.newFixedThreadPool(5);

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

    /** 08:30~09:00 매 2분 - 전술 7 동시호가 (ka10029 갭필터 + ka10030 거래대금 + BidUpper 교집합) */
    @Scheduled(cron = "0 0/2 8 * * MON-FRI")
    public void scanAuction() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(8, 30)) || now.isAfter(LocalTime.of(9, 0))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S7] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S7] 동시호가 스캔 실행 (사전 필터링 적용, news={}){}",
                newsControl, newsControl == TradingControl.CAUTIOUS ? " [신중모드]" : "");
        try {
            // 사전 필터 1: ka10029 갭 2~10% 종목
            Set<String> gapSet = new java.util.HashSet<>();
            for (String mrkt : new String[]{"001", "101"}) {
                KiwoomApiResponses.ExpCntrFluRtUpperResponse gapResp =
                        kiwoomApiService.fetchKa10029(
                                StrategyRequests.ExpCntrFluRtUpperRequest.builder()
                                        .mrktTp(mrkt).sortTp("1").trdeQtyCnd("10")
                                        .stkCnd("1").crdCnd("0").pricCnd("8").stexTp("1").build());
                if (gapResp != null && gapResp.getItems() != null) {
                    gapResp.getItems().stream()
                            .filter(item -> {
                                try {
                                    double f = Double.parseDouble(item.getFluRt().replace("+","").replace(",",""));
                                    return f >= 2.0 && f <= 10.0;
                                } catch (Exception ex) { return false; }
                            })
                            .map(KiwoomApiResponses.ExpCntrFluRtUpperResponse.ExpCntrFluRtItem::getStkCd)
                            .forEach(gapSet::add);
                }
            }

            // 사전 필터 2: ka10030 거래대금 10억(1000) 이상 종목
            Set<String> volSet = new java.util.HashSet<>();
            for (String mrkt : new String[]{"001", "101"}) {
                KiwoomApiResponses.TdyTrdeQtyUpperResponse volResp =
                        kiwoomApiService.fetchKa10030(
                                StrategyRequests.TdyTrdeQtyUpperRequest.builder()
                                        .mrktTp(mrkt).sortTp("1").mangStkIncls("1")
                                        .crdTp("0").trdeQtyTp("10").pricTp("8")
                                        .trdePricaTp("0").mrktOpenTp("0").stexTp("1").build());
                if (volResp != null && volResp.getItems() != null) {
                    volResp.getItems().stream()
                            .filter(item -> {
                                try {
                                    double amt = Double.parseDouble(item.getTrdeAmt().replace(",",""));
                                    return amt >= 1000;
                                } catch (Exception ex) { return false; }
                            })
                            .map(KiwoomApiResponses.TdyTrdeQtyUpperResponse.TdyTrdeQtyItem::getStkCd)
                            .forEach(volSet::add);
                }
            }

            // 사전 필터 3: 호가 매수비율 200% 이상
            Set<String> bidSet = bidUpperService.fetchBidUpperCodes();

            // 교집합: gapSet ∩ (volSet ∪ bidSet)
            Set<String> preFiltered = new java.util.HashSet<>(gapSet);
            Set<String> combined = new java.util.HashSet<>(volSet);
            combined.addAll(bidSet);
            preFiltered.retainAll(combined);

            log.info("[S7] 사전 필터 – gap={}건 vol={}건 bid={}건 교집합={}건",
                    gapSet.size(), volSet.size(), bidSet.size(), preFiltered.size());

            int maxSignals = newsControlService.getMaxSignals(5);
            List<TradingSignalDto> kospiSignals  = strategyService.scanAuction("001", preFiltered);
            List<TradingSignalDto> kosdaqSignals = strategyService.scanAuction("101", preFiltered);
            int cnt = signalService.processSignals(
                    kospiSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()))
                    + signalService.processSignals(
                    kosdaqSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            log.info("[S7] 동시호가 신호 발행: {}건 (max={})", cnt, maxSignals);
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
    // 장시작 브리핑 (09:01)
    // ─────────────────────────────────────────────

    /** 09:01 - 장시작 브리핑 자동 알림 */
    @Scheduled(cron = "0 1 9 * * MON-FRI")
    public void marketOpenBrief() {
        log.info("=== 장시작 브리핑 발행 (09:01) ===");
        try {
            List<String> kospi  = candidateService.getCandidates("001");
            List<String> kosdaq = candidateService.getCandidates("101");

            TradingControl control = newsControlService.getTradingControl();
            String sentiment = redis.opsForValue().get("news:market_sentiment");
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
    // 전술 1: 갭상승 시초가 (09:00~09:10, 2분마다)
    // ─────────────────────────────────────────────

    /** 09:00~09:10 매 2분 - 전술 1 갭상승 */
    @Scheduled(cron = "0 0/2 9 * * MON-FRI")
    public void scanGapOpening() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 0)) || now.isAfter(LocalTime.of(9, 10))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S1] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S1] 갭상승 시초가 스캔 (news={})", newsControl);
        try {
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS1Candidates("001").stream(),
                            candidateService.getS1Candidates("101").stream())
                    .distinct().collect(Collectors.toList());
            List<TradingSignalDto> signals = strategyService.scanGapOpening(candidates);
            int maxSignals = newsControlService.getMaxSignals(5);
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            log.info("[S1] 갭상승 신호 발행: {}건 (max={})", cnt, maxSignals);
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

        if (newsControlService.isPaused()) return;
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

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S3] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        int maxSignals = newsControlService.getMaxSignals(5);
        log.info("[S3] 외인+기관 스캔 (news={}, max={})", newsControl, maxSignals);
        try {
            List<TradingSignalDto> kospiSignals  = strategyService.scanInstFrgn("001");
            List<TradingSignalDto> kosdaqSignals = strategyService.scanInstFrgn("101");
            int cnt = signalService.processSignals(
                    kospiSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()))
                    + signalService.processSignals(
                    kosdaqSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S3] 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S3] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 4: 장대양봉 추격 (09:30~14:30, 3분마다)
    // ─────────────────────────────────────────────

    /** 09:30~14:30 매 3분 - 전술 4 장대양봉 스캔 (VolSurge + PriceSurge 사전 필터) */
    @Scheduled(cron = "0 0/3 9-14 * * MON-FRI")
    public void scanBigCandle() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(14, 30))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S4] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S4] 장대양봉 스캔 (사전 필터링 적용, news={})", newsControl);
        try {
            // 사전 필터: 거래량급증 + 가격급등 합집합
            Set<String> volSurge   = volSurgeService.fetchSurgeCandidates();
            Set<String> priceSurge = priceSurgeService.fetchSurgeCandidates();
            Set<String> surgeSet   = new java.util.HashSet<>(volSurge);
            surgeSet.addAll(priceSurge);
            log.info("[S4] 사전 필터 결과 – volSurge={}건 priceSurge={}건 union={}건",
                    volSurge.size(), priceSurge.size(), surgeSet.size());

            // surgeSet 이 비어있으면 전체 후보 기반으로 진행 (필터 API 실패 대비)
            List<String> candidates;
            if (surgeSet.isEmpty()) {
                candidates = candidateService.getAllCandidates().stream()
                        .limit(100).collect(Collectors.toList());
            } else {
                candidates = candidateService.getAllCandidates().stream()
                        .filter(surgeSet::contains)
                        .limit(30)
                        .collect(Collectors.toList());
            }

            int maxSignals = newsControlService.getMaxSignals(5);
            int cnt = 0;
            for (String stkCd : candidates) {
                var sigOpt = strategyService.checkBigCandle(stkCd);
                if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                    cnt++;
                    if (cnt >= maxSignals) break;
                }
            }
            if (cnt > 0) log.info("[S4] 신호 발행: {}건 (max={})", cnt, maxSignals);
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

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S5] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        int maxSignals = newsControlService.getMaxSignals(5);
        log.info("[S5] 프로그램+외인 스캔 (news={}, max={})", newsControl, maxSignals);
        try {
            List<TradingSignalDto> kospiSignals  = strategyService.scanProgramFrgn("001");
            List<TradingSignalDto> kosdaqSignals = strategyService.scanProgramFrgn("101");
            int cnt = signalService.processSignals(
                    kospiSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()))
                    + signalService.processSignals(
                    kosdaqSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
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

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S6] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        int maxSignals = newsControlService.getMaxSignals(5);
        log.info("[S6] 테마 후발주 스캔 (news={}, max={})", newsControl, maxSignals);
        try {
            List<TradingSignalDto> signals = strategyService.scanThemeLaggard();
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S6] 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S6] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 10: 52주 신고가 돌파 (11:00~14:00, 15분마다)
    // ─────────────────────────────────────────────

    /** 11:00~14:00 매 15분 - 전술 10 52주 신고가 돌파 */
    @Scheduled(cron = "0 0/15 11-13 * * MON-FRI")
    public void scanNewHigh() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(11, 0)) || now.isAfter(LocalTime.of(14, 0))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S10] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S10] 52주 신고가 돌파 스캔 (news={})", newsControl);
        try {
            // 52주 신고가 풀 (ka10016) 우선, 없으면 PriceSurge 폴백
            List<String> nhKospi  = candidateService.getS10Candidates("001");
            List<String> nhKosdaq = candidateService.getS10Candidates("101");
            List<String> nhCombined = java.util.stream.Stream.concat(nhKospi.stream(), nhKosdaq.stream())
                    .distinct().collect(java.util.stream.Collectors.toList());
            List<String> candidates;
            if (!nhCombined.isEmpty()) {
                candidates = nhCombined.stream().limit(30).collect(java.util.stream.Collectors.toList());
            } else {
                Set<String> priceSurge = priceSurgeService.fetchSurgeCandidates();
                candidates = !priceSurge.isEmpty()
                        ? new ArrayList<>(priceSurge).stream().limit(20).collect(java.util.stream.Collectors.toList())
                        : candidateService.getAllCandidates().stream().limit(30).collect(java.util.stream.Collectors.toList());
            }

            int maxSignals = newsControlService.getMaxSignals(3);
            int cnt = 0;
            for (String stkCd : candidates) {
                var sigOpt = strategyService.checkNewHigh(stkCd);
                if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                    cnt++;
                    if (cnt >= maxSignals) break;
                }
            }
            if (cnt > 0) log.info("[S10] 52주 신고가 돌파 신호 발행: {}건 (max={})", cnt, maxSignals);
        } catch (Exception e) {
            log.error("[S10] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 8: 골든크로스 스윙 (10:00~14:30, 10분마다)
    // ─────────────────────────────────────────────

    /** 10:00~14:30 매 10분 - 전술 8 5일선 골든크로스 스윙 */
    @Scheduled(cron = "0 0/10 10-14 * * MON-FRI")
    public void scanGoldenCross() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(10, 0)) || now.isAfter(LocalTime.of(14, 30))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S8] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S8] 골든크로스 스캔 (news={})", newsControl);
        try {
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS8Candidates("001").stream(),
                            candidateService.getS8Candidates("101").stream())
                    .distinct().limit(80).collect(java.util.stream.Collectors.toList());
            int maxSignals = newsControlService.getMaxSignals(3);
            List<TradingSignalDto> signals = strategyService.scanGoldenCross(candidates);
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S8] 골든크로스 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S8] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 9: 정배열 눌림목 스윙 (09:30~13:00, 10분마다)
    // ─────────────────────────────────────────────

    /** 09:30~13:00 매 10분 - 전술 9 정배열 눌림목 스윙 */
    @Scheduled(cron = "0 0/10 9-12 * * MON-FRI")
    public void scanPullbackSwing() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(13, 0))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S9] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S9] 정배열 눌림목 스캔 (news={})", newsControl);
        try {
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS9Candidates("001").stream(),
                            candidateService.getS9Candidates("101").stream())
                    .distinct().limit(80).collect(java.util.stream.Collectors.toList());
            int maxSignals = newsControlService.getMaxSignals(3);
            List<TradingSignalDto> signals = strategyService.scanPullbackSwing(candidates);
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S9] 눌림목 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S9] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 11: 외국인 연속 순매수 스윙 (09:30~14:30, 15분마다)
    // ─────────────────────────────────────────────

    /** 09:30~14:30 매 15분 - 전술 11 외국인 연속 순매수 (5일+) 스윙 */
    @Scheduled(cron = "0 0/15 9-14 * * MON-FRI")
    public void scanFrgnCont() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(14, 30))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S11] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        int maxSignals = newsControlService.getMaxSignals(3);
        log.info("[S11] 외국인 연속 순매수 스캔 (news={}, max={})", newsControl, maxSignals);
        try {
            // S11 후보 풀 사전 갱신 – Python 스캐너가 candidates:s11:{market} 를 읽을 수 있도록
            candidateService.getS11Candidates("001");
            candidateService.getS11Candidates("101");
            List<TradingSignalDto> kospiSignals  = strategyService.scanFrgnCont("001");
            List<TradingSignalDto> kosdaqSignals = strategyService.scanFrgnCont("101");
            int cnt = signalService.processSignals(
                    kospiSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()))
                    + signalService.processSignals(
                    kosdaqSignals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S11] 외국인 연속 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S11] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 13: 박스권 돌파 스윙 (09:30~14:00, 15분마다)
    // ─────────────────────────────────────────────

    /** 09:30~14:00 매 15분 - 전술 13 거래량 폭발 박스권 돌파 스윙 */
    @Scheduled(cron = "0 0/15 9-13 * * MON-FRI")
    public void scanBoxBreakout() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(14, 0))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S13] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S13] 박스권 돌파 스캔 (news={})", newsControl);
        try {
            // 스윙+신고가 합산 풀 (S8∪S10, 별도 API 호출 없음)
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS13Candidates("001").stream(),
                            candidateService.getS13Candidates("101").stream())
                    .distinct().limit(60).collect(java.util.stream.Collectors.toList());
            int maxSignals = newsControlService.getMaxSignals(3);
            List<TradingSignalDto> signals = strategyService.scanBoxBreakout(candidates);
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S13] 박스권 돌파 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S13] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 14: 과매도 반등 (09:30~14:00, 15분마다)
    // ─────────────────────────────────────────────

    /** 09:35~14:00 매 15분 - 전술 14 과매도 오실레이터 수렴 반등 */
    @Scheduled(cron = "0 5/15 9-13 * * MON-FRI")
    public void scanOversoldBounce() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(9, 30)) || now.isAfter(LocalTime.of(14, 0))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S14] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S14] 과매도 반등 스캔 (news={})", newsControl);
        try {
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS14Candidates("001").stream(),
                            candidateService.getS14Candidates("101").stream())
                    .distinct().limit(80).collect(java.util.stream.Collectors.toList());
            int maxSignals = newsControlService.getMaxSignals(3);
            List<TradingSignalDto> signals = strategyService.scanOversoldBounce(candidates);
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S14] 과매도 반등 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S14] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 15: 모멘텀 동조 스윙 (10:00~14:30, 15분마다)
    // ─────────────────────────────────────────────

    /** 10:10~14:30 매 15분 - 전술 15 다중지표 모멘텀 동조 스윙 */
    @Scheduled(cron = "0 10/15 10-14 * * MON-FRI")
    public void scanMomentumAlign() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(10, 0)) || now.isAfter(LocalTime.of(14, 30))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S15] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S15] 모멘텀 동조 스캔 (news={})", newsControl);
        try {
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS15Candidates("001").stream(),
                            candidateService.getS15Candidates("101").stream())
                    .distinct().limit(80).collect(java.util.stream.Collectors.toList());
            int maxSignals = newsControlService.getMaxSignals(3);
            List<TradingSignalDto> signals = strategyService.scanMomentumAlign(candidates);
            int cnt = signalService.processSignals(
                    signals.stream().limit(maxSignals).collect(java.util.stream.Collectors.toList()));
            if (cnt > 0) log.info("[S15] 모멘텀 동조 신호 발행: {}건", cnt);
        } catch (Exception e) {
            log.error("[S15] 스케줄 오류: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // 전술 12: 종가 강도 매수 (14:30~15:10, 5분마다)
    // ─────────────────────────────────────────────

    /** 14:30~15:10 매 5분 - 전술 12 종가 강도 매수 */
    @Scheduled(cron = "0 0/5 14 * * MON-FRI")
    public void scanClosingStrength() {
        LocalTime now = LocalTime.now();
        if (now.isBefore(LocalTime.of(14, 30)) || now.isAfter(LocalTime.of(15, 10))) return;

        TradingControl newsControl = newsControlService.getTradingControl();
        if (newsControl == TradingControl.PAUSE) {
            log.warn("[S12] 뉴스 기반 매매 중단 상태 – 스캔 건너뜀");
            return;
        }
        log.info("[S12] 종가강도 스캔 (news={})", newsControl);
        try {
            List<String> candidates = java.util.stream.Stream.concat(
                            candidateService.getS12Candidates("001").stream(),
                            candidateService.getS12Candidates("101").stream())
                    .distinct().collect(java.util.stream.Collectors.toList());
            int maxSignals = newsControlService.getMaxSignals(5);
            int cnt = 0;
            for (String stkCd : candidates) {
                var sigOpt = strategyService.checkClosingStrength(stkCd);
                if (sigOpt.isPresent() && signalService.processSignal(sigOpt.get())) {
                    cnt++;
                    if (cnt >= maxSignals) break;
                }
            }
            if (cnt > 0) log.info("[S12] 종가강도 신호 발행: {}건 (max={})", cnt, maxSignals);
        } catch (Exception e) {
            log.error("[S12] 스케줄 오류: {}", e.getMessage());
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

    // ─────────────────────────────────────────────
    // 장전 뉴스 브리핑 (08:30)
    // ─────────────────────────────────────────────

    /** 08:30 - 장전 뉴스 분석 결과 브리핑 발행 */
    @Scheduled(cron = "0 30 8 * * MON-FRI")
    public void preMarketNewsBrief() {
        log.info("=== 장전 뉴스 브리핑 발행 (08:30) ===");
        try {
            String control   = redis.opsForValue().get("news:trading_control");
            String sentiment = redis.opsForValue().get("news:market_sentiment");
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
        } catch (Exception e) {
            log.error("[PreMarketBrief] 장전 뉴스 브리핑 실패: {}", e.getMessage());
        }
    }

    // ─────────────────────────────────────────────
    // Phase 3-A: 장전 전일종가 사전 저장 (08:00)
    // ─────────────────────────────────────────────

    /** 08:00 – 후보 종목 전일종가 일괄 수집 후 Redis 저장 */
    @Scheduled(cron = "0 0 8 * * MON-FRI")
    public void preparePreOpenData() {
        log.info("=== 장전 전일종가 사전 저장 시작 (08:00) ===");
        try {
            List<String> candidates = candidateService.getAllCandidates();
            log.info("[PreOpen] 후보 종목 {}개에 대해 전일종가 수집 시작", candidates.size());

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

    // ─────────────────────────────────────────────
    // 오전 중간 보고 (12:30)
    // ─────────────────────────────────────────────

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

            // TOP 신호 – 오늘 신호 중 스코어 상위 2건
            List<org.invest.apiorchestrator.domain.TradingSignal> todaySignals = signalService.getTodaySignals();
            List<String> topLines = todaySignals.stream()
                    .filter(s -> s.getSignalScore() != null)
                    .sorted((a, b) -> Double.compare(
                            b.getSignalScore() != null ? b.getSignalScore() : 0,
                            a.getSignalScore()))
                    .limit(2)
                    .map(s -> String.format("  %s [%s] %.0f점", s.getStkNm() != null ? s.getStkNm() : s.getStkCd(), s.getStrategy(), s.getSignalScore()))
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

            // 섹터별 신호 집계 – 오늘 신호에서 테마명 기반
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

    // ─────────────────────────────────────────────
    // Phase 4-A: 일별 성과 집계 (15:35)
    // ─────────────────────────────────────────────

    /** 15:35 – 당일 신호 통계 집계 후 Redis + telegram_queue 발행 */
    @Scheduled(cron = "0 35 15 * * MON-FRI")
    public void compileDailySummary() {
        log.info("=== 일별 성과 집계 시작 (15:35) ===");
        try {
            java.time.LocalDateTime startOfDay = java.time.LocalDate.now().atStartOfDay();
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

            String today = java.time.LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd"));
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

            // 가상 P&L 성과 데이터 (Feature 1)
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

            // telegram_queue 에 일일 리포트 메시지 발행
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

            log.info("[DailySummary] 집계 완료 – totalSignals={} avgScore={} wins={} losses={} avgPnl={}",
                    totalSignals, String.format("%.1f", avgScore), totalWins, totalLosses, String.format("%.2f", avgPnl));
        } catch (Exception e) {
            log.error("[DailySummary] 집계 실패: {}", e.getMessage());
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
                    .collect(java.util.stream.Collectors.joining(" / "));
        } catch (Exception e) {
            return "";
        }
    }

    // 틱 데이터 정리는 DataCleanupScheduler (23:30) 에서 전담 처리
}
