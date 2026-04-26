package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * market_daily_context — 시장 전체 컨텍스트.
 * MarketContextScheduler (08:30) 가 INSERT, PerformanceAggregationScheduler (15:45) 가 당일 성과 채움.
 */
@Entity
@Table(name = "market_daily_context",
    uniqueConstraints = @UniqueConstraint(name = "uq_mdc_date", columnNames = {"date"}),
    indexes = @Index(name = "idx_mdc_date", columnList = "date DESC"))
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MarketDailyContext {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "date", nullable = false)
    private LocalDate date;

    // ── 지수 ───────────────────────────────────────────────────────────────
    @Column(name = "kospi_open",       precision = 8, scale = 2) private BigDecimal kospiOpen;
    @Column(name = "kospi_close",      precision = 8, scale = 2) private BigDecimal kospiClose;
    @Column(name = "kospi_change_pct", precision = 6, scale = 3) private BigDecimal kospiChangePct;
    @Column(name = "kospi_volume")                               private Long kospiVolume;

    @Column(name = "kosdaq_open",       precision = 8, scale = 2) private BigDecimal kosdaqOpen;
    @Column(name = "kosdaq_close",      precision = 8, scale = 2) private BigDecimal kosdaqClose;
    @Column(name = "kosdaq_change_pct", precision = 6, scale = 3) private BigDecimal kosdaqChangePct;
    @Column(name = "kosdaq_volume")                               private Long kosdaqVolume;

    // ── 시장 분위기 ────────────────────────────────────────────────────────
    @Column(name = "advancing_stocks")           private Integer advancingStocks;
    @Column(name = "declining_stocks")           private Integer decliningStocks;
    @Column(name = "unchanged_stocks")           private Integer unchangedStocks;
    @Column(name = "advance_decline_ratio", precision = 6, scale = 3) private BigDecimal advanceDeclineRatio;

    // ── 외국인·기관 수급 ───────────────────────────────────────────────────
    @Column(name = "frgn_net_buy_kospi",  precision = 14, scale = 0) private BigDecimal frgnNetBuyKospi;
    @Column(name = "inst_net_buy_kospi",  precision = 14, scale = 0) private BigDecimal instNetBuyKospi;
    @Column(name = "frgn_net_buy_kosdaq", precision = 14, scale = 0) private BigDecimal frgnNetBuyKosdaq;
    @Column(name = "inst_net_buy_kosdaq", precision = 14, scale = 0) private BigDecimal instNetBuyKosdaq;

    // ── 시장 상태 ─────────────────────────────────────────────────────────
    @Column(name = "news_sentiment",      length = 20)              private String newsSentiment;
    @Column(name = "news_trading_ctrl",   length = 20)              private String newsTradingCtrl;
    @Column(name = "vix_equivalent",      precision = 6, scale = 2) private BigDecimal vixEquivalent;
    @Column(name = "economic_event_today")                          private Boolean economicEventToday;
    @Column(name = "economic_event_nm",   length = 200)             private String economicEventNm;

    // ── 당일 성과 요약 ─────────────────────────────────────────────────────
    @Column(name = "total_signals_today")                           private Integer totalSignalsToday;
    @Column(name = "signal_win_rate_today", precision = 5, scale = 2) private BigDecimal signalWinRateToday;
    @Column(name = "avg_pnl_pct_today",     precision = 7, scale = 4) private BigDecimal avgPnlPctToday;

    @Column(name = "recorded_at")
    @Builder.Default
    private OffsetDateTime recordedAt = KstClock.nowOffset();
}
