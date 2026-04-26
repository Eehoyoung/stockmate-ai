package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * daily_indicators — 기술지표 영속 캐시
 * <p>
 * Python ai-engine 이 전략 스캔 후 UPSERT. 하루 한 번 계산으로 API 호출 최소화.
 * (date + stk_cd) UNIQUE 보장.
 * <p>
 * 쓰기 주체: Python db_writer.upsert_daily_indicators()
 * Hibernate: 읽기 + 테이블 생성(ddl-auto: update) 담당
 */
@Entity
@Table(
    name = "daily_indicators",
    uniqueConstraints = @UniqueConstraint(name = "uq_di_date_stk", columnNames = {"date", "stk_cd"}),
    indexes = {
        @Index(name = "idx_di_date_stk", columnList = "date DESC, stk_cd"),
        @Index(name = "idx_di_stk_date", columnList = "stk_cd, date DESC")
    }
)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DailyIndicators {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "date", nullable = false)
    private LocalDate date;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    // ── OHLCV ──────────────────────────────────────────────────────────────
    @Column(name = "close_price", precision = 10, scale = 0) private BigDecimal closePrice;
    @Column(name = "open_price",  precision = 10, scale = 0) private BigDecimal openPrice;
    @Column(name = "high_price",  precision = 10, scale = 0) private BigDecimal highPrice;
    @Column(name = "low_price",   precision = 10, scale = 0) private BigDecimal lowPrice;
    @Column(name = "volume")                                 private Long volume;
    @Column(name = "volume_ratio", precision = 6, scale = 2) private BigDecimal volumeRatio;

    // ── 이동평균 ───────────────────────────────────────────────────────────
    @Column(name = "ma5",   precision = 10, scale = 0) private BigDecimal ma5;
    @Column(name = "ma20",  precision = 10, scale = 0) private BigDecimal ma20;
    @Column(name = "ma60",  precision = 10, scale = 0) private BigDecimal ma60;
    @Column(name = "ma120", precision = 10, scale = 0) private BigDecimal ma120;
    @Column(name = "vol_ma20")                         private Long volMa20;

    // ── 오실레이터 ─────────────────────────────────────────────────────────
    @Column(name = "rsi14",   precision = 5, scale = 2) private BigDecimal rsi14;
    @Column(name = "stoch_k", precision = 5, scale = 2) private BigDecimal stochK;
    @Column(name = "stoch_d", precision = 5, scale = 2) private BigDecimal stochD;

    // ── 볼린저밴드 ─────────────────────────────────────────────────────────
    @Column(name = "bb_upper",     precision = 10, scale = 0) private BigDecimal bbUpper;
    @Column(name = "bb_mid",       precision = 10, scale = 0) private BigDecimal bbMid;
    @Column(name = "bb_lower",     precision = 10, scale = 0) private BigDecimal bbLower;
    @Column(name = "bb_width_pct", precision = 6,  scale = 3) private BigDecimal bbWidthPct;
    @Column(name = "pct_b",        precision = 6,  scale = 3) private BigDecimal pctB;

    // ── ATR ────────────────────────────────────────────────────────────────
    @Column(name = "atr14",   precision = 10, scale = 2) private BigDecimal atr14;
    @Column(name = "atr_pct", precision = 6,  scale = 3) private BigDecimal atrPct;

    // ── MACD ───────────────────────────────────────────────────────────────
    @Column(name = "macd_line",   precision = 10, scale = 2) private BigDecimal macdLine;
    @Column(name = "macd_signal", precision = 10, scale = 2) private BigDecimal macdSignal;
    @Column(name = "macd_hist",   precision = 10, scale = 2) private BigDecimal macdHist;

    // ── 추세·패턴 플래그 ───────────────────────────────────────────────────
    @Column(name = "is_bullish_aligned")  private Boolean isBullishAligned;
    @Column(name = "is_above_ma20")       private Boolean isAboveMa20;
    @Column(name = "is_new_high_52w")     private Boolean isNewHigh52w;
    @Column(name = "golden_cross_today")  private Boolean goldenCrossToday;

    // ── 스윙 포인트 ────────────────────────────────────────────────────────
    @Column(name = "swing_high_20d", precision = 10, scale = 0) private BigDecimal swingHigh20d;
    @Column(name = "swing_low_20d",  precision = 10, scale = 0) private BigDecimal swingLow20d;
    @Column(name = "swing_high_60d", precision = 10, scale = 0) private BigDecimal swingHigh60d;
    @Column(name = "swing_low_60d",  precision = 10, scale = 0) private BigDecimal swingLow60d;

    @Column(name = "computed_at", nullable = false)
    @Builder.Default
    private OffsetDateTime computedAt = KstClock.nowOffset();
}
