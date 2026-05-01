package org.invest.apiorchestrator.util;

import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MarketTimeUtilTests {

    private static final LocalDate MONDAY = LocalDate.of(2026, 5, 4);
    private static final LocalDate SATURDAY = LocalDate.of(2026, 5, 2);

    @Test
    void sessionBoundariesAreInclusiveAtStartAndExclusiveAtEnd() {
        assertEquals(MarketTimeUtil.MarketSession.CLOSED, MarketTimeUtil.currentSession(at(MONDAY, 7, 59)));
        assertEquals(MarketTimeUtil.MarketSession.PRE_MARKET, MarketTimeUtil.currentSession(at(MONDAY, 8, 0)));
        assertEquals(MarketTimeUtil.MarketSession.OPENING_AUCTION, MarketTimeUtil.currentSession(at(MONDAY, 8, 50)));
        assertEquals(MarketTimeUtil.MarketSession.OPENING_AUCTION, MarketTimeUtil.currentSession(at(MONDAY, 9, 0, 29)));
        assertEquals(MarketTimeUtil.MarketSession.MAIN_MARKET, MarketTimeUtil.currentSession(at(MONDAY, 9, 0, 30)));
        assertEquals(MarketTimeUtil.MarketSession.CLOSING_AUCTION, MarketTimeUtil.currentSession(at(MONDAY, 15, 20)));
        assertEquals(MarketTimeUtil.MarketSession.AFTER_PREOPEN, MarketTimeUtil.currentSession(at(MONDAY, 15, 30)));
        assertEquals(MarketTimeUtil.MarketSession.AFTER_MARKET, MarketTimeUtil.currentSession(at(MONDAY, 15, 40)));
        assertEquals(MarketTimeUtil.MarketSession.POST_QUIET, MarketTimeUtil.currentSession(at(MONDAY, 20, 0)));
        assertEquals(MarketTimeUtil.MarketSession.CLOSED, MarketTimeUtil.currentSession(at(MONDAY, 20, 10)));

        assertTrue(MarketTimeUtil.isPreMarket(at(MONDAY, 8, 0)));
        assertTrue(MarketTimeUtil.isAuctionTime(at(MONDAY, 8, 50)));
        assertFalse(MarketTimeUtil.isMarketHours(at(MONDAY, 9, 0, 29)));
        assertTrue(MarketTimeUtil.isMarketHours(at(MONDAY, 9, 0, 30)));
        assertTrue(MarketTimeUtil.isMarketHours(at(MONDAY, 15, 19)));
        assertFalse(MarketTimeUtil.isMarketHours(at(MONDAY, 15, 20)));
    }

    @Test
    void tradingActiveCombinesPreMarketAndRegularMarketOnly() {
        assertTrue(MarketTimeUtil.isTradingActive(at(MONDAY, 8, 0)));
        assertTrue(MarketTimeUtil.isTradingActive(at(MONDAY, 9, 0, 30)));
        assertTrue(MarketTimeUtil.isTradingActive(at(MONDAY, 15, 40)));
        assertFalse(MarketTimeUtil.isTradingActive(at(MONDAY, 20, 0)));
    }

    @Test
    void forceCloseMatchesDedicatedForceCloseWindow() {
        assertFalse(MarketTimeUtil.shouldForceClose(at(MONDAY, 14, 49)));
        assertTrue(MarketTimeUtil.isForceCloseTime(at(MONDAY, 14, 50)));
        assertTrue(MarketTimeUtil.shouldForceClose(at(MONDAY, 14, 50)));
        assertFalse(MarketTimeUtil.shouldForceClose(at(MONDAY, 15, 20)));
    }

    @Test
    void weekendNeverEntersTradingSessions() {
        assertFalse(MarketTimeUtil.isWeekday(SATURDAY));
        assertFalse(MarketTimeUtil.isPreMarket(at(SATURDAY, 8, 30)));
        assertFalse(MarketTimeUtil.isAuctionTime(at(SATURDAY, 8, 30)));
        assertFalse(MarketTimeUtil.isMarketHours(at(SATURDAY, 9, 0)));
        assertFalse(MarketTimeUtil.isTradingActive(at(SATURDAY, 9, 0)));
        assertFalse(MarketTimeUtil.shouldForceClose(at(SATURDAY, 14, 50)));
    }

    private static LocalDateTime at(LocalDate date, int hour, int minute) {
        return LocalDateTime.of(date, LocalTime.of(hour, minute));
    }

    private static LocalDateTime at(LocalDate date, int hour, int minute, int second) {
        return LocalDateTime.of(date, LocalTime.of(hour, minute, second));
    }
}
