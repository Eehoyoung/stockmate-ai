package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class StrategyService {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;

    // ─────────────────────────────────────────────────────────────
    // 전술 1: 갭상승 + 체결강도 시초가 매수  (8:30~9:05)
    // ─────────────────────────────────────────────────────────────
    public List<TradingSignalDto> scanGapOpening(List<String> candidates) {
        MDC.put("strategy", "S1_GAP_OPEN");
        log.info("[S1] 갭상승 시초가 스캔 시작 - 후보 {}개", candidates.size());
        List<TradingSignalDto> results = new ArrayList<>();

        for (String stkCd : candidates) {
            try {
                // Redis 예상체결 데이터
                var expOpt = redisService.getExpectedData(stkCd);
                if (expOpt.isEmpty()) continue;
                Map<Object, Object> exp = expOpt.get();

                double prevClose = parseDouble(exp, "pred_pre_pric");
                double expPrice  = parseDouble(exp, "exp_cntr_pric");
                if (prevClose <= 0 || expPrice <= 0) continue;

                double gapPct = (expPrice - prevClose) / prevClose * 100;
                if (gapPct < 3.0 || gapPct > 15.0) continue; // 3~15% 갭

                // 체결강도 (Redis 최근 5개 평균)
                double strength = redisService.getAvgCntrStrength(stkCd, 5);
                if (strength < 130.0) continue;

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
                        .strategy(TradingSignal.StrategyType.S1_GAP_OPEN)
                        .signalScore(round(score))
                        .gapPct(round(gapPct))
                        .cntrStrength(round(strength))
                        .bidRatio(round(bidRatio))
                        .entryType("시초가_시장가")
                        .targetPct(4.0)
                        .stopPct(-2.0)
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
                    .strategy(TradingSignal.StrategyType.S2_VI_PULLBACK)
                    .signalScore(round(score))
                    .pullbackPct(round(pullbackPct))
                    .cntrStrength(round(strength))
                    .bidRatio(round(bidRatio))
                    .entryType("지정가_눌림목")
                    .targetPct(3.0)
                    .stopPct(-2.0)
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

            Set<String> contSet = contResp.getItems() == null ? Collections.emptySet()
                    : contResp.getItems().stream()
                    .map(KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem::getStkCd)
                    .collect(Collectors.toSet());

            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : intradayResp.getItems()) {
                String stkCd = item.getStkCd();
                if (!contSet.contains(stkCd)) continue;

                // 거래량 비율 (Redis 당일 vs 전일)
                double volRatio = calcVolRatio(stkCd);
                if (volRatio < 1.5) continue;

                long netBuyAmt = parseLong(item.getNetBuyAmt());
                double score = netBuyAmt / 1_000_000.0 + volRatio * 5;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S3_INST_FRGN)
                        .signalScore(round(score))
                        .netBuyAmt(netBuyAmt)
                        .volRatio(round(volRatio))
                        .continuousDays(3)
                        .marketType(market)
                        .entryType("지정가_1호가")
                        .targetPct(3.5)
                        .stopPct(-2.0)
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
        try {
            var resp = apiService.post(
                    "ka10080", "/api/dostk/chart",
                    StrategyRequests.MinuteCandleRequest.builder().stkCd(stkCd).ticScope("5").build(),
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

            // 체결강도
            double strength = redisService.getAvgCntrStrength(stkCd, 3);
            if (strength < 140.0) return Optional.empty();

            // 20일 고가 대비 신고가 여부 (96봉 = 8시간 5분봉)
            double max20d = candles.subList(1, Math.min(97, candles.size())).stream()
                    .mapToDouble(can -> parseDoubleStr(can.getHighPric()))
                    .max().orElse(0);
            boolean isNewHigh = h >= max20d;

            double score = gainPct * 3 + bodyRatio * 10 + volRatio * 0.5
                    + (strength - 100) * 0.2 + (isNewHigh ? 20 : 0);

            return Optional.of(TradingSignalDto.builder()
                    .stkCd(stkCd)
                    .strategy(TradingSignal.StrategyType.S4_BIG_CANDLE)
                    .signalScore(round(score))
                    .gapPct(round(gainPct))
                    .volRatio(round(volRatio))
                    .cntrStrength(round(strength))
                    .bodyRatio(round(bodyRatio))
                    .isNewHigh(isNewHigh)
                    .entryType("추격_시장가")
                    .targetPct(4.0)
                    .stopPct(-2.5)
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

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S5_PROG_FRGN)
                        .signalScore(round(score))
                        .netBuyAmt(netBuyAmt)
                        .marketType(market)
                        .entryType("지정가_1호가")
                        .targetPct(3.0)
                        .stopPct(-2.0)
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

                    double strength = redisService.getAvgCntrStrength(stk.getStkCd(), 3);
                    if (strength < 120.0) continue;

                    double score = strength * 0.3 + (themeFluRt - stkFluRt) * 2;
                    double target = Math.min(themeFluRt * 0.6, 5.0);

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
                            .stopPct(-2.0)
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
    public List<TradingSignalDto> scanAuction(String market) {
        return scanAuction(market, Collections.emptySet());
    }

    /**
     * 사전 필터링된 종목 집합으로 S7 스캔 (preFiltered 비어있으면 전체 대상).
     */
    public List<TradingSignalDto> scanAuction(String market, Set<String> preFiltered) {
        log.info("[S7] 동시호가 스캔 [{}] preFiltered={}건", market, preFiltered.size());
        try {
            // ka10029 예상체결등락률 상위로 후보 조회
            KiwoomApiResponses.ExpCntrFluRtUpperResponse gapResp =
                    apiService.fetchKa10029(
                            StrategyRequests.ExpCntrFluRtUpperRequest.builder()
                                    .mrktTp(market).sortTp("1").trdeQtyCnd("10")
                                    .stkCnd("1").crdCnd("0").pricCnd("8").stexTp("1").build());

            if (gapResp == null || gapResp.getItems() == null) return Collections.emptyList();

            List<TradingSignalDto> results = new ArrayList<>();
            int rank = 1;
            for (var item : gapResp.getItems().stream().limit(50).toList()) {
                String stkCd = item.getStkCd();
                // 사전 필터 적용 (비어있으면 전체 허용)
                if (!preFiltered.isEmpty() && !preFiltered.contains(stkCd)) { rank++; continue; }

                var expOpt = redisService.getExpectedData(stkCd);
                if (expOpt.isEmpty()) { rank++; continue; }

                double prevClose = parseDouble(expOpt.get(), "pred_pre_pric");
                double expPrice  = parseDouble(expOpt.get(), "exp_cntr_pric");
                if (prevClose <= 0 || expPrice <= 0) { rank++; continue; }

                double gapPct = (expPrice - prevClose) / prevClose * 100;
                if (gapPct < 2.0 || gapPct > 10.0) { rank++; continue; }

                var hogaOpt = redisService.getHogaData(stkCd);
                if (hogaOpt.isEmpty()) { rank++; continue; }
                double bid = parseDouble(hogaOpt.get(), "total_buy_bid_req");
                double ask = parseDouble(hogaOpt.get(), "total_sel_bid_req");
                double bidRatio = ask > 0 ? bid / ask : 0;
                if (bidRatio < 2.0) { rank++; continue; }

                double score = bidRatio * 10 + gapPct + (50 - rank) * 0.5;

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S7_AUCTION)
                        .signalScore(round(score))
                        .gapPct(round(gapPct))
                        .bidRatio(round(bidRatio))
                        .volRank(rank)
                        .marketType(market)
                        .entryType("시초가_시장가")
                        .targetPct(Math.min(gapPct * 0.8, 5.0))
                        .stopPct(-2.0)
                        .build());
                rank++;
            }
            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5).collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S7] 스캔 오류: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 유틸
    // ─────────────────────────────────────────────────────────────
    private double calcVolRatio(String stkCd) {
        // Redis tick 데이터에서 당일 누적거래량 / 전일 동시간 추정 비교
        // 실제 구현 시 ka10055 호출 결과 캐시로 보완 가능
        var tickOpt = redisService.getTickData(stkCd);
        return tickOpt.map(m -> parseDouble(m, "vol_ratio")).orElse(1.0);
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
}
