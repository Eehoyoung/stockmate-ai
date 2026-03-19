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

    private static final String CANDIDATE_KEY = "candidates:";
    private static final Duration CANDIDATE_TTL = Duration.ofMinutes(3);

    /**
     * 시장 전체 거래량 순위 상위 200개 종목코드 반환 (캐시 3분)
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
            KiwoomApiResponses.VolumeRankResponse resp = apiService.post(
                    "ka10033", "/api/dostk/rkinfo",
                    StrategyRequests.VolumeRankRequest.builder()
                            .mrktTp(market)
                            .trdeQtyTp("10")   // 만주 이상
                            .stkCnd("1")        // 관리종목 제외
                            .updownIncls("0")   // 상하한 미포함
                            .build(),
                    KiwoomApiResponses.VolumeRankResponse.class);

            if (resp.getItems() == null) return Collections.emptyList();

            List<String> codes = resp.getItems().stream()
                    .map(KiwoomApiResponses.VolumeRankResponse.VolumeRankItem::getStkCd)
                    .limit(200)
                    .collect(Collectors.toList());

            if (!codes.isEmpty()) {
                redis.delete(cacheKey);
                redis.opsForList().rightPushAll(cacheKey, codes);
                redis.expire(cacheKey, CANDIDATE_TTL);
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
