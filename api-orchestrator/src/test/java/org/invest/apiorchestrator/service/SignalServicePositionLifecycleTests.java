package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.domain.PortfolioConfig;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.CandidatePoolHistoryRepository;
import org.invest.apiorchestrator.repository.PortfolioConfigRepository;
import org.invest.apiorchestrator.repository.RiskEventRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verifyNoInteractions;
import java.util.Optional;

class SignalServicePositionLifecycleTests {

    @Test
    void publishedSignalDoesNotFabricateExecutionOrQuantity() {
        SignalService service = new SignalService(
                mock(TradingSignalRepository.class),
                mock(RedisMarketDataService.class),
                mock(CandidateService.class),
                mock(KiwoomProperties.class),
                new ObjectMapper(),
                mock(PortfolioConfigRepository.class),
                mock(RiskEventRepository.class),
                mock(CandidatePoolHistoryRepository.class));
        TradingSignalDto dto = TradingSignalDto.builder()
                .stkCd("005930")
                .strategy(TradingSignal.StrategyType.S1_GAP_OPEN)
                .entryPrice(70000.0)
                .targetPct(3.0)
                .stopPct(-2.0)
                .build();

        TradingSignal signal = ReflectionTestUtils.invokeMethod(service, "buildSignalEntity", dto);

        assertNotNull(signal);
        assertEquals(TradingSignal.SignalStatus.SENT, signal.getSignalStatus());
        assertNull(signal.getPositionStatus());
        assertNull(signal.getEntryAt());
        assertNull(signal.getEntryQty());
        assertFalse(signal.getMonitorEnabled());
    }

    @Test
    void liveFamilyRoutingBlocksThemeExposureAtPortfolioLimit() {
        TradingSignalRepository signalRepository = mock(TradingSignalRepository.class);
        RedisMarketDataService redisService = mock(RedisMarketDataService.class);
        PortfolioConfigRepository portfolioRepository = mock(PortfolioConfigRepository.class);
        CandidateService candidateService = mock(CandidateService.class);
        when(redisService.isSignalDuplicate("005930", "S4_BIG_CANDLE")).thenReturn(false);
        when(redisService.tryAcquireStockCooldown("005930", 30)).thenReturn(true);
        when(redisService.incrementDailySignalCount()).thenReturn(1L);
        when(portfolioRepository.findSingleton()).thenReturn(Optional.of(
                PortfolioConfig.builder().maxPositionCount(5).maxSectorPct(new java.math.BigDecimal("30")).build()));
        when(signalRepository.existsActivePosition("005930")).thenReturn(false);
        when(signalRepository.countActivePositions()).thenReturn(1L);
        when(signalRepository.countActivePositionsByTheme("반도체")).thenReturn(1L);
        RiskEventRepository riskEvents = mock(RiskEventRepository.class);
        SignalService service = new SignalService(
                signalRepository, redisService, candidateService, new KiwoomProperties(),
                new ObjectMapper(), portfolioRepository, riskEvents,
                mock(CandidatePoolHistoryRepository.class));
        TradingSignalDto dto = TradingSignalDto.builder()
                .stkCd("005930").strategy(TradingSignal.StrategyType.S4_BIG_CANDLE)
                .themeName("반도체").entryPrice(70000.0).targetPct(3.0).stopPct(-2.0).build();

        String key = "ENABLE_STRATEGY_FAMILY_LIVE_ROUTING";
        String previous = System.getProperty(key);
        try {
            System.setProperty(key, "true");
            assertFalse(service.processSignal(dto));
        } finally {
            if (previous == null) System.clearProperty(key); else System.setProperty(key, previous);
        }

        verifyNoInteractions(candidateService);
        org.mockito.Mockito.verify(riskEvents).save(org.mockito.ArgumentMatchers.any());
    }
}
