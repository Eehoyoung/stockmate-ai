package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * signal_score_components — Python scorer.py 컴포넌트 상세 기록
 * <p>
 * 전략별로 어떤 지표가 실제 수익에 기여했는지 분석하기 위한 핵심 테이블.
 * 쓰기 주체: Python queue_worker (scorer.py rule_score 계산 직후).
 * Hibernate 에서는 읽기 전용(READ_ONLY)으로 사용.
 * Python 이 asyncpg 로 직접 INSERT.
 */
@Entity
@Table(name = "signal_score_components")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SignalScoreComponents {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "signal_id", nullable = false)
    private TradingSignal signal;

    @Column(name = "strategy", nullable = false, length = 30)
    private String strategy;

    // ── 공통 컴포넌트 ─────────────────────────────────────────────────────
    @Column(name = "base_score",     precision = 5, scale = 2) private BigDecimal baseScore;
    @Column(name = "time_bonus",     precision = 5, scale = 2) private BigDecimal timeBonus;
    @Column(name = "vol_score",      precision = 5, scale = 2) private BigDecimal volScore;
    @Column(name = "momentum_score", precision = 5, scale = 2) private BigDecimal momentumScore;
    @Column(name = "technical_score",precision = 5, scale = 2) private BigDecimal technicalScore;
    @Column(name = "demand_score",   precision = 5, scale = 2) private BigDecimal demandScore;
    @Column(name = "risk_penalty",   precision = 5, scale = 2) private BigDecimal riskPenalty;

    // ── 전략별 특화 컴포넌트 (JSONB) ───────────────────────────────────────
    @Column(name = "strategy_components", columnDefinition = "jsonb")
    private String strategyComponents;

    // ── 집계 ──────────────────────────────────────────────────────────────
    @Column(name = "total_score",    precision = 5, scale = 2) private BigDecimal totalScore;
    @Column(name = "threshold_used", precision = 5, scale = 2) private BigDecimal thresholdUsed;
    @Column(name = "passed_threshold") private Boolean passedThreshold;

    @Column(name = "computed_at")
    @Builder.Default
    private OffsetDateTime computedAt = KstClock.nowOffset();
}
