package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * strategy_daily_stats — 전략별 일별 집계.
 * PerformanceAggregationScheduler (15:35) 가 UPSERT.
 */
@Entity
@Table(name = "strategy_daily_stats",
    uniqueConstraints = @UniqueConstraint(name = "uq_sds_date_strategy", columnNames = {"date", "strategy"}),
    indexes = {
        @Index(name = "idx_sds_date",     columnList = "date DESC"),
        @Index(name = "idx_sds_strategy", columnList = "strategy, date DESC")
    })
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StrategyDailyStat {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "date", nullable = false)
    private java.time.LocalDate date;

    @Column(name = "strategy", nullable = false, length = 30)
    private String strategy;

    // ── 신호 건수 ──────────────────────────────────────────────────────────
    @Column(name = "total_signals")    @Builder.Default private Integer totalSignals   = 0;
    @Column(name = "enter_count")      @Builder.Default private Integer enterCount     = 0;
    @Column(name = "cancel_count")     @Builder.Default private Integer cancelCount    = 0;
    @Column(name = "skip_entry_count") @Builder.Default private Integer skipEntryCount = 0;

    // ── 청산 결과 ──────────────────────────────────────────────────────────
    @Column(name = "tp1_hit_count")     @Builder.Default private Integer tp1HitCount    = 0;
    @Column(name = "tp2_hit_count")     @Builder.Default private Integer tp2HitCount    = 0;
    @Column(name = "sl_hit_count")      @Builder.Default private Integer slHitCount     = 0;
    @Column(name = "force_close_count") @Builder.Default private Integer forceCloseCount= 0;
    @Column(name = "expired_count")     @Builder.Default private Integer expiredCount   = 0;
    @Column(name = "overnight_count")   @Builder.Default private Integer overnightCount = 0;
    @Column(name = "win_rate", precision = 5, scale = 2)  private BigDecimal winRate;

    // ── 스코어 통계 ────────────────────────────────────────────────────────
    @Column(name = "avg_rule_score",      precision = 5, scale = 2) private BigDecimal avgRuleScore;
    @Column(name = "avg_ai_score",        precision = 5, scale = 2) private BigDecimal avgAiScore;
    @Column(name = "avg_rr_ratio",        precision = 5, scale = 2) private BigDecimal avgRrRatio;
    @Column(name = "pct_above_threshold", precision = 5, scale = 2) private BigDecimal pctAboveThreshold;

    // ── 성과 통계 ──────────────────────────────────────────────────────────
    @Column(name = "avg_pnl_pct",    precision = 7,  scale = 4) private BigDecimal avgPnlPct;
    @Column(name = "total_pnl_abs",  precision = 14, scale = 0) private BigDecimal totalPnlAbs;
    @Column(name = "avg_hold_min",   precision = 7,  scale = 1) private BigDecimal avgHoldMin;
    @Column(name = "best_pnl_pct",   precision = 7,  scale = 4) private BigDecimal bestPnlPct;
    @Column(name = "worst_pnl_pct",  precision = 7,  scale = 4) private BigDecimal worstPnlPct;

    @Column(name = "threshold_snapshot", precision = 5, scale = 2) private BigDecimal thresholdSnapshot;

    @Column(name = "updated_at")
    @Builder.Default
    private OffsetDateTime updatedAt = OffsetDateTime.now();
}
