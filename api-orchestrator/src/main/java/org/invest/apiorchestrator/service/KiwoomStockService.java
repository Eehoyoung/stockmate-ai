package org.invest.apiorchestrator.service;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.dto.KiwoomStockItem;
import org.invest.apiorchestrator.dto.req.KiwoomStockRequest;
import org.invest.apiorchestrator.dto.res.KiwoomStockResponse;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;
import java.util.stream.Collectors;

@Service
@Slf4j
public class KiwoomStockService {
    private final KiwoomProperties properties;
    private final TokenService tokenService;
    private final RestTemplate restTemplate;
    private final StringRedisTemplate redisTemplate;

    private static final String STOCK_CODE_MAP_KEY = "stock:code_map";

    public KiwoomStockService(KiwoomProperties properties, TokenService tokenService, RestTemplate restTemplate, StringRedisTemplate redisTemplate) {
        this.properties = properties;
        this.tokenService = tokenService;
        this.restTemplate = restTemplate;
        this.redisTemplate = redisTemplate;
    }

    public void syncAllStockCodes() {
        // 코스피(0)와 코스닥(10) 종목을 순차적으로 수집
        fetchAndStoreStocks("0");
        fetchAndStoreStocks("10");
    }

    private void fetchAndStoreStocks(String marketType) {
        String url = properties.getApi().getBaseUrl() + "/api/dostk/stkinfo";
        String token = tokenService.getBearerToken();

        String contYn = "N";
        String nextKey = "";

        do {
            // 1. 헤더 설정
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("api-id", "ka10099");
            headers.set("authorization", "Bearer " + token);
            headers.set("cont-yn", contYn);
            headers.set("next-key", nextKey);

            // 2. 바디 설정
            KiwoomStockRequest body = KiwoomStockRequest.builder().mrkt_tp(marketType).build();
            HttpEntity<KiwoomStockRequest> entity = new HttpEntity<>(body, headers);

            // 3. API 호출
            ResponseEntity<KiwoomStockResponse> responseEntity = restTemplate.postForEntity(url, entity, KiwoomStockResponse.class);
            KiwoomStockResponse response = responseEntity.getBody();

            if (response != null && "0".equals(response.getReturn_code())) {
                // 4. Redis에 종목코드:종목명 매핑 저장
                Map<String, String> stockMap = response.getList().stream()
                        .collect(Collectors.toMap(KiwoomStockItem::getCode, KiwoomStockItem::getName, (a, b) -> a));

                redisTemplate.opsForHash().putAll(STOCK_CODE_MAP_KEY, stockMap);

                // 5. 연속 조회 여부 파악 (헤더에서 추출)
                HttpHeaders responseHeaders = responseEntity.getHeaders();
                contYn = responseHeaders.getFirst("cont-yn");
                nextKey = responseHeaders.getFirst("next-key");

                log.info("Market[{}] 수집 중... 현재 {}개 저장 완료", marketType, stockMap.size());
            } else {
                log.error("종목 정보 수집 실패: {}", response != null ? response.getReturn_msg() : "응답 없음");
                break;
            }

        } while ("Y".equals(contYn)); // 다음 데이터가 있을 때까지 반복
    }
}
