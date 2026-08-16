package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.TossMarketCalendarService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** 휴장 여부를 다른 서비스가 외부 호출 전에 읽을 수 있도록 Redis에 선행 게시한다. */
@Slf4j
@Component
@RequiredArgsConstructor
public class TossMarketCalendarScheduler {

    private final TossMarketCalendarService calendarService;

    @Scheduled(initialDelay = 30_000, fixedDelay = 21_600_000)
    public void refreshOnStartupAndPeriodically() {
        calendarService.ensureTradingDay(KstClock.today(), true);
    }

    /** 전날 남아 있는 토큰으로 내일 상태를 미리 저장한다. 토큰이 없으면 새로 발급하지 않는다. */
    @Scheduled(cron = "0 50 20 * * *", zone = "Asia/Seoul")
    public void prefetchTomorrowWithoutIssuingToken() {
        calendarService.ensureTradingDay(KstClock.today().plusDays(1), false);
    }
}
