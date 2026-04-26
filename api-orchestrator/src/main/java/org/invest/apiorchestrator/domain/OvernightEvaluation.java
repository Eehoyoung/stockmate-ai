package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * overnight_evaluations — Python overnight_worker 가 INSERT.
 * Java OvernightContextScheduler 가 next_day_* 컬럼을 익일 09:30 채운다.
 */
@Entity
@Table(name = "overnight_evaluations",
    indexes = {
        @Index(name = "idx_oe_signal_id",   columnList = "signal_id"),
        @Index(name = "idx_oe_position_id", columnList = "position_id"),
        @Index(name = "idx_oe_stk_cd",      columnList = "stk_cd, evaluated_at DESC"),
        @Index(name = "idx_oe_verdict",     columnList = "verdict, evaluated_at DESC")
    })
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class OvernightEvaluation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** trading_signals.id 참조. FK: ON DELETE SET NULL (V33 확인) */
    @Column(name = "signal_id")
    private Long signalId;

    /**
     * (레거시) V30 이전 open_positions.id 참조.
     * V33에서 FK 제거됨 — open_positions 가 뷰로 전환되어 실제 테이블 없음.
     * 이력 조회 목적으로 컬럼은 유지.
     */
    @Column(name = "position_id")
    private Long positionId;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    @Column(name = "strategy", length = 30)
    private String strategy;

    // ── Python overnight_worker 결과 ──────────────────────────────────────
    @Column(name = "java_overnight_score", precision = 5, scale = 2) private BigDecimal javaOvernightScore;
    @Column(name = "final_score",          precision = 5, scale = 2) private BigDecimal finalScore;
    @Column(name = "verdict",  length = 20) private String verdict;   // HOLD / FORCE_CLOSE
    @Column(name = "confidence", length = 10) private String confidence;
    @Column(name = "reason") private String reason;

    // ── 평가 시점 지표 스냅샷 ────────────────────────────────────────────
    @Column(name = "pnl_pct",       precision = 7, scale = 4) private BigDecimal pnlPct;
    @Column(name = "flu_rt",        precision = 7, scale = 4) private BigDecimal fluRt;
    @Column(name = "cntr_strength", precision = 7, scale = 2) private BigDecimal cntrStrength;
    @Column(name = "rsi14",         precision = 5, scale = 2) private BigDecimal rsi14;
    @Column(name = "ma_alignment",  length = 30)              private String maAlignment;
    @Column(name = "bid_ratio",     precision = 6, scale = 3) private BigDecimal bidRatio;
    @Column(name = "entry_price",   precision = 10, scale = 0) private BigDecimal entryPrice;
    @Column(name = "cur_prc_at_eval", precision = 10, scale = 0) private BigDecimal curPrcAtEval;

    @Column(name = "score_components", columnDefinition = "jsonb")
    @JdbcTypeCode(SqlTypes.JSON)
    private String scoreComponents;

    // ── 사후 검증 ─────────────────────────────────────────────────────────
    @Column(name = "next_day_open",    precision = 10, scale = 0) private BigDecimal nextDayOpen;
    @Column(name = "next_day_pnl_pct", precision = 7,  scale = 4) private BigDecimal nextDayPnlPct;
    @Column(name = "verdict_correct")                             private Boolean verdictCorrect;

    @Column(name = "evaluated_at", nullable = false)
    @Builder.Default
    private OffsetDateTime evaluatedAt = OffsetDateTime.now();
}
