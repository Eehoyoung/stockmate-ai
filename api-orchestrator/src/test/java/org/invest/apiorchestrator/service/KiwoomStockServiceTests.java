package org.invest.apiorchestrator.service;

import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.dto.KiwoomStockItem;
import org.invest.apiorchestrator.dto.res.KiwoomStockResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * stock:code_map 동기화(syncAllStockCodes)가 Authorization 헤더를 "Bearer" 를 두 번 붙이지 않고
 * 정확히 전송하는지, 그리고 응답을 Redis stock:code_map 해시에 저장하는지 검증.
 * (2026-07-30: 중복 "Bearer Bearer" 접두어 버그로 ka10099 호출이 항상 실패해 stock:code_map 이
 * 비어 있었고, candidates_builder.py의 ETF/ETN 후보 필터가 무력화되어 있었다.)
 */
@ExtendWith(MockitoExtension.class)
class KiwoomStockServiceTests {

    @Mock TokenService tokenService;
    @Mock StringRedisTemplate redisTemplate;

    @Test
    void authorizationHeaderIsNotDoublePrefixedWithBearer() {
        KiwoomProperties properties = new KiwoomProperties();
        properties.getApi().setBaseUrl("https://api.kiwoom.com");

        RestTemplate restTemplate = mock(RestTemplate.class);
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redisTemplate.opsForHash()).thenReturn(hashOps);
        when(tokenService.getBearerToken()).thenReturn("Bearer abc123");

        KiwoomStockResponse emptyResponse = new KiwoomStockResponse();
        emptyResponse.setReturn_code("0");
        emptyResponse.setReturn_msg("정상");
        KiwoomStockItem item = new KiwoomStockItem();
        item.setCode("005930");
        item.setName("삼성전자");
        emptyResponse.setList(List.of(item));
        when(restTemplate.postForEntity(anyString(), org.mockito.ArgumentMatchers.any(), eq(KiwoomStockResponse.class)))
                .thenReturn(ResponseEntity.ok(emptyResponse));

        KiwoomStockService service = new KiwoomStockService(properties, tokenService, restTemplate, redisTemplate);
        service.syncAllStockCodes();

        ArgumentCaptor<HttpEntity> entityCaptor = ArgumentCaptor.forClass(HttpEntity.class);
        org.mockito.Mockito.verify(restTemplate, org.mockito.Mockito.atLeastOnce())
                .postForEntity(anyString(), entityCaptor.capture(), eq(KiwoomStockResponse.class));

        HttpHeaders headers = entityCaptor.getValue().getHeaders();
        String authHeader = headers.getFirst("authorization");
        assertEquals("Bearer abc123", authHeader);
        assertFalse(authHeader.startsWith("Bearer Bearer"));
    }

    @Test
    void successfulResponseStoresCodeNameMapInRedis() {
        KiwoomProperties properties = new KiwoomProperties();
        properties.getApi().setBaseUrl("https://api.kiwoom.com");

        RestTemplate restTemplate = mock(RestTemplate.class);
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redisTemplate.opsForHash()).thenReturn(hashOps);
        when(tokenService.getBearerToken()).thenReturn("Bearer abc123");

        KiwoomStockItem etf = new KiwoomStockItem();
        etf.setCode("114800");
        etf.setName("KODEX 인버스");
        KiwoomStockItem stock = new KiwoomStockItem();
        stock.setCode("005930");
        stock.setName("삼성전자");

        KiwoomStockResponse response = new KiwoomStockResponse();
        response.setReturn_code("0");
        response.setReturn_msg("정상");
        response.setList(List.of(etf, stock));
        when(restTemplate.postForEntity(anyString(), org.mockito.ArgumentMatchers.any(), eq(KiwoomStockResponse.class)))
                .thenReturn(ResponseEntity.ok(response));

        KiwoomStockService service = new KiwoomStockService(properties, tokenService, restTemplate, redisTemplate);
        service.syncAllStockCodes();

        ArgumentCaptor<Map<String, String>> mapCaptor = ArgumentCaptor.forClass(Map.class);
        org.mockito.Mockito.verify(hashOps, org.mockito.Mockito.atLeastOnce())
                .putAll(eq("stock:code_map:sync"), mapCaptor.capture());

        Map<String, String> stored = mapCaptor.getAllValues().stream()
                .flatMap(m -> m.entrySet().stream())
                .collect(java.util.stream.Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue, (a, b) -> a));
        assertEquals("KODEX 인버스", stored.get("114800"));
        assertEquals("삼성전자", stored.get("005930"));
        org.mockito.Mockito.verify(redisTemplate)
                .rename("stock:code_map:sync", "stock:code_map");
    }

    @Test
    void transientNetworkFailureIsRetriedAndBothMarketsComplete() {
        KiwoomProperties properties = new KiwoomProperties();
        properties.getApi().setBaseUrl("https://api.kiwoom.com");

        RestTemplate restTemplate = mock(RestTemplate.class);
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redisTemplate.opsForHash()).thenReturn(hashOps);
        when(tokenService.getBearerToken()).thenReturn("Bearer abc123");

        KiwoomStockResponse response = new KiwoomStockResponse();
        response.setReturn_code("0");
        response.setReturn_msg("normal");
        KiwoomStockItem item = new KiwoomStockItem();
        item.setCode("005930");
        item.setName("삼성전자");
        response.setList(List.of(item));
        when(restTemplate.postForEntity(anyString(), org.mockito.ArgumentMatchers.any(), eq(KiwoomStockResponse.class)))
                .thenThrow(new ResourceAccessException("Unexpected end of file from server"))
                .thenReturn(ResponseEntity.ok(response), ResponseEntity.ok(response));

        new KiwoomStockService(properties, tokenService, restTemplate, redisTemplate)
                .syncAllStockCodes();

        org.mockito.Mockito.verify(restTemplate, org.mockito.Mockito.times(3))
                .postForEntity(anyString(), org.mockito.ArgumentMatchers.any(), eq(KiwoomStockResponse.class));
    }

    @Test
    void failedSecondMarketLeavesLiveRedisMapUntouched() {
        KiwoomProperties properties = new KiwoomProperties();
        properties.getApi().setBaseUrl("https://api.kiwoom.com");

        RestTemplate restTemplate = mock(RestTemplate.class);
        when(tokenService.getBearerToken()).thenReturn("Bearer abc123");

        KiwoomStockItem item = new KiwoomStockItem();
        item.setCode("005930");
        item.setName("삼성전자");
        KiwoomStockResponse firstMarket = new KiwoomStockResponse();
        firstMarket.setReturn_code("0");
        firstMarket.setList(List.of(item));

        when(restTemplate.postForEntity(anyString(), org.mockito.ArgumentMatchers.any(), eq(KiwoomStockResponse.class)))
                .thenReturn(ResponseEntity.ok(firstMarket))
                .thenThrow(new ResourceAccessException("second market EOF"));

        KiwoomStockService service = new KiwoomStockService(
                properties, tokenService, restTemplate, redisTemplate);

        assertThrows(ResourceAccessException.class, service::syncAllStockCodes);
        org.mockito.Mockito.verify(redisTemplate, org.mockito.Mockito.never())
                .delete("stock:code_map:sync");
        org.mockito.Mockito.verify(redisTemplate, org.mockito.Mockito.never())
                .rename("stock:code_map:sync", "stock:code_map");
    }
}
