package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.EconomicEvent;
import org.invest.apiorchestrator.repository.EconomicEventRepository;
import org.invest.apiorchestrator.service.EconomicCalendarService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * Feature 2 – 경제 캘린더 스케쥴러.
 *
 * 매시간 HIGH 임팩트 이벤트 2시간 전 체크 → calendar:pre_event 키 설정 + 텔레그램 알림.
 * 매일 08:00 오늘 예정 이벤트 모닝 브리핑.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class EconomicCalendarScheduler {

    private static final String KEY_PRE_EVENT = "calendar:pre_event";

    private final EconomicCalendarService calendarService;
    private final EconomicEventRepository eventRepository;
    private final RedisMarketDataService redisMarketDataService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    /**
     * 매시간 정각 – 2시간 내 HIGH 임팩트 이벤트 확인
     */
    @Scheduled(cron = "0 0 * * * MON-FRI")
    public void checkUpcomingHighImpactEvents() {
        try {
            List<EconomicEvent> events = eventRepository.findUnnotifiedHighImpactToday(LocalDate.now());
            if (events.isEmpty()) return;

            boolean hasSoon = calendarService.hasHighImpactEventSoon(120);
            if (!hasSoon) return;

            // calendar:pre_event 키 설정 (2시간 TTL)
            redis.opsForValue().set(KEY_PRE_EVENT, "true", Duration.ofHours(2));
            log.info("[Calendar] 2시간 내 HIGH 임팩트 이벤트 감지 → calendar:pre_event 설정");

            for (EconomicEvent event : events) {
                if (calendarService.hasHighImpactEventSoon(120)) {
                    publishCalendarAlert(event);
                    calendarService.markNotified(event.getId());
                }
            }
        } catch (Exception e) {
            log.warn("[Calendar] 이벤트 체크 오류: {}", e.getMessage());
        }
    }

    /**
     * 매일 08:00 – 오늘 예정 이벤트 모닝 브리핑
     */
    @Scheduled(cron = "0 0 8 * * MON-FRI")
    public void morningCalendarBrief() {
        try {
            List<EconomicEvent> todayEvents = calendarService.getTodayEvents();
            if (todayEvents.isEmpty()) return;

            StringBuilder sb = new StringBuilder("📅 <b>[오늘의 경제 일정]</b>\n\n");
            for (EconomicEvent e : todayEvents) {
                String impact = switch (e.getExpectedImpact()) {
                    case HIGH   -> "🔴";
                    case MEDIUM -> "🟡";
                    case LOW    -> "⚪";
                };
                String time = e.getEventTime() != null
                        ? e.getEventTime().toString().substring(0, 5)
                        : "시간 미정";
                sb.append(String.format("%s %s %s [%s]\n",
                        impact, time, e.getEventName(), e.getEventType()));
            }

            String msg = objectMapper.writeValueAsString(Map.of(
                    "type",    "CALENDAR_ALERT",
                    "subtype", "MORNING_BRIEF",
                    "message", sb.toString().trim()
            ));
            redisMarketDataService.pushScoredQueue(msg);
            log.info("[Calendar] 모닝 브리핑 발행 ({}건)", todayEvents.size());
        } catch (Exception e) {
            log.warn("[Calendar] 모닝 브리핑 오류: {}", e.getMessage());
        }
    }

    private void publishCalendarAlert(EconomicEvent event) {
        try {
            String time = event.getEventTime() != null
                    ? event.getEventTime().toString().substring(0, 5)
                    : "시간 미정";
            String message = String.format(
                    "⚠️ <b>[경제 이벤트 임박]</b>\n%s %s\n예상 영향: HIGH\n→ 신중 매매 모드 전환",
                    time, event.getEventName());

            String msg = objectMapper.writeValueAsString(Map.of(
                    "type",       "CALENDAR_ALERT",
                    "subtype",    "PRE_EVENT",
                    "event_name", event.getEventName(),
                    "event_type", event.getEventType().name(),
                    "message",    message
            ));
            redisMarketDataService.pushScoredQueue(msg);
        } catch (Exception e) {
            log.warn("[Calendar] 알림 발행 실패: {}", e.getMessage());
        }
    }
}
