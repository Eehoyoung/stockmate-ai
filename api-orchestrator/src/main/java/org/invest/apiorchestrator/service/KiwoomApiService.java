package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomRateLimiter;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.exception.KiwoomApiException;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.util.retry.Retry;

import java.time.Duration;

@Slf4j
@Service
@RequiredArgsConstructor
public class KiwoomApiService {
    private final WebClient kiwoomWebClient;
    private final TokenService tokenService;
    private final KiwoomRateLimiter rateLimiter;

    private static final int MAX_RETRIES = 3;
    /**
     * 기본 재시도 지연 – 1700 Rate Limit 발생 시에도 이 딜레이 적용.
     * Rate Limiter 토큰 보충 주기(333ms)보다 충분히 길게 설정.
     */
    private static final Duration RETRY_DELAY = Duration.ofMillis(1200);
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(15);
    private static final String HEADER_API_ID = "api-id";
    private static final String HEADER_AUTHORIZATION = "authorization";
    private static final String HEADER_CONTENT_TYPE = "Content-Type";
    private static final String CONTENT_TYPE_JSON_UTF8 = "application/json;charset=UTF-8";
    private static final String HEADER_CONT_YN = "cont-yn";
    private static final String HEADER_NEXT_KEY = "next-key";

    /**
     * 키움 REST API POST 호출 공통 메서드.
     *
     * <p><b>Rate Limiter 주의</b>: retryWhen 재시도 시에도 rateLimiter.acquire() 가
     * 반드시 다시 호출되도록 Mono.defer() 로 전체 요청 팩토리를 감쌌습니다.
     *
     * @param apiId    TR명 (예: ka10046)
     * @param endpoint URL 경로 (예: /api/dostk/mrkcond)
     * @param body     요청 바디 DTO
     * @param respType 응답 타입
     */
    public <T> T post(String apiId, String endpoint, Object body, Class<T> respType) {
        T result = Mono.defer(() -> buildPostMono(apiId, endpoint, body, respType))
                .retryWhen(Retry.backoff(MAX_RETRIES, RETRY_DELAY)
                        .filter(e -> !(e instanceof KiwoomApiException))
                        .doBeforeRetry(rs -> log.warn("API 재시도 [{}] attempt={}", apiId, rs.totalRetries() + 1)))
                .doOnError(e -> log.error("API 호출 최종 실패 [{}]: {}", apiId, e.getMessage()))
                .block(REQUEST_TIMEOUT);

        if (result == null) {
            throw new KiwoomApiException("API 응답 없음 [" + apiId + "]");
        }
        return result;
    }

    /**
     * 연속조회 지원 POST 호출 (cont-yn, next-key 자동 처리).
     * - 단순 단건 조회는 post() 사용
     */
    public <T> T postWithContinuation(String apiId, String endpoint,
                                      Object body, Class<T> respType,
                                      String contYn, String nextKey) {
        T result = Mono.defer(() -> buildPostWithContMono(apiId, endpoint, body, respType, contYn, nextKey))
                .retryWhen(Retry.backoff(MAX_RETRIES, RETRY_DELAY)
                        .filter(e -> !(e instanceof KiwoomApiException))
                        .doBeforeRetry(rs -> log.warn("API 재시도(연속조회) [{}] attempt={}", apiId, rs.totalRetries() + 1)))
                .doOnError(e -> log.error("API 호출 최종 실패(연속조회) [{}]: {}", apiId, e.getMessage()))
                .block(REQUEST_TIMEOUT);

        if (result == null) {
            throw new KiwoomApiException("API 응답 없음 [" + apiId + "]");
        }
        return result;
    }

    // ── 내부 Mono 팩토리 (Mono.defer 내부에서 호출 → 재시도마다 acquire 재실행) ──

    private <T> Mono<T> buildPostMono(String apiId, String endpoint, Object body, Class<T> respType) {
        WebClient.RequestBodySpec spec = createPostSpec(apiId, endpoint);
        return spec.bodyValue(body)
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, response -> on4xx(apiId, response))
                .bodyToMono(respType);
    }

    private <T> Mono<T> buildPostWithContMono(String apiId, String endpoint,
                                               Object body, Class<T> respType,
                                               String contYn, String nextKey) {
        WebClient.RequestBodySpec spec = createPostSpec(apiId, endpoint);
        spec = applyContinuationHeaders(spec, contYn, nextKey);
        return spec.bodyValue(body)
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, response -> on4xx(apiId, response))
                .bodyToMono(respType);
    }

    // 공통 POST 스펙 생성 (인증/공통 헤더 포함, Rate Limiter 적용)
    // Mono.defer 내부에서 호출되므로 재시도마다 acquire() 가 실행됨
    private WebClient.RequestBodySpec createPostSpec(String apiId, String endpoint) {
        rateLimiter.acquire(); // 초당 3회 제한 (KiwoomRateLimiter 설정값)
        String bearerToken = tokenService.getBearerToken();
        return kiwoomWebClient.post()
                .uri(endpoint)
                .header(HEADER_API_ID, apiId)
                .header(HEADER_AUTHORIZATION, bearerToken)
                .header(HEADER_CONTENT_TYPE, CONTENT_TYPE_JSON_UTF8);
    }

    // 연속조회 헤더 적용
    private WebClient.RequestBodySpec applyContinuationHeaders(WebClient.RequestBodySpec spec, String contYn, String nextKey) {
        if ("Y".equals(contYn) && nextKey != null) {
            return spec.header(HEADER_CONT_YN, contYn).header(HEADER_NEXT_KEY, nextKey);
        }
        return spec;
    }

    // 4xx 에러 처리: 401은 토큰 갱신 후 재시도 유도, 그 외는 즉시 실패
    private Mono<Throwable> on4xx(String apiId, org.springframework.web.reactive.function.client.ClientResponse clientResponse) {
        return clientResponse.bodyToMono(String.class)
                .flatMap(bodyText -> {
                    int status = clientResponse.statusCode().value();
                    log.error("4xx 오류 [{}] status={} body={}", apiId, status, bodyText);
                    if (status == 401) {
                        // 토큰 만료: 갱신 후 재시도 허용 예외로 전달
                        tokenService.refreshToken();
                        return Mono.error(new IllegalStateException("Token refreshed. Retry request."));
                    }
                    // 8005 응답 코드 처리 (토큰 만료 – body 에 코드가 담기는 경우)
                    if (bodyText != null && bodyText.contains("8005")) {
                        log.warn("8005 토큰 만료 감지 [{}] – 토큰 갱신 후 재시도", apiId);
                        tokenService.refreshToken();
                        return Mono.error(new IllegalStateException("8005 Token expired. Retry request."));
                    }
                    // 1700 Rate Limit: 재시도 허용 예외 (Mono.defer + acquire 로 재시도 전 토큰 획득)
                    if (bodyText != null && bodyText.contains("1700")) {
                        log.warn("1700 Rate Limit [{}] – {}ms 후 재시도 예정", apiId, RETRY_DELAY.toMillis());
                        return Mono.error(new IllegalStateException("1700 Rate limit. Retry request."));
                    }
                    return Mono.error(new KiwoomApiException("API 오류 [" + apiId + "]: " + bodyText));
                });
    }

    // ─────────────────────────────────────────────────────────────
    // 편의 메서드 – 신규 API
    // ─────────────────────────────────────────────────────────────

    private static final String RKINFO_PATH  = "/api/dostk/rkinfo";
    private static final String STKINFO_PATH = "/api/dostk/stkinfo";

    /** ka10029 예상체결등락률상위 */
    public KiwoomApiResponses.ExpCntrFluRtUpperResponse fetchKa10029(
            StrategyRequests.ExpCntrFluRtUpperRequest req) {
        return post("ka10029", RKINFO_PATH, req,
                KiwoomApiResponses.ExpCntrFluRtUpperResponse.class);
    }

    /** ka10030 당일거래량상위 */
    public KiwoomApiResponses.TdyTrdeQtyUpperResponse fetchKa10030(
            StrategyRequests.TdyTrdeQtyUpperRequest req) {
        return post("ka10030", RKINFO_PATH, req,
                KiwoomApiResponses.TdyTrdeQtyUpperResponse.class);
    }

    /** ka10023 거래량급증 */
    public KiwoomApiResponses.TrdeQtySdninResponse fetchKa10023(
            StrategyRequests.TrdeQtySdninRequest req) {
        return post("ka10023", RKINFO_PATH, req,
                KiwoomApiResponses.TrdeQtySdninResponse.class);
    }

    /** ka10019 가격급등락 */
    public KiwoomApiResponses.PricJmpFluResponse fetchKa10019(
            StrategyRequests.PricJmpFluRequest req) {
        return post("ka10019", STKINFO_PATH, req,
                KiwoomApiResponses.PricJmpFluResponse.class);
    }

    /** ka10020 호가잔량상위 */
    public KiwoomApiResponses.BidReqUpperResponse fetchKa10020(
            StrategyRequests.BidReqUpperRequest req) {
        return post("ka10020", RKINFO_PATH, req,
                KiwoomApiResponses.BidReqUpperResponse.class);
    }

    /** ka10001 주식기본정보 (전일종가 조회) */
    public KiwoomApiResponses.StkBasicInfoResponse fetchKa10001(String stkCd) {
        return post("ka10001", STKINFO_PATH,
                StrategyRequests.StkBasicInfoRequest.builder().stkCd(stkCd).build(),
                KiwoomApiResponses.StkBasicInfoResponse.class);
    }

    /** ka10081 주식일봉차트 (52주 신고가 확인용) */
    public KiwoomApiResponses.DailyCandleResponse fetchKa10081(String stkCd) {
        return post("ka10081", "/api/dostk/chart",
                StrategyRequests.DailyCandleRequest.builder().stkCd(stkCd).build(),
                KiwoomApiResponses.DailyCandleResponse.class);
    }
}
