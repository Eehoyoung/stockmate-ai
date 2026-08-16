package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.TossInvestProperties;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.LocalDate;
import java.util.Optional;

/** Toss 국내 장 운영정보를 날짜별 OPEN/CLOSED 값으로 정규화한다. */
@Slf4j
@Service
@RequiredArgsConstructor
public class TossMarketCalendarService {

    public static final String KEY_PREFIX = "market:kr:calendar:";
    private static final Duration CACHE_TTL = Duration.ofDays(14);

    private final WebClient tossWebClient;
    private final TossInvestProperties properties;
    private final TossAuthService tossAuthService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    public Optional<Boolean> cachedTradingDay(LocalDate date) {
        try {
            String value = redis.opsForValue().get(KEY_PREFIX + date);
            if ("OPEN".equals(value)) return Optional.of(true);
            if ("CLOSED".equals(value)) return Optional.of(false);
        } catch (Exception e) {
            log.warn("[MarketCalendar] cache read failed date={}: {}", date, e.getMessage());
        }
        return Optional.empty();
    }

    /**
     * 캐시가 없을 때만 Toss를 조회한다. allowTokenIssue=false이면 기존 토큰이 없을 경우
     * 네트워크 호출 없이 UNKNOWN을 반환한다.
     */
    public Optional<Boolean> ensureTradingDay(LocalDate date, boolean allowTokenIssue) {
        Optional<Boolean> cached = cachedTradingDay(date);
        if (cached.isPresent() || !properties.isEnabled()) return cached;

        String cachedToken = tossAuthService.getCachedToken();
        final String token = cachedToken == null && allowTokenIssue
                ? tossAuthService.getValidToken() : cachedToken;
        if (token == null) return Optional.empty();

        try {
            String responseBody = tossWebClient.get()
                    .uri(uri -> uri.path("/api/v1/market-calendar/KR")
                            .queryParam("date", date).build())
                    .headers(headers -> headers.setBearerAuth(token))
                    .retrieve()
                    .bodyToMono(String.class)
                    .block(Duration.ofSeconds(15));
            JsonNode response = responseBody == null ? null : objectMapper.readTree(responseBody);
            JsonNode today = response == null ? null : response.path("result").path("today");
            if (today == null || today.isMissingNode() || !date.toString().equals(today.path("date").asText())) {
                log.warn("[MarketCalendar] invalid response date={}", date);
                return Optional.empty();
            }
            boolean open = !today.path("integrated").isMissingNode()
                    && !today.path("integrated").isNull()
                    && !today.path("integrated").path("regularMarket").isMissingNode()
                    && !today.path("integrated").path("regularMarket").isNull();
            redis.opsForValue().set(KEY_PREFIX + date, open ? "OPEN" : "CLOSED", CACHE_TTL);
            log.info("[MarketCalendar] date={} status={} source=TOSS", date, open ? "OPEN" : "CLOSED");
            return Optional.of(open);
        } catch (Exception e) {
            log.warn("[MarketCalendar] lookup failed date={}: {}", date, e.getMessage());
            return Optional.empty();
        }
    }
}
