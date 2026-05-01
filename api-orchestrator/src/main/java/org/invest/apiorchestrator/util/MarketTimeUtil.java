package org.invest.apiorchestrator.util;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

public class MarketTimeUtil {

    public enum MarketSession {
        PRE_MARKET,
        OPENING_AUCTION,
        MAIN_MARKET,
        CLOSING_AUCTION,
        AFTER_PREOPEN,
        AFTER_MARKET,
        POST_QUIET,
        CLOSED
    }

    private static final LocalTime PRE_MARKET_START = LocalTime.of(8, 0);
    private static final LocalTime OPENING_AUCTION_START = LocalTime.of(8, 50);
    private static final LocalTime MAIN_MARKET_START = LocalTime.of(9, 0, 30);
    private static final LocalTime MARKET_CLOSE = LocalTime.of(15, 20);
    private static final LocalTime AFTER_PREOPEN_START = LocalTime.of(15, 30);
    private static final LocalTime AFTER_MARKET_START = LocalTime.of(15, 40);
    private static final LocalTime POST_QUIET_START = LocalTime.of(20, 0);
    private static final LocalTime CLOSED_START = LocalTime.of(20, 10);
    private static final LocalTime FORCE_CLOSE_TIME = LocalTime.of(14, 50);

    public static boolean isWeekday() {
        return isWeekday(KstClock.today());
    }

    public static boolean isWeekday(LocalDate date) {
        DayOfWeek dow = date.getDayOfWeek();
        return dow != DayOfWeek.SATURDAY && dow != DayOfWeek.SUNDAY;
    }

    public static boolean isPreMarket() {
        return isPreMarket(KstClock.now());
    }

    public static boolean isPreMarket(LocalDateTime dateTime) {
        return currentSession(dateTime) == MarketSession.PRE_MARKET;
    }

    public static boolean isAuctionTime() {
        return isAuctionTime(KstClock.now());
    }

    public static boolean isAuctionTime(LocalDateTime dateTime) {
        return currentSession(dateTime) == MarketSession.OPENING_AUCTION
                || currentSession(dateTime) == MarketSession.CLOSING_AUCTION;
    }

    public static boolean isMarketHours() {
        return isMarketHours(KstClock.now());
    }

    public static boolean isMarketHours(LocalDateTime dateTime) {
        return currentSession(dateTime) == MarketSession.MAIN_MARKET;
    }

    public static boolean isForceCloseTime() {
        return isForceCloseTime(KstClock.now());
    }

    public static boolean isForceCloseTime(LocalDateTime dateTime) {
        LocalTime now = dateTime.toLocalTime();
        return isWeekday(dateTime.toLocalDate()) && !now.isBefore(FORCE_CLOSE_TIME) && now.isBefore(MARKET_CLOSE);
    }

    public static boolean isTradingActive() {
        return isTradingActive(KstClock.now());
    }

    public static boolean isTradingActive(LocalDateTime dateTime) {
        return switch (currentSession(dateTime)) {
            case PRE_MARKET, OPENING_AUCTION, MAIN_MARKET, CLOSING_AUCTION, AFTER_PREOPEN, AFTER_MARKET -> true;
            case POST_QUIET, CLOSED -> false;
        };
    }

    public static boolean shouldForceClose() {
        return shouldForceClose(KstClock.now());
    }

    public static boolean shouldForceClose(LocalDateTime dateTime) {
        return isForceCloseTime(dateTime);
    }

    public static MarketSession currentSession() {
        return currentSession(KstClock.now());
    }

    public static MarketSession currentSession(LocalDateTime dateTime) {
        if (!isWeekday(dateTime.toLocalDate())) {
            return MarketSession.CLOSED;
        }
        LocalTime now = dateTime.toLocalTime();
        if (!now.isBefore(PRE_MARKET_START) && now.isBefore(OPENING_AUCTION_START)) {
            return MarketSession.PRE_MARKET;
        }
        if (!now.isBefore(OPENING_AUCTION_START) && now.isBefore(MAIN_MARKET_START)) {
            return MarketSession.OPENING_AUCTION;
        }
        if (!now.isBefore(MAIN_MARKET_START) && now.isBefore(MARKET_CLOSE)) {
            return MarketSession.MAIN_MARKET;
        }
        if (!now.isBefore(MARKET_CLOSE) && now.isBefore(AFTER_PREOPEN_START)) {
            return MarketSession.CLOSING_AUCTION;
        }
        if (!now.isBefore(AFTER_PREOPEN_START) && now.isBefore(AFTER_MARKET_START)) {
            return MarketSession.AFTER_PREOPEN;
        }
        if (!now.isBefore(AFTER_MARKET_START) && now.isBefore(POST_QUIET_START)) {
            return MarketSession.AFTER_MARKET;
        }
        if (!now.isBefore(POST_QUIET_START) && now.isBefore(CLOSED_START)) {
            return MarketSession.POST_QUIET;
        }
        return MarketSession.CLOSED;
    }
}
