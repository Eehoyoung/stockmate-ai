package org.invest.apiorchestrator.util;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalTime;

public class MarketTimeUtil {

    private static final LocalTime PRE_MARKET_START  = LocalTime.of(7, 30);
    private static final LocalTime AUCTION_START     = LocalTime.of(8, 30);
    private static final LocalTime MARKET_OPEN       = LocalTime.of(9, 0);
    private static final LocalTime MARKET_CLOSE      = LocalTime.of(15, 20);
    private static final LocalTime POST_MARKET_END   = LocalTime.of(15, 30);
    private static final LocalTime FORCE_CLOSE_TIME  = LocalTime.of(14, 50);

    public static boolean isWeekday() {
        DayOfWeek dow = LocalDate.now().getDayOfWeek();
        return dow != DayOfWeek.SATURDAY && dow != DayOfWeek.SUNDAY;
    }

    public static boolean isPreMarket() {
        LocalTime now = LocalTime.now();
        return isWeekday() && now.isAfter(PRE_MARKET_START) && now.isBefore(MARKET_OPEN);
    }

    public static boolean isAuctionTime() {
        LocalTime now = LocalTime.now();
        return isWeekday() && now.isAfter(AUCTION_START) && now.isBefore(MARKET_OPEN);
    }

    public static boolean isMarketHours() {
        LocalTime now = LocalTime.now();
        return isWeekday() && !now.isBefore(MARKET_OPEN) && now.isBefore(MARKET_CLOSE);
    }

    public static boolean isForceCloseTime() {
        LocalTime now = LocalTime.now();
        return isWeekday() && !now.isBefore(FORCE_CLOSE_TIME) && now.isBefore(MARKET_CLOSE);
    }

    public static boolean isTradingActive() {
        return isPreMarket() || isMarketHours();
    }

    /** 강제 청산 알림용 (14:50 이후 장중) */
    public static boolean shouldForceClose() {
        return isWeekday() && !LocalTime.now().isBefore(FORCE_CLOSE_TIME)
                && LocalTime.now().isBefore(MARKET_CLOSE);
    }
}
