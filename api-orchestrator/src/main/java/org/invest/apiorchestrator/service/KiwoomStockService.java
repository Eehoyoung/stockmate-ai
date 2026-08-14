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
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
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
    private static final String STOCK_CODE_MAP_SYNC_KEY = "stock:code_map:sync";
    private static final int NETWORK_MAX_ATTEMPTS = 3;
    private static final long NETWORK_RETRY_BASE_DELAY_MS = 500L;

    public KiwoomStockService(KiwoomProperties properties, TokenService tokenService, RestTemplate restTemplate, StringRedisTemplate redisTemplate) {
        this.properties = properties;
        this.tokenService = tokenService;
        this.restTemplate = restTemplate;
        this.redisTemplate = redisTemplate;
    }

    public void syncAllStockCodes() {
        Map<String, String> completeMap = new LinkedHashMap<>();
        completeMap.putAll(fetchStocks("0"));
        completeMap.putAll(fetchStocks("10"));
        if (completeMap.isEmpty()) {
            throw new IllegalStateException("ka10099 returned no stocks");
        }

        // Preserve the live map until both markets have been collected. Redis
        // RENAME swaps the complete temporary hash into place atomically.
        redisTemplate.delete(STOCK_CODE_MAP_SYNC_KEY);
        redisTemplate.opsForHash().putAll(STOCK_CODE_MAP_SYNC_KEY, completeMap);
        redisTemplate.rename(STOCK_CODE_MAP_SYNC_KEY, STOCK_CODE_MAP_KEY);
        log.info("stock:code_map atomically replaced count={}", completeMap.size());
    }

    private Map<String, String> fetchStocks(String marketType) {
        String url = properties.getApi().getBaseUrl() + "/api/dostk/stkinfo";
        // getBearerToken() already returns the "Bearer " prefix — do not prepend it again here.
        String bearerToken = tokenService.getBearerToken();

        String contYn = "N";
        String nextKey = "";
        Map<String, String> marketMap = new LinkedHashMap<>();

        do {
            // 1. 헤더 설정
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("api-id", "ka10099");
            headers.set("authorization", bearerToken);
            headers.set("cont-yn", contYn);
            headers.set("next-key", nextKey);

            // 2. 바디 설정
            KiwoomStockRequest body = KiwoomStockRequest.builder().mrkt_tp(marketType).build();
            HttpEntity<KiwoomStockRequest> entity = new HttpEntity<>(body, headers);

            // 3. API 호출
            ResponseEntity<KiwoomStockResponse> responseEntity = postWithNetworkRetry(
                    url, entity, marketType);
            KiwoomStockResponse response = responseEntity.getBody();

            if (response != null && "0".equals(response.getReturn_code())) {
                // 4. Redis에 종목코드:종목명 매핑 저장
                Map<String, String> stockMap = response.getList().stream()
                        .collect(Collectors.toMap(KiwoomStockItem::getCode, KiwoomStockItem::getName, (a, b) -> a));

                marketMap.putAll(stockMap);

                // 5. 연속 조회 여부 파악 (헤더에서 추출)
                HttpHeaders responseHeaders = responseEntity.getHeaders();
                contYn = responseHeaders.getFirst("cont-yn");
                nextKey = responseHeaders.getFirst("next-key");

                log.info("Market[{}] 수집 중... 현재 {}개 수집 완료", marketType, marketMap.size());
            } else {
                String reason = response != null ? response.getReturn_msg() : "empty response";
                throw new IllegalStateException(
                        "ka10099 failed market=" + marketType + " reason=" + reason);
            }

        } while ("Y".equals(contYn)); // 다음 데이터가 있을 때까지 반복
        return marketMap;
    }

    private ResponseEntity<KiwoomStockResponse> postWithNetworkRetry(
            String url,
            HttpEntity<KiwoomStockRequest> entity,
            String marketType
    ) {
        ResourceAccessException lastError = null;
        for (int attempt = 1; attempt <= NETWORK_MAX_ATTEMPTS; attempt++) {
            try {
                return restTemplate.postForEntity(url, entity, KiwoomStockResponse.class);
            } catch (ResourceAccessException e) {
                lastError = e;
                if (attempt == NETWORK_MAX_ATTEMPTS) {
                    break;
                }
                long delayMs = NETWORK_RETRY_BASE_DELAY_MS * attempt;
                log.warn(
                        "ka10099 network error market={} attempt={}/{} retryInMs={} reason={}",
                        marketType, attempt, NETWORK_MAX_ATTEMPTS, delayMs, e.getMessage());
                try {
                    Thread.sleep(delayMs);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("ka10099 retry interrupted market=" + marketType, interrupted);
                }
            }
        }
        throw lastError;
    }
}
