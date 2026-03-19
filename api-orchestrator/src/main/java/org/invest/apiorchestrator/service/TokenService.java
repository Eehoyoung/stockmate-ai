package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.KiwoomToken;
import org.invest.apiorchestrator.dto.req.TokenRequest;
import org.invest.apiorchestrator.dto.res.TokenResponse;
import org.invest.apiorchestrator.exception.KiwoomApiException;
import org.invest.apiorchestrator.repository.KiwoomTokenRepository;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.concurrent.locks.ReentrantLock;

@Slf4j
@Service
@RequiredArgsConstructor
public class TokenService {

    private final WebClient kiwoomWebClient;
    private final KiwoomProperties properties;
    private final KiwoomTokenRepository tokenRepository;
    private final StringRedisTemplate stringRedisTemplate;

    private static final String REDIS_TOKEN_KEY = "kiwoom:token";
    private static final String TOKEN_ISSUE_URL = "/oauth2/token";

    private final ReentrantLock tokenLock = new ReentrantLock();

    /**
     * 유효한 액세스 토큰 반환 (캐시 우선 → DB → 신규 발급)
     */
    public String getValidToken() {
        // 1. Redis 캐시에서 조회
        String cached = stringRedisTemplate.opsForValue().get(REDIS_TOKEN_KEY);
        if (cached != null && !cached.isBlank()) {
            return cached;
        }

        // 2. 락 획득 후 DB 조회 / 신규 발급
        tokenLock.lock();
        try {
            // double-check
            cached = stringRedisTemplate.opsForValue().get(REDIS_TOKEN_KEY);
            if (cached != null && !cached.isBlank()) {
                return cached;
            }

            return refreshToken();
        } finally {
            tokenLock.unlock();
        }
    }

    /**
     * 토큰 강제 갱신
     */
    @Transactional
    public String refreshToken() {
        log.info("키움 액세스 토큰 발급 요청");

        TokenRequest req = TokenRequest.builder()
                .appKey(properties.getApi().getAppKey())
                .secretKey(properties.getApi().getSecretKey())
                .build();

        TokenResponse resp = kiwoomWebClient.post()
                .uri(TOKEN_ISSUE_URL)
                .bodyValue(req)
                .retrieve()
                .bodyToMono(TokenResponse.class)
                .block(Duration.ofSeconds(15));

        if (resp == null || !resp.isSuccess()) {
            String msg = resp != null ? resp.getReturnMsg() : "응답 없음";
            throw new KiwoomApiException("토큰 발급 실패: " + msg);
        }

        // 기존 활성 토큰 비활성화
        tokenRepository.deactivateAllTokens();

        // 새 토큰 저장
        int ttlMinutes = properties.getApi().getTokenTtlMinutes();
        KiwoomToken token = KiwoomToken.builder()
                .accessToken(resp.getAccessToken())
                .tokenType(resp.getTokenType() != null ? resp.getTokenType() : "Bearer")
                .expiresAt(LocalDateTime.now().plusMinutes(ttlMinutes))
                .active(true)
                .build();
        tokenRepository.save(token);

        // Redis 캐싱 (만료 10분 전 갱신되도록 TTL 단축)
        long redisTtl = ttlMinutes - 15L;
        stringRedisTemplate.opsForValue()
                .set(REDIS_TOKEN_KEY, resp.getAccessToken(), Duration.ofMinutes(redisTtl));

        log.info("토큰 발급 완료 - 유효시간: {}분", ttlMinutes);
        return resp.getAccessToken();
    }

    /**
     * Bearer 접두어 포함 토큰 반환
     */
    public String getBearerToken() {
        return "Bearer " + getValidToken();
    }

    /**
     * 토큰 폐기
     */
    @Transactional
    public void revokeToken() {
        stringRedisTemplate.delete(REDIS_TOKEN_KEY);
        tokenRepository.deactivateAllTokens();
        log.info("토큰 폐기 완료");
    }
}
