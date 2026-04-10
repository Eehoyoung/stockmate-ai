package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * daily_pnl — 일별 포트폴리오 손익 집계
 * <p>
 * 쓰기 주체: Java DailyPnlScheduler (15:45, 장 마감 후 집계).
 * 날짜별 1행 UNIQUE 보장 (UPSERT 패턴).
 */
@Entity
@Table(name = "daily_pnl")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DailyPnl {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "date", nullable = false, unique = true)
    private LocalDate date;

    // ── 당일 신호 통계 ───────────────────────────────────────────────────
    @Column(name = "total_signals")  @Builder.Default private Integer totalSignals = 0;
    @Column(name = "enter_count")    @Builder.Default private Integer enterCount   = 0;
    @Column(name = "cancel_count")   @Builder.Default private Integer cancelCount  = 0;

    // ── 당일 청산 결과 ───────────────────────────────────────────────────
    @Column(name = "closed_count")       @Builder.Default private Integer closedCount     = 0;
    @Column(name = "tp_hit_count")       @Builder.Default private Integer tpHitCount      = 0;
    @Column(name = "sl_hit_count")       @Builder.Default private Integer slHitCount      = 0;
    @Column(name = "force_close_count")  @Builder.Default private Integer forceCloseCount = 0;
    @Column(name = "win_rate", precision = 5, scale = 2) private BigDecimal winRate;

    // ── 손익 ─────────────────────────────────────────────────────────────
    @Column(name = "gross_pnl_abs", precision = 14, scale = 0)  private BigDecimal grossPnlAbs;
    @Column(name = "net_pnl_abs",   precision = 14, scale = 0)  private BigDecimal netPnlAbs;
    @Column(name = "gross_pnl_pct", precision = 7,  scale = 4)  private BigDecimal grossPnlPct;
    @Column(name = "net_pnl_pct",   precision = 7,  scale = 4)  private BigDecimal netPnlPct;
    @Column(name = "avg_pnl_per_trade", precision = 7, scale = 4) private BigDecimal avgPnlPerTrade;

    // ── 리스크 지표 ───────────────────────────────────────────────────────
    @Column(name = "max_intraday_loss_pct", precision = 7, scale = 4) private BigDecimal maxIntradayLossPct;
    @Column(name = "daily_loss_limit_hit")  @Builder.Default private Boolean dailyLossLimitHit = false;

    // ── 누적 ──────────────────────────────────────────────────────────────
    @Column(name = "cumulative_pnl_abs", precision = 16, scale = 0)  private BigDecimal cumulativePnlAbs;
    @Column(name = "cumulative_pnl_pct", precision = 7,  scale = 4)  private BigDecimal cumulativePnlPct;
    @Column(name = "peak_capital",        precision = 16, scale = 0)  private BigDecimal peakCapital;
    @Column(name = "current_drawdown_pct",precision = 7,  scale = 4)  private BigDecimal currentDrawdownPct;

    // ── 시장 컨텍스트 ─────────────────────────────────────────────────────
    @Column(name = "kospi_change_pct",  precision = 6, scale = 3) private BigDecimal kospiChangePct;
    @Column(name = "kosdaq_change_pct", precision = 6, scale = 3) private BigDecimal kosdaqChangePct;
    @Column(name = "market_sentiment", length = 20) private String marketSentiment;

    @Column(name = "aggregated_at")
    @Builder.Default
    private OffsetDateTime aggregatedAt = OffsetDateTime.now();
}
