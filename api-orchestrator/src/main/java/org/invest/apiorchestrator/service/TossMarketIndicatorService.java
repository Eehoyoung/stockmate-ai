package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.res.TossResponses;
import org.invest.apiorchestrator.exception.TossApiException;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.function.Supplier;

/**
 * 토스증권 Market Indicators 그룹(코스피/코스닥/국채) 조회.
 * 심볼 카탈로그: KOSPI, KOSDAQ, KR_BOND_2Y/3Y/5Y/10Y/20Y/30Y (그 외는 400 unsupported-symbol).
 *
 * <p>이 서비스는 스케줄러에서만 호출되며, 장애가 전체 트레이딩 루프를 막지 않도록
 * 모든 메서드가 예외를 삼키고 null 을 반환한다 — 호출부(TossMarketScheduler)가
 * null 을 "이번 주기 스킵"으로 처리한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TossMarketIndicatorService {

    private final WebClient tossWebClient;
    private final TossAuthService tossAuthService;

    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(10);

    public TossResponses.MarketIndicatorPricesResponse getPrices(String symbolsCsv) {
        return callWithTokenRetry(() -> tossWebClient.get()
                .uri(uriBuilder -> uriBuilder.path("/api/v1/market-indicators/prices")
                        .queryParam("symbols", symbolsCsv)
                        .build())
                .header("Authorization", tossAuthService.getBearerToken())
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, this::handle4xx)
                .bodyToMono(TossResponses.MarketIndicatorPricesResponse.class)
                .block(REQUEST_TIMEOUT), "market-indicators/prices");
    }

    public TossResponses.MarketIndicatorCandlesResponse getCandles(String symbol, String interval, int count) {
        return callWithTokenRetry(() -> tossWebClient.get()
                .uri(uriBuilder -> uriBuilder.path("/api/v1/market-indicators/{symbol}/candles")
                        .queryParam("interval", interval)
                        .queryParam("count", count)
                        .build(symbol))
                .header("Authorization", tossAuthService.getBearerToken())
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, this::handle4xx)
                .bodyToMono(TossResponses.MarketIndicatorCandlesResponse.class)
                .block(REQUEST_TIMEOUT), "market-indicators/candles[" + symbol + "]");
    }

    public TossResponses.MarketIndicatorInvestorTradingResponse getInvestorTrading(String symbol, String interval, int count) {
        return callWithTokenRetry(() -> tossWebClient.get()
                .uri(uriBuilder -> uriBuilder.path("/api/v1/market-indicators/{symbol}/investor-trading")
                        .queryParam("interval", interval)
                        .queryParam("count", count)
                        .build(symbol))
                .header("Authorization", tossAuthService.getBearerToken())
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, this::handle4xx)
                .bodyToMono(TossResponses.MarketIndicatorInvestorTradingResponse.class)
                .block(REQUEST_TIMEOUT), "market-indicators/investor-trading[" + symbol + "]");
    }

    private Mono<Throwable> handle4xx(org.springframework.web.reactive.function.client.ClientResponse response) {
        int status = response.statusCode().value();
        if (status == 401) {
            return Mono.error(new TokenExpiredSignal());
        }
        if (status == 429) {
            String retryAfter = response.headers().asHttpHeaders().getFirst("Retry-After");
            log.warn("[Toss] 429 rate limit, Retry-After={}s — 이번 주기 스킵", retryAfter);
        }
        return response.bodyToMono(String.class)
                .defaultIfEmpty("")
                .flatMap(body -> Mono.error(new TossApiException("Toss API 오류 status=" + status + " body=" + body)));
    }

    /** 401(토큰 만료)일 때 1회 재발급 후 재시도, 그 외 실패는 삼키고 null 반환 */
    private <T> T callWithTokenRetry(Supplier<T> call, String label) {
        try {
            return call.get();
        } catch (TokenExpiredSignal expired) {
            log.info("[Toss] 401 감지 — 토큰 재발급 후 재시도 [{}]", label);
            try {
                tossAuthService.refreshToken();
                return call.get();
            } catch (Exception retryEx) {
                log.warn("[Toss] 재시도 실패 [{}]: {}", label, retryEx.getMessage());
                return null;
            }
        } catch (Exception e) {
            log.debug("[Toss] 호출 실패 [{}]: {}", label, e.getMessage());
            return null;
        }
    }

    /** onStatus 핸들러가 401을 이 신호로 매핑해 던지면 callWithTokenRetry가 재시도 여부를 구분한다 */
    private static class TokenExpiredSignal extends RuntimeException {
        TokenExpiredSignal() { super("toss token expired"); }
    }
}
