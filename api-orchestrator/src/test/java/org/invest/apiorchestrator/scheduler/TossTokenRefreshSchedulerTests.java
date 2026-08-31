package org.invest.apiorchestrator.scheduler;

import org.invest.apiorchestrator.config.TossInvestProperties;
import org.invest.apiorchestrator.service.TossAuthService;
import org.invest.apiorchestrator.service.TossMarketCalendarService;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.Optional;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TossTokenRefreshSchedulerTests {

    @Test
    void startupPreparesTossTokenWhenEnabled() {
        TossAuthService auth = mock(TossAuthService.class);
        TossMarketCalendarService calendar = mock(TossMarketCalendarService.class);
        TossInvestProperties properties = new TossInvestProperties();
        properties.setEnabled(true);

        new TossTokenRefreshScheduler(auth, properties, calendar).refreshOnStartup();

        verify(auth).getValidToken();
    }

    @Test
    void closedMarketSkipsMorningTokenRefresh() {
        TossAuthService auth = mock(TossAuthService.class);
        TossMarketCalendarService calendar = mock(TossMarketCalendarService.class);
        TossInvestProperties properties = new TossInvestProperties();
        properties.setEnabled(true);
        when(calendar.ensureTradingDay(any(LocalDate.class), eq(true))).thenReturn(Optional.of(false));

        new TossTokenRefreshScheduler(auth, properties, calendar).refreshMorning();

        verify(auth, never()).getValidToken();
        verify(auth, never()).refreshToken();
    }

    @Test
    void openMarketReusesValidCachedToken() {
        TossAuthService auth = mock(TossAuthService.class);
        TossMarketCalendarService calendar = mock(TossMarketCalendarService.class);
        TossInvestProperties properties = new TossInvestProperties();
        properties.setEnabled(true);
        when(calendar.ensureTradingDay(any(LocalDate.class), eq(true))).thenReturn(Optional.of(true));

        new TossTokenRefreshScheduler(auth, properties, calendar).refreshMorning();

        verify(auth).getValidToken();
        verify(auth, never()).refreshToken();
    }
}
