package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.EconomicEvent;
import org.invest.apiorchestrator.repository.EconomicEventRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.*;
import java.util.List;

/**
 * Feature 2 – 경제 캘린더 서비스.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EconomicCalendarService {

    private final EconomicEventRepository eventRepository;

    /** 이번 주 이벤트 (월~일) */
    @Transactional(readOnly = true)
    public List<EconomicEvent> getThisWeekEvents() {
        LocalDate today  = LocalDate.now();
        LocalDate monday = today.with(java.time.DayOfWeek.MONDAY);
        LocalDate sunday = monday.plusDays(6);
        return eventRepository.findByEventDateBetweenOrderByEventDateAsc(monday, sunday);
    }

    /** 오늘 이벤트 */
    @Transactional(readOnly = true)
    public List<EconomicEvent> getTodayEvents() {
        return eventRepository.findByEventDateOrderByEventTimeAsc(LocalDate.now());
    }

    /**
     * 지금부터 withinMinutes 분 내에 HIGH 임팩트 이벤트가 있는지 확인
     */
    @Transactional(readOnly = true)
    public boolean hasHighImpactEventSoon(int withinMinutes) {
        LocalDate today = LocalDate.now();
        LocalTime now   = LocalTime.now();
        LocalTime limit = now.plusMinutes(withinMinutes);

        List<EconomicEvent> todayEvents = eventRepository.findByEventDateOrderByEventTimeAsc(today);
        return todayEvents.stream()
                .filter(e -> e.getExpectedImpact() == EconomicEvent.ImpactLevel.HIGH)
                .filter(e -> e.getEventTime() != null)
                .anyMatch(e -> {
                    LocalTime t = e.getEventTime();
                    return !t.isBefore(now) && !t.isAfter(limit);
                });
    }

    /** 이벤트 등록 */
    @Transactional
    public EconomicEvent addEvent(EconomicEvent event) {
        log.info("[Calendar] 이벤트 등록: {} {} impact={}", event.getEventName(), event.getEventDate(), event.getExpectedImpact());
        return eventRepository.save(event);
    }

    /** 알림 발송 후 notified 플래그 업데이트 */
    @Transactional
    public void markNotified(Long eventId) {
        eventRepository.findById(eventId).ifPresent(e -> {
            e.markNotified();
            log.debug("[Calendar] 알림 완료 처리 id={}", eventId);
        });
    }
}
