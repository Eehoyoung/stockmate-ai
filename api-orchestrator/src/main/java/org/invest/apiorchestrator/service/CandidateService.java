package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class CandidateService {

    private final KiwoomApiService apiService;
    private final StringRedisTemplate redis;

    private static final String CANDIDATE_KEY   = "candidates:";
    private static final String WATCHLIST_KEY   = "candidates:watchlist";
    private static final String TAG_KEY         = "candidates:tag:";   // Set – 전략 태그
    private static final Duration CANDIDATE_TTL = Duration.ofMinutes(3);
    private static final Duration TAG_TTL       = Duration.ofHours(24);

    /**
     * 예상체결등락률 상위 종목코드 반환 (ka10029, 캐시 3분).
     * 갭 3~30% 범위 필터 → S1 후보 리스트.
     *
     * <p><b>거래 시간 외 보호</b>: Redis 캐시가 비어 있고 거래 시간이 아닌 경우
     * ka10029 API 를 호출하지 않고 빈 리스트를 반환합니다.
     * 모의 서버(mockapi)는 장 시간 외 예상체결 데이터가 없어 불필요한 API 소모와
     * Rate Limit(1700) 오류를 유발하기 때문입니다.
     *
     * @param market 001:코스피, 101:코스닥, 000:전체
     */
    public List<String> getCandidates(String market) {
        String cacheKey = CANDIDATE_KEY + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) {
            return cached;
        }

        // 캐시 없음 – 거래 시간 외이면 API 호출 생략 (Rate Limit 방어)
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 & 캐시 없음 – ka10029 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }

        try {
            KiwoomApiResponses.ExpCntrFluRtUpperResponse resp =
                    apiService.fetchKa10029(
                            StrategyRequests.ExpCntrFluRtUpperRequest.builder()
                                    .mrktTp(market)
                                    .sortTp("1")        // 상승률 순
                                    .trdeQtyCnd("10")   // 만주 이상
                                    .stkCnd("1")        // 관리종목 제외
                                    .crdCnd("0")
                                    .pricCnd("8")       // 1천원 이상
                                    .stexTp("3")
                                    .build());

            if (resp == null || resp.getItems() == null) return Collections.emptyList();

            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double fluRt = Double.parseDouble(
                                    item.getFluRt().replace("+", "").replace(",", ""));
                            return fluRt >= 3.0 && fluRt <= 30.0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.ExpCntrFluRtUpperResponse.ExpCntrFluRtItem::getStkCd)
                    .limit(200)
                    .collect(Collectors.toList());

            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, CANDIDATE_TTL);
                // WebSocket 동적 구독을 위한 watchlist 갱신
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
     * candidates:tag:{stkCd} (Set, TTL 24h)
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

    /**
     * 특정 종목에 기록된 전략 태그 조회.
     */
    public Set<String> getStrategyTags(String stkCd) {
        try {
            Set<String> tags = redis.opsForSet().members(TAG_KEY + stkCd);
            return tags != null ? tags : Collections.emptySet();
        } catch (Exception e) {
            return Collections.emptySet();
        }
    }

    /**
     * 후보 종목 목록 + 전략 태그 맵 반환.
     * 반환 형태: [{code: "005930", strategies: ["S1_GAP_OPEN", "S3_INST_FRGN"]}, ...]
     */
    public List<Map<String, Object>> getCandidatesWithTags(String market) {
        List<String> codes = getCandidates(market);
        return codes.stream().map(code -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("code", code);
            item.put("strategies", getStrategyTags(code));
            return item;
        }).collect(Collectors.toList());
    }

    /**
     * 코스피 + 코스닥 통합 후보 종목
     */
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

    private static final String S1_KEY  = "candidates:s1:";
    private static final Duration S1_TTL = Duration.ofMinutes(3);

    /**
     * S1 갭상승 시초가 후보 풀 (ka10029, 캐시 3분).
     * 예상체결등락률 3~15% 필터 – S1 전용.
     * key: candidates:s1:{market}
     */
    public List<String> getS1Candidates(String market) {
        String cacheKey = S1_KEY + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;

        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S1 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }

        try {
            KiwoomApiResponses.ExpCntrFluRtUpperResponse resp =
                    apiService.fetchKa10029(
                            StrategyRequests.ExpCntrFluRtUpperRequest.builder()
                                    .mrktTp(market)
                                    .sortTp("1")
                                    .trdeQtyCnd("10")   // 만주 이상
                                    .stkCnd("1")        // 관리종목 제외
                                    .crdCnd("0")
                                    .pricCnd("8")       // 1천원 이상
                                    .stexTp("3")
                                    .build());

            if (resp == null || resp.getItems() == null) return Collections.emptyList();

            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double fluRt = Double.parseDouble(
                                    item.getFluRt().replace("+", "").replace(",", ""));
                            return fluRt >= 3.0 && fluRt <= 15.0;   // S1: 3~15%
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.ExpCntrFluRtUpperResponse.ExpCntrFluRtItem::getStkCd)
                    .limit(100)
                    .collect(Collectors.toList());

            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, S1_TTL);
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S1 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    // ─────────────────────────────────────────────────────────────
    // 전략별 전용 후보 풀  candidates:s{N}:{market}
    // ─────────────────────────────────────────────────────────────

    private static final Duration POOL_TTL    = Duration.ofMinutes(20);  // 스윙 풀 – Java 스캔 주기(5분) × 4배 여유

    /**
     * S7 동시호가 후보 풀 (ka10029, 캐시 3분).
     * 예상체결등락률 2~10% 필터 – S1(3~15%)보다 완화된 범위.
     * key: candidates:s7:{market}
     */
    public List<String> getS7Candidates(String market) {
        String cacheKey = "candidates:s7:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S7 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.ExpCntrFluRtUpperResponse resp =
                    apiService.fetchKa10029(
                            StrategyRequests.ExpCntrFluRtUpperRequest.builder()
                                    .mrktTp(market).sortTp("1").trdeQtyCnd("10")
                                    .stkCnd("1").crdCnd("0").pricCnd("8").stexTp("3")
                                    .build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double f = Double.parseDouble(item.getFluRt().replace("+","").replace(",",""));
                            return f >= 2.0 && f <= 10.0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.ExpCntrFluRtUpperResponse.ExpCntrFluRtItem::getStkCd)
                    .limit(100).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, Duration.ofMinutes(3));
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S7 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S8 골든크로스 스윙 후보 풀 (ka10027 상승률, 캐시 20분).
     * 등락률 0.5~8% 소폭 상승 필터.
     * key: candidates:s8:{market}
     */
    public List<String> getS8Candidates(String market) {
        String cacheKey = "candidates:s8:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S8 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.FluRtUpperResponse resp =
                    apiService.fetchKa10027(
                            StrategyRequests.FluRtUpperRequest.builder()
                                    .mrktTp(market).sortTp("1").trdeQtyCnd("0010")
                                    .stkCnd("1").crdCnd("0").updownIncls("0")
                                    .pricCnd("8").trdePricaCnd("0").build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double f = Double.parseDouble(item.getFluRt().replace("+","").replace(",",""));
                            return f >= 0.5 && f <= 8.0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.FluRtUpperResponse.FluRtUpperItem::getStkCd)
                    .limit(150).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, POOL_TTL);
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S8 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S9 정배열 눌림목 스윙 후보 풀 (ka10027 상승률 0.3~5%, 캐시 20분).
     * key: candidates:s9:{market}
     */
    public List<String> getS9Candidates(String market) {
        String cacheKey = "candidates:s9:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S9 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.FluRtUpperResponse resp =
                    apiService.fetchKa10027(
                            StrategyRequests.FluRtUpperRequest.builder()
                                    .mrktTp(market).sortTp("1").trdeQtyCnd("0010")
                                    .stkCnd("1").crdCnd("0").updownIncls("0")
                                    .pricCnd("8").trdePricaCnd("0").build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double f = Double.parseDouble(item.getFluRt().replace("+","").replace(",",""));
                            return f >= 0.3 && f <= 5.0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.FluRtUpperResponse.FluRtUpperItem::getStkCd)
                    .limit(150).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, POOL_TTL);
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S9 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S10 52주 신고가 돌파 스윙 후보 풀 (ka10016, 캐시 20분).
     * key: candidates:s10:{market}
     */
    public List<String> getS10Candidates(String market) {
        String cacheKey = "candidates:s10:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S10 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.NtlPricResponse resp =
                    apiService.fetchKa10016(
                            StrategyRequests.NtlPricRequest.builder()
                                    .mrktTp(market).build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .map(KiwoomApiResponses.NtlPricResponse.NtlPricItem::getStkCd)
                    .filter(cd -> cd != null && !cd.isBlank())
                    .limit(100).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, POOL_TTL);
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S10 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S11 외국인 연속 순매수 스윙 후보 풀 (ka10035, 캐시 30분).
     * D-1·D-2·D-3 모두 양수 + tot > 0 필터.
     * key: candidates:s11:{market}
     */
    public List<String> getS11Candidates(String market) {
        String cacheKey = "candidates:s11:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S11 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.FrgnContNettrdUpperResponse resp =
                    apiService.fetchKa10035(
                            StrategyRequests.FrgnContNettrdRequest.builder()
                                    .mrktTp(market).trdeTp("2").baseDtTp("1").build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            return parseSignedInt(item.getDm1()) > 0
                                    && parseSignedInt(item.getDm2()) > 0
                                    && parseSignedInt(item.getDm3()) > 0
                                    && parseSignedInt(item.getTot()) > 0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem::getStkCd)
                    .filter(cd -> cd != null && !cd.isBlank())
                    .limit(80).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, Duration.ofMinutes(30));
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S11 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S12 종가 강도 확인 매수 후보 풀 (ka10032, 캐시 10분).
     * 거래대금 상위 종목 중 당일 양전(flu_rt > 0) 필터.
     * key: candidates:s12:{market}
     */
    public List<String> getS12Candidates(String market) {
        String cacheKey = "candidates:s12:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S12 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.TrdePricaUpperResponse resp =
                    apiService.fetchKa10032(
                            StrategyRequests.TrdePricaUpperRequest.builder()
                                    .mrktTp(market).mangStkIncls("0").build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double f = Double.parseDouble(item.getFluRt().replace("+","").replace(",",""));
                            return f > 0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.TrdePricaUpperResponse.TrdePricaUpperItem::getStkCd)
                    .filter(cd -> cd != null && !cd.isBlank())
                    .limit(50).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, Duration.ofMinutes(10));
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S12 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S13 박스권 돌파 스윙 후보 풀 (S8 ∪ S10 합산, 별도 API 호출 없음).
     * key: candidates:s13:{market}, TTL 5분
     */
    public List<String> getS13Candidates(String market) {
        String cacheKey = "candidates:s13:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S13 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        List<String> codes = java.util.stream.Stream.concat(
                        getS8Candidates(market).stream(),
                        getS10Candidates(market).stream())
                .distinct().limit(150).collect(Collectors.toList());
        if (!codes.isEmpty()) {
            redis.delete(cacheKey);
            redis.opsForList().rightPushAll(cacheKey, codes);
            redis.expire(cacheKey, POOL_TTL);
        }
        return codes;
    }

    /**
     * S14 과매도 반등 스윙 후보 풀 (ka10027 하락률 3~10%, 캐시 20분).
     * key: candidates:s14:{market}
     */
    public List<String> getS14Candidates(String market) {
        String cacheKey = "candidates:s14:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S14 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        try {
            KiwoomApiResponses.FluRtUpperResponse resp =
                    apiService.fetchKa10027(
                            StrategyRequests.FluRtUpperRequest.builder()
                                    .mrktTp(market).sortTp("3").trdeQtyCnd("0010")
                                    .stkCnd("1").crdCnd("0").updownIncls("0")
                                    .pricCnd("8").trdePricaCnd("0").build());
            if (resp == null || resp.getItems() == null) return Collections.emptyList();
            List<String> codes = resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double f = Math.abs(Double.parseDouble(item.getFluRt().replace("+","").replace(",","")));
                            return f >= 3.0 && f <= 10.0;
                        } catch (Exception ex) { return false; }
                    })
                    .map(KiwoomApiResponses.FluRtUpperResponse.FluRtUpperItem::getStkCd)
                    .limit(100).collect(Collectors.toList());
            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, POOL_TTL);
            }
            return codes;
        } catch (Exception e) {
            log.error("[Candidate] S14 후보 조회 실패 [{}]: {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * S15 모멘텀 동조 스윙 후보 풀 (S8 풀 재활용, 캐시 20분).
     * S8과 동일한 소스(ka10027 0.5~8%) 사용, 별도 TTL로 독립 관리.
     * key: candidates:s15:{market}
     */
    public List<String> getS15Candidates(String market) {
        String cacheKey = "candidates:s15:" + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) return cached;
        if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
            log.debug("[Candidate] 거래 시간 외 – S15 풀 호출 생략 [market={}]", market);
            return Collections.emptyList();
        }
        List<String> codes = getS8Candidates(market);
        if (!codes.isEmpty()) {
            redis.delete(cacheKey);
            redis.opsForList().rightPushAll(cacheKey, codes);
            redis.expire(cacheKey, POOL_TTL);
        }
        return codes;
    }

    // 부호 포함 정수 파싱 (+34396981, -140)
    private static int parseSignedInt(String val) {
        if (val == null) return 0;
        try { return Integer.parseInt(val.replace("+","").replace(",","").trim()); }
        catch (NumberFormatException e) { return 0; }
    }
}
