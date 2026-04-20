package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.util.MarketTimeUtil;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Supplier;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class CandidateService {

    private final KiwoomApiService apiService;
    private final StringRedisTemplate redis;

    private static final String CANDIDATE_KEY   = "candidates:";
    private static final String WATCHLIST_KEY   = "candidates:watchlist";
    private static final String TAG_KEY         = "candidates:tag:";
    private static final Duration CANDIDATE_TTL = Duration.ofMinutes(3);
    private static final Duration TAG_TTL       = Duration.ofHours(24);
    private static final Duration POOL_TTL      = Duration.ofMinutes(20);
    private static final Duration S4_TTL        = Duration.ofMinutes(5);

    /**
     * 예상체결등락률 상위 종목코드 반환 (ka10029, 캐시 3분).
     * 갭 3~30% 범위 필터 → S1 후보 리스트.
     *
     * <p><b>거래 시간 외 보호</b>: Redis 캐시가 비어 있고 거래 시간이 아닌 경우
     * ka10029 API 를 호출하지 않고 빈 리스트를 반환합니다.
     *
     * @param market 001:코스피, 101:코스닥, 000:전체
     */
    public List<String> getCandidates(String market) {
        String cacheKey = CANDIDATE_KEY + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) {
            return cached;
        }

        if (!MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 & 캐시 없음 – ka10029 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }

        try {
            List<String> codes = fetchKa10029Codes(market, 3.0, 30.0, 200);
            if (!codes.isEmpty()) {
                cacheCodes(cacheKey, codes, CANDIDATE_TTL);
                redis.opsForSet().add(WATCHLIST_KEY, codes.toArray(new String[0]));
                redis.expire(WATCHLIST_KEY, Duration.ofMinutes(10));
            }
            return codes;
        } catch (Exception e) {
            log.error("후보 종목 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * 전략 신호 발행 시 해당 종목에 전략 태그 기록.
     */
    public void tagStrategy(String stkCd, String strategy) {
        try {
            String key = TAG_KEY + stkCd;
            redis.opsForSet().add(key, strategy);
            redis.expire(key, TAG_TTL);
        } catch (Exception e) {
            log.debug("[Candidate] 전략 태그 기록 실패 [{} {}]: {}", stkCd, strategy, e.getMessage());
        }
    }

    public Set<String> getStrategyTags(String stkCd) {
        try {
            Set<String> tags = redis.opsForSet().members(TAG_KEY + stkCd);
            return tags != null ? tags : Collections.emptySet();
        } catch (Exception e) {
            return Collections.emptySet();
        }
    }

    public List<Map<String, Object>> getCandidatesWithTags(String market) {
        List<String> codes = getCandidates(market);
        return codes.stream().map(code -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("code", code);
            item.put("strategies", getStrategyTags(code));
            return item;
        }).collect(Collectors.toList());
    }

    public List<String> getAllCandidates() {
        List<String> kospi  = getCandidates("001");
        List<String> kosdaq = getCandidates("101");
        return java.util.stream.Stream.concat(kospi.stream(), kosdaq.stream())
                .distinct()
                .collect(Collectors.toList());
    }

    // ─────────────────────────────────────────────────────────────
    // 전략별 전용 후보 풀  (candidates:s{N}:{market})
    // ─────────────────────────────────────────────────────────────

    /** S1 갭상승 시초가 (ka10029, 3~15%, TTL 90분 — 08:30 Python 스캔 윈도우 커버) */
    public List<String> getS1Candidates(String market) {
        return loadCandidates("s1", market, Duration.ofMinutes(90), 90,
                () -> fetchKa10029Codes(market, 3.0, 15.0, 100));
    }

    /** S4 장대양봉 + 거래량급증 (ka10023, sdninRt≥50 & 3~20%, TTL 5분) */
    public List<String> getS4Candidates(String market) {
        return loadCandidates("s4", market, S4_TTL, 5,
                () -> fetchKa10023Codes(market, 50.0, 3.0, 20.0, 100));
    }

    /** S8 골든크로스 스윙 (ka10027 상승률, 0.5~8%, TTL 20분) */
    public List<String> getS8Candidates(String market) {
        return loadCandidates("s8", market, POOL_TTL, 20,
                () -> fetchKa10027Codes(market, "1", 0.5, 8.0, false, 150));
    }

    /** S9 정배열 눌림목 스윙 (ka10027 상승률, 0.3~5%, TTL 20분) */
    public List<String> getS9Candidates(String market) {
        return loadCandidates("s9", market, POOL_TTL, 20,
                () -> fetchKa10027Codes(market, "1", 0.3, 5.0, false, 150));
    }

    /** S10 52주 신고가 돌파 스윙 (ka10016, TTL 20분) */
    public List<String> getS10Candidates(String market) {
        return loadCandidates("s10", market, POOL_TTL, 20,
                () -> fetchKa10016Codes(market, 100));
    }

    /** S11 외국인 연속 순매수 (ka10035, D1·D2·D3·tot 모두 양수, TTL 30분) */
    public List<String> getS11Candidates(String market) {
        return loadCandidates("s11", market, Duration.ofMinutes(30), 30,
                () -> fetchKa10035Codes(market, 80));
    }

    /** S12 종가 강도 확인 (ka10032 거래대금상위, flu_rt>0, TTL 10분) */
    public List<String> getS12Candidates(String market) {
        return loadCandidates("s12", market, Duration.ofMinutes(10), 10,
                () -> fetchKa10032Codes(market, 0.0001, Double.MAX_VALUE, 50));
    }

    /** S13 박스권 돌파 (ka10023, sdninRt≥30 & 3~8%, TTL 10분) */
    public List<String> getS13Candidates(String market) {
        return loadCandidates("s13", market, Duration.ofMinutes(10), 10,
                () -> fetchKa10023Codes(market, 30.0, 3.0, 8.0, 100));
    }

    /** S14 과매도 반등 스윙 (ka10027 하락률, |flu|3~10%, TTL 20분) */
    public List<String> getS14Candidates(String market) {
        return loadCandidates("s14", market, POOL_TTL, 20,
                () -> fetchKa10027Codes(market, "3", 3.0, 10.0, true, 100));
    }

    /** S15 모멘텀 정렬 (ka10032 거래대금상위, 0.5~8%, TTL 15분) */
    public List<String> getS15Candidates(String market) {
        return loadCandidates("s15", market, Duration.ofMinutes(15), 15,
                () -> fetchKa10032Codes(market, 0.5, 8.0, 80));
    }

    // ─────────────────────────────────────────────────────────────
    // 템플릿 + 내부 헬퍼
    // ─────────────────────────────────────────────────────────────

    /**
     * 모든 전략 후보 풀의 공통 템플릿.
     * 캐시 읽기 → 거래시간 가드 → fetcher 실행 → 캐시 쓰기 + watchlist 갱신.
     */
    private List<String> loadCandidates(String strategyKey, String market,
                                         Duration ttl, int watchlistTtlMin,
                                         Supplier<List<String>> fetcher) {
        String cacheKey = "candidates:" + strategyKey + ":" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;

        if (!MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – {} 풀 호출 생략 [market={}]",
                    strategyKey.toUpperCase(), market);
            return Collections.emptyList();
        }

        try {
            List<String> codes = fetcher.get();
            if (codes != null && !codes.isEmpty()) {
                cacheCodes(cacheKey, codes, ttl);
                updateWatchlist(codes, watchlistTtlMin);
            }
            return codes == null ? Collections.emptyList() : codes;
        } catch (Exception e) {
            log.error("[Candidate] {} 후보 조회 실패 [{}]: {}",
                    strategyKey.toUpperCase(), market, e.getMessage());
            return Collections.emptyList();
        }
    }

    private void cacheCodes(String cacheKey, List<String> codes, Duration ttl) {
        redis.delete(cacheKey);
        redis.opsForList().rightPushAll(cacheKey, codes);
        redis.expire(cacheKey, ttl);
    }

    /**
     * candidates:watchlist SET 갱신 — websocket-listener 가 5초마다 읽어 동적 구독을 관리한다.
     */
    private void updateWatchlist(List<String> codes, int ttlMinutes) {
        if (codes == null || codes.isEmpty()) return;
        try {
            redis.opsForSet().add(WATCHLIST_KEY, codes.toArray(new String[0]));
            redis.expire(WATCHLIST_KEY, Duration.ofMinutes(ttlMinutes));
        } catch (Exception e) {
            log.debug("[Candidate] watchlist 갱신 실패: {}", e.getMessage());
        }
    }

    // ───────── Kiwoom API fetcher 헬퍼 ─────────

    /** ka10029 예상체결등락률 상위 → flu_rt 범위 필터. */
    private List<String> fetchKa10029Codes(String market, double fluMin, double fluMax, int limit) {
        KiwoomApiResponses.ExpCntrFluRtUpperResponse resp =
                apiService.fetchKa10029(
                        StrategyRequests.ExpCntrFluRtUpperRequest.builder()
                                .mrktTp(market)
                                .sortTp("1")
                                .trdeQtyCnd("10")
                                .stkCnd("1")
                                .crdCnd("0")
                                .pricCnd("8")
                                .stexTp("3")
                                .build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        return resp.getItems().stream()
                .filter(item -> inRange(item.getFluRt(), fluMin, fluMax))
                .map(KiwoomApiResponses.ExpCntrFluRtUpperResponse.ExpCntrFluRtItem::getStkCd)
                .filter(cd -> cd != null && !cd.isBlank())
                .limit(limit)
                .collect(Collectors.toList());
    }

    /** ka10023 거래량급증 → sdninRt≥min & flu_rt 범위. */
    private List<String> fetchKa10023Codes(String market, double sdninMin,
                                           double fluMin, double fluMax, int limit) {
        KiwoomApiResponses.TrdeQtySdninResponse resp =
                apiService.fetchKa10023(
                        StrategyRequests.TrdeQtySdninRequest.builder()
                                .mrktTp(market).sortTp("2").tmTp("1").tm("5")
                                .trdeQtyTp("10").stkCnd("1").pricTp("8")
                                .build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        return resp.getItems().stream()
                .filter(item -> parseFluRt(item.getSdninRt()) >= sdninMin
                        && inRange(item.getFluRt(), fluMin, fluMax))
                .map(KiwoomApiResponses.TrdeQtySdninResponse.TrdeQtySdninItem::getStkCd)
                .filter(cd -> cd != null && !cd.isBlank())
                .limit(limit)
                .collect(Collectors.toList());
    }

    /** ka10027 상승률/하락률 순. {@code abs=true} 시 절대값으로 범위 판정(과매도 반등용). */
    private List<String> fetchKa10027Codes(String market, String sortTp,
                                           double fluMin, double fluMax,
                                           boolean abs, int limit) {
        KiwoomApiResponses.FluRtUpperResponse resp =
                apiService.fetchKa10027(
                        StrategyRequests.FluRtUpperRequest.builder()
                                .mrktTp(market).sortTp(sortTp).trdeQtyCnd("0010")
                                .stkCnd("1").crdCnd("0").updownIncls("0")
                                .pricCnd("8").trdePricaCnd("0").build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        return resp.getItems().stream()
                .filter(item -> {
                    double f = parseFluRt(item.getFluRt());
                    double v = abs ? Math.abs(f) : f;
                    return v >= fluMin && v <= fluMax;
                })
                .map(KiwoomApiResponses.FluRtUpperResponse.FluRtUpperItem::getStkCd)
                .filter(cd -> cd != null && !cd.isBlank())
                .limit(limit)
                .collect(Collectors.toList());
    }

    /** ka10016 신고가 돌파 (필터 없음, 단순 코드 추출). */
    private List<String> fetchKa10016Codes(String market, int limit) {
        KiwoomApiResponses.NtlPricResponse resp =
                apiService.fetchKa10016(
                        StrategyRequests.NtlPricRequest.builder().mrktTp(market).build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        return resp.getItems().stream()
                .map(KiwoomApiResponses.NtlPricResponse.NtlPricItem::getStkCd)
                .filter(cd -> cd != null && !cd.isBlank())
                .limit(limit)
                .collect(Collectors.toList());
    }

    /** ka10035 외국인 연속 순매수 → D1·D2·D3·tot 모두 양수. */
    private List<String> fetchKa10035Codes(String market, int limit) {
        KiwoomApiResponses.FrgnContNettrdUpperResponse resp =
                apiService.fetchKa10035(
                        StrategyRequests.FrgnContNettrdRequest.builder()
                                .mrktTp(market).trdeTp("2").baseDtTp("1").build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        return resp.getItems().stream()
                .filter(item -> parseSignedInt(item.getDm1()) > 0
                        && parseSignedInt(item.getDm2()) > 0
                        && parseSignedInt(item.getDm3()) > 0
                        && parseSignedInt(item.getTot()) > 0)
                .map(KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem::getStkCd)
                .filter(cd -> cd != null && !cd.isBlank())
                .limit(limit)
                .collect(Collectors.toList());
    }

    /** ka10032 거래대금상위 → flu_rt 범위 필터. */
    private List<String> fetchKa10032Codes(String market, double fluMin, double fluMax, int limit) {
        KiwoomApiResponses.TrdePricaUpperResponse resp =
                apiService.fetchKa10032(
                        StrategyRequests.TrdePricaUpperRequest.builder()
                                .mrktTp(market).mangStkIncls("0").build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        return resp.getItems().stream()
                .filter(item -> inRange(item.getFluRt(), fluMin, fluMax))
                .map(KiwoomApiResponses.TrdePricaUpperResponse.TrdePricaUpperItem::getStkCd)
                .filter(cd -> cd != null && !cd.isBlank())
                .limit(limit)
                .collect(Collectors.toList());
    }

    // ───────── 파싱 유틸 ─────────

    private static double parseFluRt(String raw) {
        if (raw == null) return 0.0;
        try {
            return Double.parseDouble(raw.replace("+", "").replace(",", "").trim());
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    private static boolean inRange(String raw, double min, double max) {
        try {
            double f = parseFluRt(raw);
            return f >= min && f <= max;
        } catch (Exception e) {
            return false;
        }
    }

    private static int parseSignedInt(String val) {
        if (val == null) return 0;
        try { return Integer.parseInt(val.replace("+", "").replace(",", "").trim()); }
        catch (NumberFormatException e) { return 0; }
    }
}
