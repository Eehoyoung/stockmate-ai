package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * trade_plans — 신호별 TP/SL 계획 (V31)
 * <p>
 * 하나의 신호에 복수의 플랜(primary / alternative)이 가능하며
 * variant_rank 로 우선순위를 표현한다.
 */
@Entity
@Table(name = "trade_plans", indexes = {
        @Index(name = "idx_trade_plans_signal", columnList = "signal_id, variant_rank")
})
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TradePlan {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** trading_signals.id 참조 (ON DELETE CASCADE) */
    @Column(name = "signal_id", nullable = false)
    private Long signalId;

    @Column(name = "strategy_code", nullable = false, length = 30)
    private String strategyCode;

    @Column(name = "strategy_version", length = 40)
    private String strategyVersion;

    /** 플랜 이름: primary / conservative / aggressive 등 */
    @Column(name = "plan_name", nullable = false, length = 50)
    @Builder.Default
    private String planName = "primary";

    /** TP 계산 모델 식별자 */
    @Column(name = "tp_model", length = 50)
    private String tpModel;

    /** SL 계산 모델 식별자 */
    @Column(name = "sl_model", length = 50)
    private String slModel;

    @Column(name = "tp_price", precision = 10, scale = 0)
    private BigDecimal tpPrice;

    @Column(name = "sl_price", precision = 10, scale = 0)
    private BigDecimal slPrice;

    @Column(name = "tp_pct", precision = 7, scale = 3)
    private BigDecimal tpPct;

    @Column(name = "sl_pct", precision = 7, scale = 3)
    private BigDecimal slPct;

    /** 슬리피지 미반영 R:R */
    @Column(name = "planned_rr", precision = 6, scale = 3)
    private BigDecimal plannedRr;

    /** 슬리피지 반영 실질 R:R */
    @Column(name = "effective_rr", precision = 6, scale = 3)
    private BigDecimal effectiveRr;

    @Column(name = "time_stop_type", length = 30)
    private String timeStopType;

    @Column(name = "time_stop_minutes")
    private Integer timeStopMinutes;

    @Column(name = "time_stop_session", length = 30)
    private String timeStopSession;

    /** 트레일링 스탑 룰 식별자 */
    @Column(name = "trailing_rule", length = 50)
    private String trailingRule;

    /** 부분 TP 룰 식별자 */
    @Column(name = "partial_tp_rule", length = 50)
    private String partialTpRule;

    /** 청산 우선순위 (TP_FIRST / SL_FIRST / TIME_STOP 등) */
    @Column(name = "planned_exit_priority", length = 50)
    private String plannedExitPriority;

    /** 플랜 우선순위 (1=primary) */
    @Column(name = "variant_rank")
    @Builder.Default
    private Integer variantRank = 1;

    @Column(name = "created_at", nullable = false)
    @Builder.Default
    private OffsetDateTime createdAt = OffsetDateTime.now();
}
