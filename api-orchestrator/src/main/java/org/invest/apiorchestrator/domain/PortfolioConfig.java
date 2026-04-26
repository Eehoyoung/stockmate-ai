package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * portfolio_config — 자본·리스크 설정 (싱글턴 행 테이블)
 * <p>
 * id=1 인 단일 행만 존재. CHECK 제약으로 보장.
 * Java TradingController REST API 로 변경, DB 에 영속화.
 */
@Entity
@Table(name = "portfolio_config")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class PortfolioConfig {

    @Id
    @Column(name = "id")
    @Builder.Default
    private Integer id = 1;

    // ── 자본 설정 ──────────────────────────────────────────────────────────
    @Column(name = "total_capital", nullable = false, precision = 16, scale = 0)
    @Builder.Default
    private BigDecimal totalCapital = new BigDecimal("10000000");

    @Column(name = "max_position_pct", nullable = false, precision = 5, scale = 2)
    @Builder.Default
    private BigDecimal maxPositionPct = new BigDecimal("10.0");

    @Column(name = "max_position_count", nullable = false)
    @Builder.Default
    private Integer maxPositionCount = 5;

    @Column(name = "max_sector_pct", nullable = false, precision = 5, scale = 2)
    @Builder.Default
    private BigDecimal maxSectorPct = new BigDecimal("30.0");

    // ── 리스크 설정 ───────────────────────────────────────────────────────
    @Column(name = "daily_loss_limit_pct", nullable = false, precision = 5, scale = 2)
    @Builder.Default
    private BigDecimal dailyLossLimitPct = new BigDecimal("3.0");

    @Column(name = "daily_loss_limit_abs", precision = 14, scale = 0)
    private BigDecimal dailyLossLimitAbs;

    @Column(name = "max_drawdown_pct", nullable = false, precision = 5, scale = 2)
    @Builder.Default
    private BigDecimal maxDrawdownPct = new BigDecimal("10.0");

    @Column(name = "sl_mandatory", nullable = false)
    @Builder.Default
    private Boolean slMandatory = true;

    @Column(name = "min_rr_ratio", nullable = false, precision = 5, scale = 2)
    @Builder.Default
    private BigDecimal minRrRatio = new BigDecimal("1.0");

    // ── 전략 활성화 (JSONB 배열) ──────────────────────────────────────────
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "enabled_strategies", columnDefinition = "jsonb")
    @Builder.Default
    private String enabledStrategies =
            "[\"S1_GAP_OPEN\",\"S7_ICHIMOKU_BREAKOUT\",\"S8_GOLDEN_CROSS\",\"S9_PULLBACK_SWING\"," +
            "\"S10_NEW_HIGH\",\"S11_FRGN_CONT\",\"S12_CLOSING\",\"S13_BOX_BREAKOUT\"," +
            "\"S14_OVERSOLD_BOUNCE\",\"S15_MOMENTUM_ALIGN\"]";

    /** FIXED_PCT / KELLY / VOLATILITY */
    @Column(name = "sizing_method", nullable = false, length = 20)
    @Builder.Default
    private String sizingMethod = "FIXED_PCT";

    @Column(name = "updated_at")
    @Builder.Default
    private OffsetDateTime updatedAt = KstClock.nowOffset();

    @Column(name = "updated_by", length = 50)
    private String updatedBy;

    // ── 도메인 메서드 ─────────────────────────────────────────────────────
    public void update(BigDecimal totalCapital, BigDecimal maxPositionPct,
                       Integer maxPositionCount, String updatedBy) {
        this.totalCapital = totalCapital;
        this.maxPositionPct = maxPositionPct;
        this.maxPositionCount = maxPositionCount;
        this.updatedAt = KstClock.nowOffset();
        this.updatedBy = updatedBy;
    }
}
