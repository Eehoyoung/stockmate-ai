package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * position_state_events — 포지션 상태 변화 이벤트 이력 (V31)
 * <p>
 * PositionMonitorScheduler 가 TP/SL/TrailingStop 등 상태 전이 시마다 INSERT.
 */
@Entity
@Table(name = "position_state_events", indexes = {
        @Index(name = "idx_position_state_events_signal_ts", columnList = "signal_id, event_ts DESC")
})
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class PositionStateEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** trading_signals.id 참조 (ON DELETE CASCADE) */
    @Column(name = "signal_id", nullable = false)
    private Long signalId;

    /**
     * 이벤트 유형 예: ACTIVATED, TP1_HIT, TP2_HIT, SL_HIT,
     * TRAILING_UPDATED, FORCE_CLOSE, OVERNIGHT_HOLD, EXPIRED
     */
    @Column(name = "event_type", nullable = false, length = 40)
    private String eventType;

    @Column(name = "event_ts", nullable = false)
    @Builder.Default
    private OffsetDateTime eventTs = OffsetDateTime.now();

    /** 이벤트 발생 시점의 포지션 상태 (ACTIVE, PARTIAL_TP, OVERNIGHT, CLOSED …) */
    @Column(name = "position_status", length = 20)
    private String positionStatus;

    @Column(name = "peak_price", precision = 10, scale = 0)
    private BigDecimal peakPrice;

    @Column(name = "trailing_stop_price", precision = 10, scale = 0)
    private BigDecimal trailingStopPrice;

    /** 이벤트 부가 데이터 (JSON) */
    @Column(name = "payload", columnDefinition = "jsonb")
    @JdbcTypeCode(SqlTypes.JSON)
    private String payload;
}
