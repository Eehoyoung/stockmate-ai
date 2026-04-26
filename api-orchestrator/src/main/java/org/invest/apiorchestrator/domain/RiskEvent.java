package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * risk_events — 리스크 한도 위반 로그.
 * 리스크 한도 초과, 중복 신호 차단, R:R 미달 등 실시간 INSERT.
 */
@Entity
@Table(name = "risk_events",
    indexes = {
        @Index(name = "idx_re_type_date", columnList = "event_type, occurred_at DESC"),
        @Index(name = "idx_re_date",      columnList = "occurred_at DESC")
    })
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class RiskEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "event_type", nullable = false, length = 30)
    private String eventType;
    // DAILY_LOSS_LIMIT / MAX_POSITION_EXCEEDED / SECTOR_LIMIT / DRAWDOWN_LIMIT
    // NEWS_PAUSE / DUPLICATE_SIGNAL_BLOCKED / RR_BELOW_MIN

    @Column(name = "stk_cd", length = 20)
    private String stkCd;

    @Column(name = "strategy", length = 30)
    private String strategy;

    @Column(name = "signal_id")
    private Long signalId;

    @Column(name = "threshold_value", precision = 10, scale = 2)
    private BigDecimal thresholdValue;

    @Column(name = "actual_value", precision = 10, scale = 2)
    private BigDecimal actualValue;

    @Column(name = "description")
    private String description;

    @Column(name = "action_taken", length = 100)
    private String actionTaken;

    @Column(name = "occurred_at", nullable = false)
    @Builder.Default
    private OffsetDateTime occurredAt = KstClock.nowOffset();
}
