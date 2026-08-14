package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.TossInvestProperties;
import org.invest.apiorchestrator.dto.res.TossResponses;
import org.invest.apiorchestrator.exception.TossApiException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.concurrent.locks.ReentrantLock;

/**
 * 토스증권 OAuth2 Client Credentials 토큰 발급/캐싱.
 *
 * <p>토스는 client 당 유효 토큰이 1개이며, 재발급 시 이전 토큰이 즉시 무효화된다
 * (docs/toss_invest_openapi_claude_required.md 참조). 따라서 Kiwoom 토큰과 동일하게
 * Java(api-orchestrator)가 유일한 발급 주체이며, Redis {@code toss:token} 키를
 * 단일 source of truth로 삼는다. ai-engine(Python)은 이 키를 읽기만 하고 절대
 * 자체 발급하지 않는다 — 그렇지 않으면 두 프로세스가 서로의 토큰을 무효화시킨다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TossAuthService {

    private final WebClient tossWebClient;
    private final TossInvestProperties properties;
    private final StringRedisTemplate stringRedisTemplate;

    private static final String REDIS_TOKEN_KEY = "toss:token";
    private static final String TOKEN_ISSUE_URL = "/oauth2/token";
    /** 만료 15분 전 갱신되도록 캐시 TTL을 짧게 잡는다 (Kiwoom TokenService와 동일 여유) */
    private static final long EXPIRY_BUFFER_SECONDS = 900;

    private final ReentrantLock tokenLock = new ReentrantLock();

    public String getValidToken() {
        try {
            String cached = stringRedisTemplate.opsForValue().get(REDIS_TOKEN_KEY);
            if (cached != null && !cached.isBlank()) {
                return cached;
            }
        } catch (Exception e) {
            log.warn("[Toss] Redis 토큰 캐시 조회 실패: {}", e.getMessage());
        }

        tokenLock.lock();
        try {
            try {
                String cached = stringRedisTemplate.opsForValue().get(REDIS_TOKEN_KEY);
                if (cached != null && !cached.isBlank()) {
                    return cached;
                }
            } catch (Exception e) {
                log.warn("[Toss] Redis 토큰 double-check 실패: {}", e.getMessage());
            }
            return refreshToken();
        } finally {
            tokenLock.unlock();
        }
    }

    public String refreshToken() {
        if (properties.getClientId() == null || properties.getClientId().isBlank()
                || properties.getClientSecret() == null || properties.getClientSecret().isBlank()) {
            throw new TossApiException("토스 client_id/client_secret 미설정");
        }

        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("grant_type", "client_credentials");
        form.add("client_id", properties.getClientId());
        form.add("client_secret", properties.getClientSecret());

        TossResponses.OAuth2TokenResponse resp;
        try {
            resp = tossWebClient.post()
                    .uri(TOKEN_ISSUE_URL)
                    .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                    .body(BodyInserters.fromFormData(form))
                    .retrieve()
                    .bodyToMono(TossResponses.OAuth2TokenResponse.class)
                    .block(Duration.ofSeconds(15));
        } catch (Exception e) {
            throw new TossApiException("토스 토큰 발급 실패: " + e.getMessage(), e);
        }

        if (resp == null || resp.getAccessToken() == null || resp.getAccessToken().isBlank()) {
            throw new TossApiException("토스 토큰 발급 응답 없음");
        }

        long expiresIn = resp.getExpiresIn() != null ? resp.getExpiresIn() : 86_400L;
        long ttlSeconds = Math.max(60, expiresIn - EXPIRY_BUFFER_SECONDS);

        try {
            stringRedisTemplate.opsForValue()
                    .set(REDIS_TOKEN_KEY, resp.getAccessToken(), Duration.ofSeconds(ttlSeconds));
        } catch (Exception e) {
            log.warn("[Toss] Redis 토큰 캐싱 실패: {}", e.getMessage());
        }

        log.info("[Toss] 토큰 발급 완료 - TTL {}초", ttlSeconds);
        return resp.getAccessToken();
    }

    public String getBearerToken() {
        return "Bearer " + getValidToken();
    }
}
