package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class CandidateService {

    private final KiwoomApiService apiService;
    private final StringRedisTemplate redis;

    private static final String CANDIDATE_KEY   = "candidates:";
    private static final String WATCHLIST_KEY   = "candidates:watchlist";
    private static final Duration CANDIDATE_TTL = Duration.ofMinutes(3);

    /**
     * 예상체결등락률 상위 종목코드 반환 (ka10029, 캐시 3분).
     * 갭 3~30% 범위 필터 → S1 후보 리스트.
     *
     * @param market 001:코스피, 101:코스닥, 000:전체
     */
    public List<String> getCandidates(String market) {
        String cacheKey = CANDIDATE_KEY + market;
        List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
        if (cached != null && !cached.isEmpty()) {
            return cached;
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
                                    .stexTp("1")
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
     * 코스피 + 코스닥 통합 후보 종목
     */
    public List<String> getAllCandidates() {
        List<String> kospi  = getCandidates("001");
        List<String> kosdaq = getCandidates("101");
        return java.util.stream.Stream.concat(kospi.stream(), kosdaq.stream())
                .distinct()
                .collect(Collectors.toList());
    }
}
