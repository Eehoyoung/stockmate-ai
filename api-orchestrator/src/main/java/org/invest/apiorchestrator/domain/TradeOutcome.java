package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * trade_outcomes — 신호별 실현 결과 (V31)
 * <p>
 * PositionMonitorScheduler 가 포지션 종료 시 INSERT.
 * rr_fit_report.py 등 Python 분석 모듈이 읽어 백테스트 통계를 산출한다.
 */
@Entity
@Table(name = "trade_outcomes", indexes = {
        @Index(name = "idx_trade_outcomes_signal", columnList = "signal_id, exit_ts DESC")
})
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TradeOutcome {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** trading_signals.id 참조 (ON DELETE CASCADE) */
    @Column(name = "signal_id", nullable = false)
    private Long signalId;

    /** trade_plans.id 참조 (ON DELETE CASCADE, nullable) */
    @Column(name = "plan_id")
    private Long planId;

    /**
     * 청산 사유: TP1_HIT / TP2_HIT / SL_HIT / TIME_STOP /
     * FORCE_CLOSE / TRAILING_STOP / EXPIRED
     */
    @Column(name = "exit_reason", nullable = false, length = 20)
    private String exitReason;

    @Column(name = "exit_ts", nullable = false)
    @Builder.Default
    private OffsetDateTime exitTs = OffsetDateTime.now();

    @Column(name = "exit_price", precision = 10, scale = 0)
    private BigDecimal exitPrice;

    @Column(name = "filled_qty")
    private Integer filledQty;

    /** 슬리피지 미반영 실현 R:R */
    @Column(name = "realized_rr_gross", precision = 6, scale = 3)
    private BigDecimal realizedRrGross;

    /** 슬리피지 반영 실현 R:R */
    @Column(name = "realized_rr_net", precision = 6, scale = 3)
    private BigDecimal realizedRrNet;

    @Column(name = "realized_pnl", precision = 14, scale = 2)
    private BigDecimal realizedPnl;

    /** TP가 SL보다 먼저 도달했는지 여부 */
    @Column(name = "tp_hit_before_sl_flag")
    private Boolean tpHitBeforeSlFlag;

    /** 계획 호라이즌 내 TP 도달 여부 */
    @Column(name = "tp_reached_within_horizon_flag")
    private Boolean tpReachedWithinHorizonFlag;

    /** 시간 정지(time-stop) 에 의한 종료 여부 */
    @Column(name = "timeout_flag")
    @Builder.Default
    private Boolean timeoutFlag = false;

    /** 호가 스냅 방식: CLOSE / INTRA 등 */
    @Column(name = "touch_mode", length = 20)
    private String touchMode;

    /** 체결 품질 플래그: IDEAL / SLIPPAGE / PARTIAL 등 */
    @Column(name = "execution_quality_flag", length = 20)
    private String executionQualityFlag;
}
