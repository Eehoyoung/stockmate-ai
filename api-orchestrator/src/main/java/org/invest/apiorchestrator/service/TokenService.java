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
import java.time.format.DateTimeFormatter;
import org.invest.apiorchestrator.util.KstClock;
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
    private static final DateTimeFormatter EXPIRES_DT_FMT = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

    private final ReentrantLock tokenLock = new ReentrantLock();

    /**
     * 유효한 액세스 토큰 반환 (캐시 우선 → DB → 신규 발급)
     */
    public String getValidToken() {
        // 1. Redis 캐시에서 조회 (Redis 장애 시 무시)
        try {
            String cached = stringRedisTemplate.opsForValue().get(REDIS_TOKEN_KEY);
            if (cached != null && !cached.isBlank()) {
                return cached;
            }
        } catch (Exception e) {
            log.warn("Redis 캐시 조회 실패 (무시하고 DB 조회 진행): {}", e.getMessage());
        }

        // 2. 락 획득 후 DB 조회 / 신규 발급
        tokenLock.lock();
        try {
            // double-check (Redis 장애 시 무시)
            try {
                String cached = stringRedisTemplate.opsForValue().get(REDIS_TOKEN_KEY);
                if (cached != null && !cached.isBlank()) {
                    return cached;
                }
            } catch (Exception e) {
                log.warn("Redis double-check 실패 (무시하고 신규 발급 진행): {}", e.getMessage());
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
                .secretKey(properties.getApi().getAppSecret())
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

        // expires_dt(yyyyMMddHHmmss) 파싱, 실패 시 설정값 fallback
        LocalDateTime expiresAt;
        long redisTtlMinutes;
        String expiresDt = resp.getExpiresDt();
        if (expiresDt != null && expiresDt.length() == 14) {
            expiresAt = LocalDateTime.parse(expiresDt, EXPIRES_DT_FMT);
            redisTtlMinutes = Duration.between(KstClock.now(), expiresAt).toMinutes() - 15;
        } else {
            int ttlMinutes = properties.getApi().getTokenTtlMinutes();
            expiresAt = KstClock.now().plusMinutes(ttlMinutes);
            redisTtlMinutes = ttlMinutes - 15L;
        }

        // 새 토큰 저장
        KiwoomToken token = KiwoomToken.builder()
                .accessToken(resp.getAccessToken())
                .tokenType(resp.getTokenType() != null ? resp.getTokenType() : "Bearer")
                .expiresAt(expiresAt)
                .active(true)
                .build();
        tokenRepository.save(token);

        // Redis 캐싱 (만료 15분 전 갱신되도록 TTL 단축, Redis 장애 시 무시)
        try {
            stringRedisTemplate.opsForValue()
                    .set(REDIS_TOKEN_KEY, resp.getAccessToken(), Duration.ofMinutes(redisTtlMinutes));
        } catch (Exception e) {
            log.warn("Redis 토큰 캐싱 실패 (DB에는 저장됨): {}", e.getMessage());
        }

        log.info("토큰 발급 완료 - 만료: {}", expiresAt);
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
        try {
            stringRedisTemplate.delete(REDIS_TOKEN_KEY);
        } catch (Exception e) {
            log.warn("Redis 토큰 삭제 실패 (무시): {}", e.getMessage());
        }
        tokenRepository.deactivateAllTokens();
        log.info("토큰 폐기 완료");
    }
}
