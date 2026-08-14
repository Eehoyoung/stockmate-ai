package org.invest.apiorchestrator.controller;

import org.invest.apiorchestrator.repository.StrategyParamHistoryRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.CandidateService;
import org.invest.apiorchestrator.service.EconomicCalendarService;
import org.invest.apiorchestrator.service.NewsControlService;
import org.invest.apiorchestrator.service.OperationsHealthService;
import org.invest.apiorchestrator.service.OvernightScoringService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.SignalService;
import org.invest.apiorchestrator.service.StrategyExecutionOwnership;
import org.invest.apiorchestrator.service.StrategyService;
import org.invest.apiorchestrator.service.TokenService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** S8/S9/S11/S13~S16 대시보드 수동 실행 프록시(/api/trading/strategy/{code}/run) 검증. */
@ExtendWith(MockitoExtension.class)
class TradingControllerPythonStrategyProxyTests {

    @Mock StrategyService strategyService;
    @Mock SignalService signalService;
    @Mock CandidateService candidateService;
    @Mock TokenService tokenService;
    @Mock EconomicCalendarService calendarService;
    @Mock NewsControlService newsControlService;
    @Mock RedisMarketDataService redisMarketDataService;
    @Mock OvernightScoringService overnightScoringService;
    @Mock TradingSignalRepository signalRepository;
    @Mock StringRedisTemplate redis;
    @Mock StrategyParamHistoryRepository strategyParamHistoryRepository;
    @Mock JdbcTemplate jdbcTemplate;
    @Mock OperationsHealthService operationsHealthService;
    @Mock StrategyExecutionOwnership strategyExecutionOwnership;
    @Mock WebClient internalWebClient;

    @InjectMocks TradingController controller;

    @Test
    void unsupportedCodeIsRejectedBeforeCallingAiEngine() {
        var response = controller.runPythonOwnedStrategy("s1");

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals("error", response.getBody().get("status"));
        verifyNoInteractions(internalWebClient);
    }

    @Test
    void supportedCodeProxiesToAiEngineAndReturnsBody() {
        ReflectionTestUtils.setField(controller, "aiEngineUrl", "http://ai-engine:8082");
        WebClient.RequestBodyUriSpec uriSpec = mock(WebClient.RequestBodyUriSpec.class);
        WebClient.RequestBodySpec bodySpec = mock(WebClient.RequestBodySpec.class);
        WebClient.ResponseSpec responseSpec = mock(WebClient.ResponseSpec.class);
        when(internalWebClient.post()).thenReturn(uriSpec);
        when(uriSpec.uri(anyString())).thenReturn(bodySpec);
        when(bodySpec.retrieve()).thenReturn(responseSpec);
        when(responseSpec.bodyToMono(Map.class))
                .thenReturn(Mono.just(Map.of("strategy", "S16_ACCUMULATION_SHADOW", "published", 2)));

        var response = controller.runPythonOwnedStrategy("S16");

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("S16_ACCUMULATION_SHADOW", response.getBody().get("strategy"));
        assertEquals(2, response.getBody().get("published"));
    }

    @Test
    void aiEngineFailureReturns500WithoutThrowing() {
        ReflectionTestUtils.setField(controller, "aiEngineUrl", "http://ai-engine:8082");
        WebClient.RequestBodyUriSpec uriSpec = mock(WebClient.RequestBodyUriSpec.class);
        WebClient.RequestBodySpec bodySpec = mock(WebClient.RequestBodySpec.class);
        WebClient.ResponseSpec responseSpec = mock(WebClient.ResponseSpec.class);
        when(internalWebClient.post()).thenReturn(uriSpec);
        when(uriSpec.uri(anyString())).thenReturn(bodySpec);
        when(bodySpec.retrieve()).thenReturn(responseSpec);
        when(responseSpec.bodyToMono(Map.class))
                .thenReturn(Mono.error(new RuntimeException("connection refused")));

        var response = controller.runPythonOwnedStrategy("s8");

        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, response.getStatusCode());
        assertEquals("error", response.getBody().get("status"));
    }
}
