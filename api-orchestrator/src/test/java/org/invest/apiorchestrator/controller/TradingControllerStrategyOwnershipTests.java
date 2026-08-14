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
import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class TradingControllerStrategyOwnershipTests {

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
    void pythonOwnerBlocksEveryJavaPublishingEndpointBeforeCandidateOrEvaluationWork() {
        when(strategyExecutionOwnership.javaOwnsEvaluation()).thenReturn(false);
        when(strategyExecutionOwnership.owner()).thenReturn(StrategyExecutionOwnership.Owner.PYTHON);

        var responses = List.of(
                controller.runS1("000"),
                controller.runS3("001"),
                controller.runS4("000"),
                controller.runS5("001"),
                controller.runS6(),
                controller.runS10(),
                controller.runS12()
        );

        responses.forEach(response -> {
            assertEquals(HttpStatus.CONFLICT, response.getStatusCode());
            assertEquals("blocked", response.getBody().get("status"));
            assertEquals("PYTHON", response.getBody().get("owner"));
            assertEquals(0, response.getBody().get("published"));
        });
        verifyNoInteractions(candidateService, strategyService, signalService);
    }

    @Test
    void javaOwnerAllowsJavaEvaluationAndPublishingPath() {
        when(strategyExecutionOwnership.javaOwnsEvaluation()).thenReturn(true);
        when(strategyService.scanInstFrgn("001")).thenReturn(List.of());

        var response = controller.runS3("001");

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(0, response.getBody().get("published"));
        verify(strategyService).scanInstFrgn("001");
        verify(signalService).processSignals(List.of());
    }
}
