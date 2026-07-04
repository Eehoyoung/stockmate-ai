package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.strategy.S10NewHighEvaluator;
import org.invest.apiorchestrator.service.strategy.S2ViPullbackEvaluator;
import org.invest.apiorchestrator.service.strategy.S4BigCandleEvaluator;
import org.invest.apiorchestrator.service.strategy.S12ClosingStrengthEvaluator;
import org.invest.apiorchestrator.service.strategy.StrategyScanContext;
import org.invest.apiorchestrator.service.strategy.StrategyScannerRegistry;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import org.invest.apiorchestrator.util.KstClock;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class StrategyService {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;
    private final StockMasterRepository stockMasterRepository;
    private final KiwoomApiService kiwoomApiService;
    private final StrategyScannerRegistry strategyScannerRegistry;
    private final S2ViPullbackEvaluator s2ViPullbackEvaluator;
    private final S4BigCandleEvaluator s4BigCandleEvaluator;
    private final S10NewHighEvaluator s10NewHighEvaluator;
    private final S12ClosingStrengthEvaluator s12ClosingStrengthEvaluator;

    // ─────────────────────────────────────────────────────────────
    // 전술 1: 갭상승 + 체결강도 시초가 매수  (8:30~9:05)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanGapOpening(List<String> candidates) {
        var scanner = strategyScannerRegistry.find(TradingSignal.StrategyType.S1_GAP_OPEN);
        if (scanner.isPresent()) {
            return scanner.get().scan(StrategyScanContext.candidates(candidates));
        }
        MDC.put("strategy", "S1_GAP_OPEN");
        log.info("[S1] 갭상승 시초가 스캔 시작 - 후보 {}개", candidates.size());
        List<TradingSignalDto> results = new ArrayList<>();

        for (String stkCd : candidates) {
            try {
                // Redis 예상체결 데이터 (장 개시 후 만료 시 tick 데이터로 fallback)
                double prevClose, expPrice;
                var expOpt = redisService.getExpectedData(stkCd);
                if (expOpt.isPresent()) {
                    Map<Object, Object> exp = expOpt.get();
                    prevClose = parseDouble(exp, "pred_pre_pric");
                    expPrice  = parseDouble(exp, "exp_cntr_pric");
                } else {
                    var tickFb = redisService.getTickData(stkCd);
                    if (tickFb.isEmpty()) continue;
                    Map<Object, Object> tick = tickFb.get();
                    prevClose = parseDouble(tick, "pred_pre");
                    expPrice  = parseDouble(tick, "cur_prc");
                }
                if (prevClose <= 0 || expPrice <= 0) continue;

                double gapPct = (expPrice - prevClose) / prevClose * 100;
                if (gapPct < 3.0 || gapPct > 15.0) continue; // 3~15% 갭

                // 체결강도 (Redis 최근 5개 평균) – 데이터 없으면 조건 생략(장 초반 대응)
                double strength = redisService.getAvgCntrStrength(stkCd, 5);
                if (redisService.hasStrengthData(stkCd) && strength < 130.0) continue;

                // 호가잔량 비율
                double bidRatio = 0;
                var hogaOpt = redisService.getHogaData(stkCd);
                if (hogaOpt.isPresent()) {
                    double bid = parseDouble(hogaOpt.get(), "total_buy_bid_req");
                    double ask = parseDouble(hogaOpt.get(), "total_sel_bid_req");
                    bidRatio = ask > 0 ? bid / ask : 0;
                }
                if (bidRatio < 1.3) continue;

                double score = gapPct * 0.5 + (strength - 100) * 0.3 + bidRatio * 0.2;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(resolveStkNm(stkCd))
                        .strategy(TradingSignal.StrategyType.S1_GAP_OPEN)
                        .signalScore(round(score))
                        .entryPrice(expPrice)
                        .gapPct(round(gapPct))
                        .cntrStrength(round(strength))
                        .bidRatio(round(bidRatio))
                        .entryType("시초가_시장가")
                        .targetPct(5.0).target2Pct(9.0).stopPct(-2.0)
                        .tp1Price(round(expPrice * 1.05))
                        .tp2Price(round(expPrice * 1.09))
                        .slPrice(round(expPrice * 0.98))
                        .build());

            } catch (Exception e) {
                log.warn("[S1] {} 처리 오류: {}", stkCd, e.getMessage());
            }
        }

        MDC.remove("strategy");
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5).collect(Collectors.toList());
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 2: VI 발동 후 눌림목 재진입  (실시간 이벤트 기반)
    // ─────────────────────────────────────────────────────────────
    public Optional<TradingSignalDto> checkViPullback(String stkCd, double viPrice,
                                                      boolean isDynamic) {
        Optional<TradingSignalDto> evaluated = s2ViPullbackEvaluator.evaluate(stkCd, viPrice, isDynamic);
        if (evaluated.isPresent()) {
            return evaluated;
        }
        try {
            var tickOpt = redisService.getTickData(stkCd);
            if (tickOpt.isEmpty()) return Optional.empty();

            double curPrice = parseDouble(tickOpt.get(), "cur_prc");
            if (curPrice <= 0 || viPrice <= 0) return Optional.empty();

            double pullbackPct = (curPrice - viPrice) / viPrice * 100;
            // 눌림 범위 -1% ~ -3%
            if (pullbackPct < -3.0 || pullbackPct > -1.0) return Optional.empty();

            double strength = redisService.getAvgCntrStrength(stkCd, 3);
            if (strength < 110.0) return Optional.empty();

            var hogaOpt = redisService.getHogaData(stkCd);
            if (hogaOpt.isEmpty()) return Optional.empty();
            double bid = parseDouble(hogaOpt.get(), "total_buy_bid_req");
            double ask = parseDouble(hogaOpt.get(), "total_sel_bid_req");
            double bidRatio = ask > 0 ? bid / ask : 0;
            if (bidRatio < 1.3) return Optional.empty();

            double score = Math.abs(pullbackPct) * 10 + (strength - 100) * 0.3
                    + bidRatio * 5 + (isDynamic ? 10 : 0);

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S2_VI_PULLBACK)
                    .signalScore(round(score))
                    .entryPrice(curPrice)
                    .pullbackPct(round(pullbackPct))
                    .cntrStrength(round(strength))
                    .bidRatio(round(bidRatio))
                    .entryType("지정가_눌림목")
                    .targetPct(6.5).target2Pct(9.5).stopPct(-2.0)
                    .tp1Price(round(curPrice * 1.065))
                    .tp2Price(round(curPrice * 1.095))
                    .slPrice(round(curPrice * 0.98))
                    .build());
        } catch (Exception e) {
            log.warn("[S2] {} 처리 오류: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 3: 외인 + 기관 동시 순매수 돌파  (9:30~)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanInstFrgn(String market) {
        var scanner = strategyScannerRegistry.find(TradingSignal.StrategyType.S3_INST_FRGN);
        if (scanner.isPresent()) {
            return scanner.get().scan(StrategyScanContext.market(market));
        }
        log.info("[S3] 외인+기관 동시 순매수 스캔 [{}]", market);
        try {
            // 장중 투자자별 매매 (동시순매수)
            var intradayResp = apiService.post(
                    "ka10063", "/api/dostk/mrkcond",
                    StrategyRequests.IntradayInvestorRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.IntradayInvestorResponse.class);

            if (intradayResp.getItems() == null) return Collections.emptyList();

            // 기관외국인 연속 순매수 3일
            var contResp = apiService.post(
                    "ka10131", "/api/dostk/frgnistt",
                    StrategyRequests.InstFrgnContinuousRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.InstFrgnContinuousResponse.class);

            // ka10131 응답에서 종목코드 → 실제 연속일수 매핑 (cont_dt_cnt 필드)
            Map<String, Integer> contMap = contResp.getItems() == null ? Collections.emptyMap()
                    : contResp.getItems().stream()
                    .filter(c -> c.getStkCd() != null)
                    .collect(Collectors.toMap(
                            KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem::getStkCd,
                            c -> { int d = parseInt(c.getContDtCnt()); return d > 0 ? d : 1; },
                            (a, b) -> a  // 중복 키 시 첫 번째 값 사용
                    ));

            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : intradayResp.getItems()) {
                String stkCd = item.getStkCd();
                if (!contMap.containsKey(stkCd)) continue;
                int actualDays = contMap.get(stkCd);

                // 거래량 비율 (Redis 당일 vs 전일)
                double volRatio = calcVolRatio(stkCd);
                if (volRatio < 1.5) continue;

                long netBuyAmt = parseLong(item.getNetBuyAmt());
                double score = netBuyAmt / 1_000_000.0 + volRatio * 5;

                var tickS3 = redisService.getTickData(stkCd);
                double curPriceS3 = tickS3.isPresent() ? parseDouble(tickS3.get(), "cur_prc") : 0.0;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S3_INST_FRGN)
                        .signalScore(round(score))
                        .netBuyAmt(netBuyAmt)
                        .volRatio(round(volRatio))
                        .continuousDays(actualDays)
                        .marketType(market)
                        .entryType("지정가_1호가")
                        .targetPct(3.5)
                        .target2Pct(5.0)
                        .stopPct(-2.0)
                        .tp1Price(curPriceS3 > 0 ? round(curPriceS3 * 1.06) : null)
                        .tp2Price(curPriceS3 > 0 ? round(curPriceS3 * 1.10) : null)
                        .slPrice(curPriceS3 > 0 ? round(curPriceS3 * 0.97) : null)
                        .build());
            }
            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5).collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S3] 스캔 오류: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 4: 장대양봉 + 거래량 급증 추격매수  (장중)
    // ─────────────────────────────────────────────────────────────
    public Optional<TradingSignalDto> checkBigCandle(String stkCd) {
        Optional<TradingSignalDto> evaluated = s4BigCandleEvaluator.evaluate(stkCd);
        if (evaluated.isPresent()) {
            return evaluated;
        }
        try {
            var resp = apiService.post(
                    "ka10080", "/api/dostk/chart",
                    StrategyRequests.MinuteCandleRequest.builder().stkCd(stkCd).ticScope("5").baseDt(KstClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"))).build(),
                    KiwoomApiResponses.MinuteCandleResponse.class);

            if (resp.getCandles() == null || resp.getCandles().size() < 10)
                return Optional.empty();

            var candles = resp.getCandles();
            var cur = candles.get(0);

            double o = parseDoubleStr(cur.getOpenPric());
            double h = parseDoubleStr(cur.getHighPric());
            double l = parseDoubleStr(cur.getLowPric());
            double c = parseDoubleStr(cur.getCurPrc());
            long   vol = parseLongStr(cur.getTrdeQty());

            if (o <= 0 || h <= l) return Optional.empty();
            if (c <= o) return Optional.empty(); // 음봉 제외

            double candleRange = h - l;
            double body        = c - o;
            double bodyRatio   = candleRange > 0 ? body / candleRange : 0;
            double gainPct     = (c - o) / o * 100;

            if (bodyRatio < 0.7 || gainPct < 3.0) return Optional.empty();

            // 직전 5봉 평균 거래량 대비
            double avgPrevVol = candles.subList(1, Math.min(6, candles.size())).stream()
                    .mapToLong(can -> parseLongStr(can.getTrdeQty()))
                    .average().orElse(0);
            double volRatio = avgPrevVol > 0 ? vol / avgPrevVol : 0;
            if (volRatio < 5.0) return Optional.empty();

            // 체결강도 – 데이터 있을 때만 필터(장 초반 미수신 대응), 임계값 120으로 완화
            double strength = redisService.getAvgCntrStrength(stkCd, 3);
            if (redisService.hasStrengthData(stkCd) && strength < 120.0) return Optional.empty();

            // 20일 고가 대비 신고가 여부 (96봉 = 8시간 5분봉)
            double max20d = candles.subList(1, Math.min(97, candles.size())).stream()
                    .mapToDouble(can -> parseDoubleStr(can.getHighPric()))
                    .max().orElse(0);
            boolean isNewHigh = h >= max20d;

            double score = gainPct * 3 + bodyRatio * 10 + volRatio * 0.5
                    + (strength - 100) * 0.2 + (isNewHigh ? 20 : 0);

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S4_BIG_CANDLE)
                    .signalScore(round(score))
                    .entryPrice(c)
                    .gapPct(round(gainPct))
                    .volRatio(round(volRatio))
                    .cntrStrength(round(strength))
                    .bodyRatio(round(bodyRatio))
                    .isNewHigh(isNewHigh)
                    .entryType("추격_시장가")
                    .targetPct(6.0).target2Pct(9.0).stopPct(-3.0)
                    .tp1Price(round(c * 1.06))
                    .tp2Price(round(c * 1.09))
                    .slPrice(l > 0 ? round(Math.max(l * 0.99, c * 0.97)) : round(c * 0.97))  // 저가 하방, 최대 -3% 캡
                    .build());
        } catch (Exception e) {
            log.warn("[S4] {} 처리 오류: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 5: 프로그램 순매수 + 외인 동반 상위  (10:00~14:00)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanProgramFrgn(String market) {
        var scanner = strategyScannerRegistry.find(TradingSignal.StrategyType.S5_PROG_FRGN);
        if (scanner.isPresent()) {
            return scanner.get().scan(StrategyScanContext.market(market));
        }
        log.info("[S5] 프로그램+외인 스캔 [{}]", market);
        try {
            var progResp = apiService.post(
                    "ka90003", "/api/dostk/stkinfo",
                    StrategyRequests.ProgramNetBuyRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.ProgramNetBuyResponse.class);

            var frgnResp = apiService.post(
                    "ka90009", "/api/dostk/rkinfo",
                    StrategyRequests.FrgnInstUpperRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.FrgnInstUpperResponse.class);

            if (progResp.getItems() == null || frgnResp.getItems() == null)
                return Collections.emptyList();

            Set<String> frgnSet = frgnResp.getItems().stream()
                    .map(KiwoomApiResponses.FrgnInstUpperResponse.FrgnInstItem::getStkCd)
                    .collect(Collectors.toSet());

            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : progResp.getItems()) {
                String stkCd = item.getStkCd();
                if (!frgnSet.contains(stkCd)) continue;

                long netBuyAmt = parseLong(item.getNetBuyAmt());
                double score = netBuyAmt / 1_000_000.0;

                var tickS5 = redisService.getTickData(stkCd);
                double curPriceS5 = tickS5.isPresent() ? parseDouble(tickS5.get(), "cur_prc") : 0.0;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S5_PROG_FRGN)
                        .signalScore(round(score))
                        .netBuyAmt(netBuyAmt)
                        .marketType(market)
                        .entryType("지정가_1호가")
                        .targetPct(6.0)
                        .target2Pct(9.0)
                        .stopPct(-3.0)
                        .tp1Price(curPriceS5 > 0 ? round(curPriceS5 * 1.06) : null)
                        .tp2Price(curPriceS5 > 0 ? round(curPriceS5 * 1.09) : null)
                        .slPrice(curPriceS5 > 0 ? round(curPriceS5 * 0.97) : null)
                        .build());
            }
            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5).collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S5] 스캔 오류: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 6: 테마 상위 + 후발주 (9:30~13:00)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanThemeLaggard() {
        var scanner = strategyScannerRegistry.find(TradingSignal.StrategyType.S6_THEME_LAGGARD);
        if (scanner.isPresent()) {
            return scanner.get().scan(StrategyScanContext.market(""));
        }
        log.info("[S6] 테마 후발주 스캔");
        List<TradingSignalDto> results = new ArrayList<>();
        try {
            var themeResp = apiService.post(
                    "ka90001", "/api/dostk/thme",
                    StrategyRequests.ThemeGroupRequest.builder().build(),
                    KiwoomApiResponses.ThemeGroupResponse.class);

            if (themeResp.getItems() == null) return Collections.emptyList();

            // 상위 5 테마만 처리
            List<KiwoomApiResponses.ThemeGroupResponse.ThemeGroupItem> topThemes = themeResp.getItems()
                    .stream().limit(5).collect(Collectors.toList());

            for (var theme : topThemes) {
                double themeFluRt = parseDoubleStr(theme.getFluRt());
                if (themeFluRt < 2.0) continue;

                var stockResp = apiService.post(
                        "ka90002", "/api/dostk/thme",
                        StrategyRequests.ThemeStockRequest.builder().themaGrpCd(theme.getThemaGrpCd()).build(),
                        KiwoomApiResponses.ThemeStockResponse.class);

                if (stockResp.getItems() == null) continue;

                List<Double> fluRates = stockResp.getItems().stream()
                        .map(s -> parseDoubleStr(s.getFluRt()))
                        .collect(Collectors.toList());

                if (fluRates.isEmpty()) continue;
                fluRates.sort(Double::compareTo);
                double p70 = fluRates.get((int)(fluRates.size() * 0.7));

                for (var stk : stockResp.getItems()) {
                    double stkFluRt = parseDoubleStr(stk.getFluRt());
                    // 후발주 조건: 상승 중이나 상위 30%는 아님
                    if (stkFluRt < 0.5 || stkFluRt >= p70 || stkFluRt >= 5.0) continue;

                    // 테마 종목은 WS 구독 외 종목 포함 가능 → 데이터 있을 때만 필터
                    double strength = redisService.getAvgCntrStrength(stk.getStkCd(), 3);
                    if (redisService.hasStrengthData(stk.getStkCd()) && strength < 120.0) continue;

                    double score = strength * 0.3 + (themeFluRt - stkFluRt) * 2;
                    double target = Math.min(themeFluRt * 0.6, 5.0);

                    var tickS6 = redisService.getTickData(stk.getStkCd());
                    double curPriceS6 = tickS6.isPresent() ? parseDouble(tickS6.get(), "cur_prc") : 0.0;
                    double t1Pct = Math.max(Math.min(themeFluRt * 0.5, 8.0), 6.0);  // floor 6% for R:R ≥ 1.3 (KOSDAQ)
                    double t2Pct = Math.max(Math.min(themeFluRt * 0.7, 11.0), 9.0);

                    results.add(TradingSignalDto.builder()
                            .stkCd(stk.getStkCd())
                            .stkNm(stk.getStkNm())
                            .strategy(TradingSignal.StrategyType.S6_THEME_LAGGARD)
                            .signalScore(round(score))
                            .themeName(theme.getThemaNm())
                            .gapPct(round(stkFluRt))
                            .cntrStrength(round(strength))
                            .entryType("지정가_1호가")
                            .targetPct(round(target))
                            .target2Pct(round(target * 1.5))
                            .stopPct(-2.0)
                            .tp1Price(curPriceS6 > 0 ? round(curPriceS6 * (1.0 + t1Pct / 100.0)) : null)
                            .tp2Price(curPriceS6 > 0 ? round(curPriceS6 * (1.0 + t2Pct / 100.0)) : null)
                            .slPrice(curPriceS6 > 0 ? round(curPriceS6 * 0.97) : null)
                            .build());
                }
            }
        } catch (Exception e) {
            log.error("[S6] 스캔 오류: {}", e.getMessage());
        }
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5).collect(Collectors.toList());
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 7: 장전 예상체결 + 호가잔량  (8:30~9:00)
    // ─────────────────────────────────────────────────────────────
    @Deprecated
    public List<TradingSignalDto> scanAuction(String market) {
        return scanAuction(market, Collections.emptySet());
    }

    /**
     * Deprecated.
     * S7은 더 이상 동시호가 스캔이 아니며 Python ai-engine의
     * `strategy_7_ichimoku_breakout.py`에서만 장중 실행된다.
     */
    @Deprecated
    public List<TradingSignalDto> scanAuction(String market, Set<String> preFiltered) {
        var scanner = strategyScannerRegistry.find(TradingSignal.StrategyType.S7_ICHIMOKU_BREAKOUT);
        if (scanner.isPresent()) {
            return scanner.get().scan(StrategyScanContext.market(market, preFiltered));
        }
        log.warn("[S7] legacy auction scan requested for market={} preFiltered={}건; returning empty list",
                market, preFiltered.size());
        return Collections.emptyList();
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 10: 52주 신고가 돌파  (11:00~14:00, 15분마다)
    // ─────────────────────────────────────────────────────────────

    /**
     * 당일 고가가 52주(약 250 거래일) 신고가를 돌파했는지 확인.
     * ka10081 일봉차트를 활용하며, 거래량·등락률·체결강도 복합 조건 적용.
     */
    public Optional<TradingSignalDto> checkNewHigh(String stkCd) {
        Optional<TradingSignalDto> evaluated = s10NewHighEvaluator.evaluate(stkCd);
        if (evaluated.isPresent()) {
            return evaluated;
        }
        try {
            var resp = apiService.fetchKa10081(stkCd);
            if (resp.getCandles() == null || resp.getCandles().size() < 20) return Optional.empty();

            var candles = resp.getCandles();
            var today   = candles.get(0);

            double todayHigh  = parseDoubleStr(today.getHighPric());
            double todayClose = parseDoubleStr(today.getCurPrc());
            double todayOpen  = parseDoubleStr(today.getOpenPric());
            long   todayVol   = parseLongStr(today.getTrdeQty());

            if (todayHigh <= 0 || todayClose <= 0 || todayOpen <= 0) return Optional.empty();
            if (todayClose <= todayOpen) return Optional.empty(); // 음봉 제외

            // 52주 최고가 (전일까지)
            int historyDays = Math.min(250, candles.size() - 1);
            double yearHigh = candles.subList(1, historyDays + 1).stream()
                    .mapToDouble(c -> parseDoubleStr(c.getHighPric()))
                    .max().orElse(0);
            if (yearHigh <= 0) return Optional.empty();

            // 신고가 돌파 조건 (0.1% 이내 근접도 허용)
            if (todayHigh < yearHigh * 0.999) return Optional.empty();

            // 등락률 0.5~15%
            double prevClose = parseDoubleStr(candles.get(1).getCurPrc());
            if (prevClose <= 0) return Optional.empty();
            double fluRt = (todayClose - prevClose) / prevClose * 100;
            if (fluRt < 0.5 || fluRt > 15.0) return Optional.empty();

            // 최근 20일 평균 거래량 대비 1.5배 이상
            double avgVol = candles.subList(1, Math.min(21, candles.size())).stream()
                    .mapToLong(c -> parseLongStr(c.getTrdeQty()))
                    .average().orElse(1);
            double volRatio = avgVol > 0 ? (double) todayVol / avgVol : 0;
            if (volRatio < 1.5) return Optional.empty();

            // MA20 과도 이격 검사 – 25% 이상 이격은 버블권 진입 위험
            if (candles.size() >= 21) {
                double ma20 = candles.subList(0, 20).stream()
                        .mapToDouble(c -> parseDoubleStr(c.getCurPrc()))
                        .filter(p -> p > 0)
                        .average().orElse(0);
                if (ma20 > 0 && todayClose > ma20 * 1.25) {
                    log.debug("[S10] {} MA20 과도 이격 {:.1f}%, skip", stkCd,
                            (todayClose / ma20 - 1) * 100);
                    return Optional.empty();
                }
            }

            double strength = redisService.getAvgCntrStrength(stkCd, 5);
            // 거래량 급증률 % 환산 (scorer.py vol_surge_rt 필드와 통일): 2.0x → 100%
            double volSurgePct = Math.max(0.0, (volRatio - 1.0) * 100.0);

            double score = fluRt * 2 + volRatio * 3
                    + (strength > 100 ? (strength - 100) * 0.2 : 0)
                    + (todayHigh >= yearHigh ? 20 : 10);

            // 기술적 TP/SL: 신고가 돌파 후 추세 지속 기준
            // SL: 52주 고가(이전 저항 → 돌파 후 지지) 하방 1%
            double slS10  = round(yearHigh * 0.99);
            double tp1S10 = round(todayClose * 1.08);   // 8% 1차 목표
            double tp2S10 = round(todayClose * 1.15);   // 15% 2차 목표
            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S10_NEW_HIGH)
                    .signalScore(round(score))
                    .entryPrice(todayClose)
                    .gapPct(round(fluRt))
                    .volRatio(round(volRatio))
                    .volSurgeRt(round(volSurgePct))
                    .cntrStrength(round(strength))
                    .isNewHigh(true)
                    .entryType("당일종가_또는_익일시가")
                    .targetPct(8.0).target2Pct(15.0)
                    .stopPct(round((slS10 - todayClose) / todayClose * 100))
                    .tp1Price(tp1S10)
                    .tp2Price(tp2S10)
                    .slPrice(slS10)
                    .build());
        } catch (Exception e) {
            log.warn("[S10] {} 처리 오류: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 12: 종가 강도 매수  (14:30~15:10, 5분마다)
    // ─────────────────────────────────────────────────────────────

    /**
     * 장마감 전 실시간 틱 데이터 기반 종가 강도 전략.
     * 등락률·체결강도·호가비율 복합 조건으로 익일 갭상승 가능 종목 포착.
     */
    public Optional<TradingSignalDto> checkClosingStrength(String stkCd) {
        Optional<TradingSignalDto> evaluated = s12ClosingStrengthEvaluator.evaluate(stkCd);
        if (evaluated.isPresent()) {
            return evaluated;
        }
        try {
            var tickOpt = redisService.getTickData(stkCd);
            if (tickOpt.isEmpty()) return Optional.empty();
            Map<Object, Object> tick = tickOpt.get();

            double fluRt  = parseDouble(tick, "flu_rt");
            double curPrc = parseDouble(tick, "cur_prc");
            if (curPrc <= 0) return Optional.empty();

            // 등락률 4~15% (ka10027 스펙: 충분한 장중 모멘텀, 과열 제외)
            if (fluRt < 4.0 || fluRt > 15.0) return Optional.empty();

            // 체결강도 110 이상 (ka10027 스펙 기준)
            double strength = redisService.getAvgCntrStrength(stkCd, 5);
            if (strength < 110.0) return Optional.empty();

            // 호가 매수 우위 (bid/ask > 1.5)
            var hogaOpt = redisService.getHogaData(stkCd);
            if (hogaOpt.isEmpty()) return Optional.empty();
            double bid      = parseDouble(hogaOpt.get(), "total_buy_bid_req");
            double ask      = parseDouble(hogaOpt.get(), "total_sel_bid_req");
            double bidRatio = ask > 0 ? bid / ask : 0;
            if (bidRatio < 1.5) return Optional.empty();

            double score = fluRt * 3 + (strength - 100) * 0.3 + bidRatio * 5;

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .stkNm(resolveStkNm(stkCd))
                    .strategy(TradingSignal.StrategyType.S12_CLOSING)
                    .signalScore(round(score))
                    .entryPrice(curPrc)
                    .gapPct(round(fluRt))
                    .cntrStrength(round(strength))
                    .bidRatio(round(bidRatio))
                    .entryType("종가_동시호가")
                    .targetPct(6.0).target2Pct(10.0).stopPct(-3.0)
                    .tp1Price(round(curPrc * 1.06))
                    .tp2Price(round(curPrc * 1.10))
                    .slPrice(round(curPrc * 0.97))
                    .build());
        } catch (Exception e) {
            log.warn("[S12] {} 처리 오류: {}", stkCd, e.getMessage());
            return Optional.empty();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 8: 5일선 골든크로스 스윙  (10:00~14:30)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanGoldenCross(List<String> candidates) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S8_GOLDEN_CROSS)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 9: 정배열 눌림목 지지 반등 스윙  (09:30~13:00)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanPullbackSwing(List<String> candidates) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S9_PULLBACK_SWING)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 11: 외국인 연속 순매수 스윙 (5일+)  (09:30~14:30)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanFrgnCont(String market) {
        var scanner = strategyScannerRegistry.find(TradingSignal.StrategyType.S11_FRGN_CONT);
        if (scanner.isPresent()) {
            return scanner.get().scan(StrategyScanContext.market(market));
        }
        log.info("[S11] 외국인 연속 순매수 스캔 [{}]", market);
        try {
            var contResp = apiService.fetchKa10035(
                    StrategyRequests.FrgnContNettrdRequest.builder()
                            .mrktTp(market)
                            .trdeTp("2")      // 연속순매수
                            .baseDtTp("0")    // 당일기준
                            .build());
            if (contResp == null || contResp.getItems() == null) return Collections.emptyList();

            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : contResp.getItems()) {
                String stkCd = item.getStkCd();
                // dm1/dm2/dm3 모두 양수여야 연속 매수 (음수면 순매도)
                double dm1 = parseDoubleSign(item.getDm1());
                double dm2 = parseDoubleSign(item.getDm2());
                double dm3 = parseDoubleSign(item.getDm3());
                if (dm1 <= 0 || dm2 <= 0 || dm3 <= 0) continue;

                double tot = parseDoubleSign(item.getTot());
                // 외인 한도소진율 보너스 (높을수록 외인 수급 강함)
                double limitExhRt = parseDouble(item.getLimitExhRt());

                double volRatio = calcVolRatio(stkCd);
                double cntrStr  = redisService.getAvgCntrStrength(stkCd, 5);

                // 3일 연속 매수 확인 + 총 순매수 비중 + 한도소진율 보너스
                double score = 15.0                              // 3일 연속 기본
                        + Math.min(tot / 100_000.0, 20.0)       // 총 순매수 비중 (최대 20점)
                        + limitExhRt * 0.5                       // 한도소진율 (최대 ~25점)
                        + volRatio * 3.0
                        + Math.max(cntrStr - 100, 0) * 0.2;

                var tickS11 = redisService.getTickData(stkCd);
                double curPriceS11 = tickS11.isPresent() ? parseDouble(tickS11.get(), "cur_prc") : 0.0;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S11_FRGN_CONT)
                        .signalScore(round(score))
                        .continuousDays(3)
                        .volRatio(round(volRatio))
                        .cntrStrength(round(cntrStr))
                        .marketType(market)
                        .entryType("지정가_1호가")
                        .holdingDays("5~10거래일")
                        .targetPct(9.0).target2Pct(14.0)
                        .stopPct(-5.0)
                        .tp1Price(curPriceS11 > 0 ? round(curPriceS11 * 1.09) : null)
                        .tp2Price(curPriceS11 > 0 ? round(curPriceS11 * 1.14) : null)
                        .slPrice(curPriceS11 > 0 ? round(curPriceS11 * 0.95) : null)
                        .build());
            }
            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5).collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S11] 스캔 오류: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 13: 거래량 폭발 박스권 돌파 스윙  (09:30~14:00)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanBoxBreakout(List<String> candidates) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S13_BOX_BREAKOUT)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 14: 과매도 오실레이터 수렴 반등  (09:30~14:00)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanOversoldBounce(List<String> candidates) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    // ─────────────────────────────────────────────────────────────
    // 전술 15: 다중지표 모멘텀 동조 스윙  (10:00~14:30)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanMomentumAlign(List<String> candidates) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S15_MOMENTUM_ALIGN)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    public List<TradingSignalDto> scanAccumulationShadow(List<String> candidates) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    // ─────────────────────────────────────────────────────────────
    // 유틸
    // ─────────────────────────────────────────────────────────────
    /** Redis ws:tick → StockMaster DB 순으로 종목명 조회 (없으면 빈 문자열 반환) */
    private String resolveStkNm(String stkCd) {
        try {
            var tickOpt = redisService.getTickData(stkCd);
            if (tickOpt.isPresent()) {
                Object nm = tickOpt.get().get("stk_nm");
                if(nm != null || !nm.toString().isEmpty()) {
                    nm = nm.toString().trim();
                }else {
                    nm = kiwoomApiService.fetchKa10001(stkCd).getStkNm().trim();
                }
                return nm.toString().trim();
            }
        } catch (Exception ignored) {}
        try {
            return stockMasterRepository.findByStkCd(stkCd)
                    .map(m -> m.getStkNm() != null ? m.getStkNm().trim() : "")
                    .orElse("");
        } catch (Exception ignored) {}
        return "";
    }

    private double calcVolRatio(String stkCd) {
        // Redis tick 데이터에서 당일 누적거래량 비율 조회
        // ws:tick 해시에 vol_ratio 필드가 없으면 조건 통과(1.5)로 처리하여
        // 거래량 데이터 미수신 시에도 S3 후보 제외가 일어나지 않도록 함
        var tickOpt = redisService.getTickData(stkCd);
        if (tickOpt.isEmpty()) return 1.5;  // 데이터 없으면 통과로 처리
        double cached = parseDouble(tickOpt.get(), "vol_ratio");
        return cached > 0 ? cached : 1.5;   // 0이면 필드 미존재 → 통과로 처리
    }

    private double parseDouble(Map<Object, Object> map, String key) {
        try { return Double.parseDouble(map.getOrDefault(key, "0").toString()
                .replace(",", "").replace("+", "")); }
        catch (Exception e) { return 0; }
    }
    private double parseDoubleStr(String v) {
        try { return v == null ? 0 : Double.parseDouble(v.replace(",","").replace("+","")); }
        catch (Exception e) { return 0; }
    }
    /** +/- 부호 보존 파싱 (순매수/매도 구분용) */
    private double parseDoubleSign(String v) {
        try { return v == null ? 0 : Double.parseDouble(v.replace(",","")); }
        catch (Exception e) { return 0; }
    }
    private double parseDouble(String v) { return parseDoubleStr(v); }
    private long parseLong(String v) {
        try { return v == null ? 0 : Long.parseLong(v.replace(",","").replace("+","")); }
        catch (Exception e) { return 0; }
    }
    private long parseLongStr(String v) { return parseLong(v); }
    private int parseInt(String v) {
        try { return v == null ? 999 : Integer.parseInt(v.replace(",","")); }
        catch (Exception e) { return 999; }
    }
    private double round(double v) { return Math.round(v * 100.0) / 100.0; }

    // ─────────────────────────────────────────────────────────────
    // 기술지표 헬퍼 (순수 정적 수학 – 외부 라이브러리 불필요)
    // 모든 배열: [0]=최신, [n-1]=가장 과거 (newest-first)
    // ─────────────────────────────────────────────────────────────

    /** MA 평균: closes[offset..offset+period-1] */
    private static double maAvg(double[] arr, int offset, int period) {
        if (arr.length < offset + period) return 0;
        double s = 0; for (int i = offset; i < offset + period; i++) s += arr[i];
        return s / period;
    }

    /** Wilder's Smoothed RSI – newest-first output */
    private static double[] calcRsi(double[] closes, int period) {
        int n = closes.length;
        if (n < period + 2) return new double[0];
        // Reverse to oldest-first for processing
        double[] c = new double[n];
        for (int i = 0; i < n; i++) c[i] = closes[n - 1 - i];
        // Initial SMA avg gain/loss
        double ag = 0, al = 0;
        for (int i = 1; i <= period; i++) {
            double d = c[i] - c[i - 1];
            if (d > 0) ag += d; else al -= d;
        }
        ag /= period; al /= period;
        int rn = n - period;
        double[] r = new double[rn]; // oldest-first
        r[0] = al == 0 ? 100 : 100 - 100.0 / (1 + ag / al);
        for (int i = 1; i < rn; i++) {
            double d = c[period + i] - c[period + i - 1];
            ag = (ag * (period - 1) + Math.max(d, 0)) / period;
            al = (al * (period - 1) + Math.max(-d, 0)) / period;
            r[i] = al == 0 ? 100 : 100 - 100.0 / (1 + ag / al);
        }
        // Reverse to newest-first
        double[] out = new double[rn];
        for (int i = 0; i < rn; i++) out[i] = r[rn - 1 - i];
        return out;
    }

    /** EMA list – oldest-first, length = closes.length - period + 1 */
    private static double[] calcEmaOf(double[] closesNF, int period) {
        int n = closesNF.length;
        if (n < period) return new double[0];
        double[] c = new double[n];
        for (int i = 0; i < n; i++) c[i] = closesNF[n - 1 - i]; // oldest-first
        double alpha = 2.0 / (period + 1);
        double sma = 0;
        for (int i = 0; i < period; i++) sma += c[i];
        sma /= period;
        int len = n - period + 1;
        double[] ema = new double[len];
        ema[0] = sma;
        for (int i = 1; i < len; i++)
            ema[i] = c[period - 1 + i] * alpha + ema[i - 1] * (1 - alpha);
        return ema; // oldest-first
    }

    /**
     * MACD (12/26/9) – returns [macdLine, signalLine, histogram] each newest-first.
     * All three arrays have the same length = n - slow - signal + 2.
     */
    private static double[][] calcMacd(double[] closes, int fast, int slow, int signal) {
        double[] fastOf = calcEmaOf(closes, fast);  // oldest-first, len = n-fast+1
        double[] slowOf = calcEmaOf(closes, slow);  // oldest-first, len = n-slow+1
        int macdLen = slowOf.length;
        if (macdLen == 0) return new double[][]{new double[0], new double[0], new double[0]};
        int offset = fastOf.length - macdLen; // = slow - fast
        double[] macdOf = new double[macdLen];
        for (int i = 0; i < macdLen; i++) macdOf[i] = fastOf[i + offset] - slowOf[i];

        if (macdLen < signal) return new double[][]{new double[0], new double[0], new double[0]};
        double alpha = 2.0 / (signal + 1);
        double sma = 0;
        for (int i = 0; i < signal; i++) sma += macdOf[i];
        sma /= signal;
        int sigLen = macdLen - signal + 1;
        double[] sigOf = new double[sigLen];
        sigOf[0] = sma;
        for (int i = 1; i < sigLen; i++)
            sigOf[i] = macdOf[signal - 1 + i] * alpha + sigOf[i - 1] * (1 - alpha);

        double[] histOf = new double[sigLen];
        int mo = macdLen - sigLen;
        for (int i = 0; i < sigLen; i++) histOf[i] = macdOf[i + mo] - sigOf[i];

        // Reverse all to newest-first
        double[] mNF = new double[sigLen], sNF = new double[sigLen], hNF = new double[sigLen];
        for (int i = 0; i < sigLen; i++) {
            mNF[i] = macdOf[mo + sigLen - 1 - i];
            sNF[i] = sigOf[sigLen - 1 - i];
            hNF[i] = histOf[sigLen - 1 - i];
        }
        return new double[][]{mNF, sNF, hNF};
    }

    /** Bollinger Bands bandwidth % at index 0 (newest). Returns -1 if not enough data. */
    private static double calcBollingerBandwidth(double[] closes, int period) {
        if (closes.length < period) return -1;
        double mean = maAvg(closes, 0, period);
        double variance = 0;
        for (int i = 0; i < period; i++) variance += Math.pow(closes[i] - mean, 2);
        double std = Math.sqrt(variance / period);
        return mean > 0 ? (std * 4 / mean) * 100 : -1; // (upper-lower)/middle * 100
    }

    /** Bollinger Upper Band at index 0 (newest). Returns 0 if not enough data. */
    private static double calcBollingerUpper(double[] closes, int period) {
        if (closes.length < period) return 0;
        double mean = maAvg(closes, 0, period);
        double variance = 0;
        for (int i = 0; i < period; i++) variance += Math.pow(closes[i] - mean, 2);
        double std = Math.sqrt(variance / period);
        return mean + 2 * std;
    }

    /** Bollinger %B at index 0 (newest). Returns -1 if not enough data. */
    private static double calcBollingerPctB(double[] closes, int period) {
        if (closes.length < period) return -1;
        double mean = maAvg(closes, 0, period);
        double variance = 0;
        for (int i = 0; i < period; i++) variance += Math.pow(closes[i] - mean, 2);
        double std = Math.sqrt(variance / period);
        double upper = mean + 2 * std;
        double lower = mean - 2 * std;
        return upper > lower ? (closes[0] - lower) / (upper - lower) : -1;
    }

    /** Wilder's ATR – newest-first output */
    private static double[] calcAtr(double[] highs, double[] lows, double[] closes, int period) {
        int n = Math.min(highs.length, Math.min(lows.length, closes.length));
        if (n < period + 1) return new double[0];
        // TR oldest-first (reverse)
        double[] trOf = new double[n - 1];
        for (int i = 0; i < n - 1; i++) {
            int ni = n - 1 - i; // oldest-first index maps to closes[ni] (newer) and closes[ni+1] (older, but wait)
            // In newest-first array: closes[ni] is older than closes[ni-1]
            // So in oldest-first pass: index i in trOf corresponds to closes[n-1-i] → closes[n-2-i]
            double h = highs[n - 1 - i];
            double l = lows[n - 1 - i];
            double pc = closes[n - i]; // previous close in oldest-first = closes[n-1-i+1] in NF?
            // Oldest-first index i: price at time i = closes[n-1-i]; prev close at time i-1 = closes[n-i]
            // But i=0 means oldest, so prev close doesn't exist at i=0
            // Actually let's just do TR for i>=1 in oldest-first
            if (i == 0) { trOf[0] = h - l; continue; }
            double prevC = closes[n - 1 - (i - 1)]; // closes at time i-1 in oldest-first
            trOf[i] = Math.max(h - l, Math.max(Math.abs(h - prevC), Math.abs(l - prevC)));
        }
        // Wilder smooth
        double atr0 = 0;
        for (int i = 0; i < period; i++) atr0 += trOf[i];
        atr0 /= period;
        int rLen = n - period;
        double[] atrOf = new double[rLen];
        atrOf[0] = atr0;
        for (int i = 1; i < rLen; i++)
            atrOf[i] = (atrOf[i - 1] * (period - 1) + trOf[period - 1 + i]) / period;
        // Reverse to newest-first
        double[] out = new double[rLen];
        for (int i = 0; i < rLen; i++) out[i] = atrOf[rLen - 1 - i];
        return out;
    }

    /** Slow Stochastic – returns [slowK, slowD] each newest-first */
    private static double[][] calcSlowStoch(double[] highs, double[] lows, double[] closes,
                                            int kPeriod, int dPeriod, int slowing) {
        int n = Math.min(highs.length, Math.min(lows.length, closes.length));
        if (n < kPeriod + slowing + dPeriod) return new double[][]{new double[0], new double[0]};
        // Raw %K oldest-first
        int rawLen = n - kPeriod + 1;
        double[] rawK = new double[rawLen];
        for (int i = 0; i < rawLen; i++) {
            int ni = n - 1 - i; // newest index in NF for this oldest-first slot
            // Collect kPeriod values starting at position n-1-i backward
            double hh = 0, ll = Double.MAX_VALUE;
            for (int j = 0; j < kPeriod; j++) {
                int idx = ni - j; // going back in NF (older)
                if (idx < 0) break;
                hh = Math.max(hh, highs[idx]);
                ll = Math.min(ll, lows[idx]);
            }
            rawK[i] = (hh > ll) ? (closes[ni] - ll) / (hh - ll) * 100 : 50;
        }
        // Slow %K = SMA(rawK, slowing)
        int sLen = rawLen - slowing + 1;
        if (sLen <= 0) return new double[][]{new double[0], new double[0]};
        double[] slowKOf = new double[sLen];
        for (int i = 0; i < sLen; i++) {
            double s = 0; for (int j = 0; j < slowing; j++) s += rawK[i + j];
            slowKOf[i] = s / slowing;
        }
        // Slow %D = SMA(slowK, dPeriod)
        int dLen = sLen - dPeriod + 1;
        if (dLen <= 0) return new double[][]{new double[0], new double[0]};
        double[] slowDOf = new double[dLen];
        for (int i = 0; i < dLen; i++) {
            double s = 0; for (int j = 0; j < dPeriod; j++) s += slowKOf[i + j];
            slowDOf[i] = s / dPeriod;
        }
        // Align and reverse to newest-first
        int outLen = dLen;
        int kOff = sLen - outLen;
        double[] kNF = new double[outLen], dNF = new double[outLen];
        for (int i = 0; i < outLen; i++) {
            kNF[i] = slowKOf[kOff + outLen - 1 - i];
            dNF[i] = slowDOf[outLen - 1 - i];
        }
        return new double[][]{kNF, dNF};
    }

    /** Williams %R – newest-first, range 0 to -100 */
    private static double[] calcWilliamsR(double[] highs, double[] lows, double[] closes, int period) {
        int n = Math.min(highs.length, Math.min(lows.length, closes.length));
        if (n < period) return new double[0];
        int outLen = n - period + 1;
        double[] out = new double[outLen]; // newest-first
        for (int i = 0; i < outLen; i++) {
            double hh = 0, ll = Double.MAX_VALUE;
            for (int j = 0; j < period; j++) {
                hh = Math.max(hh, highs[i + j]);
                ll = Math.min(ll, lows[i + j]);
            }
            out[i] = hh > ll ? (hh - closes[i]) / (hh - ll) * -100 : -50;
        }
        return out;
    }

    /** MFI at index 0 (latest period window). Returns 0 if not enough data. */
    private static double calcMfiLatest(double[] highs, double[] lows, double[] closes, double[] vols, int period) {
        return calcMfiAt(highs, lows, closes, vols, period, 0);
    }

    /** MFI at offset (0=latest). Returns 0 if not enough data. */
    private static double calcMfiAt(double[] highs, double[] lows, double[] closes, double[] vols, int period, int offset) {
        int n = Math.min(highs.length, Math.min(lows.length, Math.min(closes.length, vols.length)));
        if (n < offset + period + 1) return 0;
        double posFlow = 0, negFlow = 0;
        for (int i = offset; i < offset + period; i++) {
            double tp  = (highs[i] + lows[i] + closes[i]) / 3.0;
            double tpp = (highs[i + 1] + lows[i + 1] + closes[i + 1]) / 3.0;
            double mf  = tp * vols[i];
            if (tp > tpp) posFlow += mf; else negFlow += mf;
        }
        return negFlow == 0 ? 100 : 100 - 100.0 / (1 + posFlow / negFlow);
    }
}
