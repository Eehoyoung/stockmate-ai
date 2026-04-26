package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

/**
 * Feature 2 – 경제 이벤트 엔티티.
 * FOMC, 한은 금통위, CPI 등 주요 발표일을 저장한다.
 * INSERT 경로 없음 — 테이블은 유지하되 스케줄러는 비활성화(EconomicCalendarScheduler).
 *
 * V33: 구형 컬럼 title, importance, country 제거됨 (V1 baseline 잔재, 엔티티에 없음).
 *      event_name, event_type, event_time, expected_impact, description, notified 는 V22에서 추가됨.
 */
@Entity
@Table(name = "economic_events", indexes = {
        @Index(name = "idx_event_date", columnList = "event_date"),
        @Index(name = "idx_event_impact", columnList = "expected_impact")
})
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EconomicEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "event_seq")
    @SequenceGenerator(name = "event_seq", sequenceName = "economic_events_seq", allocationSize = 10)
    private Long id;

    @Column(name = "event_name", nullable = false, length = 100)
    private String eventName;

    @Enumerated(EnumType.STRING)
    @Column(name = "event_type", nullable = false, length = 20)
    private EventType eventType;

    @Column(name = "event_date", nullable = false)
    private LocalDate eventDate;

    @Column(name = "event_time")
    private LocalTime eventTime;

    @Enumerated(EnumType.STRING)
    @Column(name = "expected_impact", nullable = false, length = 10)
    @Builder.Default
    private ImpactLevel expectedImpact = ImpactLevel.MEDIUM;

    @Column(name = "description", columnDefinition = "TEXT")
    private String description;

    @CreatedDate
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "notified")
    @Builder.Default
    private boolean notified = false;

    public void markNotified() {
        this.notified = true;
    }

    public enum EventType {
        FED, BOK, CPI, PPI, GDP, EMPLOYMENT, CUSTOM
    }

    public enum ImpactLevel {
        HIGH, MEDIUM, LOW
    }
}
