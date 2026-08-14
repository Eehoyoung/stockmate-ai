package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.CandidatePoolHistoryRepository;
import org.invest.apiorchestrator.repository.PortfolioConfigRepository;
import org.invest.apiorchestrator.repository.RiskEventRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

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
}
