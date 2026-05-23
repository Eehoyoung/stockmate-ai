package org.invest.apiorchestrator.util;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;

public record TradingDayWindow(
        LocalDate date,
        LocalDateTime start,
        LocalDateTime end,
        OffsetDateTime offsetStart,
        OffsetDateTime offsetEnd
) {

    public static TradingDayWindow of(LocalDate date) {
        LocalDateTime start = LocalDateTime.of(date, LocalTime.MIDNIGHT);
        LocalDateTime end = start.plusDays(1);
        return new TradingDayWindow(
                date,
                start,
                end,
                start.atZone(KstClock.ZONE_ID).toOffsetDateTime(),
                end.atZone(KstClock.ZONE_ID).toOffsetDateTime()
        );
    }
}
