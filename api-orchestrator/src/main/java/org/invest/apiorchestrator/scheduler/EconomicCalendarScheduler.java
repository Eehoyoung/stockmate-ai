package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.EconomicEvent;
import org.invest.apiorchestrator.repository.EconomicEventRepository;
import org.invest.apiorchestrator.service.EconomicCalendarService;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;

/**
 * Economic calendar scheduler.
 *
 * User-facing calendar/news delivery is owned by ai-engine scheduled briefs only.
 * This scheduler now maintains internal risk flags and notification state without
 * publishing Telegram messages.
 */
@Slf4j
// @Component — economic_events 테이블 V25에서 DROP됨; 스케줄러 비활성화
@RequiredArgsConstructor
public class EconomicCalendarScheduler {

    private static final String KEY_PRE_EVENT = "calendar:pre_event";

    private final EconomicCalendarService calendarService;
    private final EconomicEventRepository eventRepository;
    private final StringRedisTemplate redis;

    @Scheduled(cron = "0 0 * * * MON-FRI", zone = "Asia/Seoul")
    public void checkUpcomingHighImpactEvents() {
        try {
            List<EconomicEvent> events = eventRepository.findUnnotifiedHighImpactToday(LocalDate.now());
            if (events.isEmpty()) {
                return;
            }

            boolean hasSoon = calendarService.hasHighImpactEventSoon(120);
            if (!hasSoon) {
                return;
            }

            redis.opsForValue().set(KEY_PRE_EVENT, "true", Duration.ofHours(2));
            log.info("[Calendar] pre-event risk flag set");

            for (EconomicEvent event : events) {
                if (calendarService.hasHighImpactEventSoon(120)) {
                    publishCalendarAlert(event);
                    calendarService.markNotified(event.getId());
                }
            }
        } catch (Exception e) {
            log.warn("[Calendar] event check error: {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 0 8 * * MON-FRI", zone = "Asia/Seoul")
    public void morningCalendarBrief() {
        try {
            List<EconomicEvent> todayEvents = calendarService.getTodayEvents();
            if (todayEvents.isEmpty()) {
                return;
            }

            log.info("[Calendar] ai-engine morning brief owns user-facing calendar delivery; skipped {} events", todayEvents.size());
        } catch (Exception e) {
            log.warn("[Calendar] morning brief error: {}", e.getMessage());
        }
    }

    private void publishCalendarAlert(EconomicEvent event) {
        log.info("[Calendar] ai-engine scheduled brief owns user-facing event alerts; CALENDAR_ALERT push skipped for event={}", event.getEventName());
    }
}
