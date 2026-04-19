package org.invest.apiorchestrator.util;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;

public final class KstClock {

    public static final ZoneId ZONE_ID = ZoneId.of("Asia/Seoul");

    private KstClock() {
    }

    public static LocalDate today() {
        return LocalDate.now(ZONE_ID);
    }

    public static LocalTime nowTime() {
        return LocalTime.now(ZONE_ID);
    }

    public static LocalDateTime now() {
        return LocalDateTime.now(ZONE_ID);
    }

    public static OffsetDateTime nowOffset() {
        return OffsetDateTime.now(ZONE_ID);
    }

    public static ZonedDateTime nowZoned() {
        return ZonedDateTime.now(ZONE_ID);
    }
}
