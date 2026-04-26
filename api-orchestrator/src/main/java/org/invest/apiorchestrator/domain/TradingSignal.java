package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.LocalDateTime;
import org.invest.apiorchestrator.util.KstClock;

@Entity
@Table(name = "trading_signals", indexes = {
        @Index(name = "idx_signal_stk_cd",    columnList = "stk_cd"),
        @Index(name = "idx_signal_strategy",   columnList = "strategy"),
        @Index(name = "idx_signal_created_at", columnList = "created_at"),
        @Index(name = "idx_ts_action_created", columnList = "action, created_at"),
        @Index(name = "idx_ts_stk_action",     columnList = "stk_cd, action, created_at"),
        @Index(name = "idx_ts_position_status", columnList = "position_status")
})
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TradingSignal {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "signal_seq")
    @SequenceGenerator(name = "signal_seq", sequenceName = "trading_signals_seq", allocationSize = 50)
    private Long id;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    @Column(name = "stk_nm", length = 40)
    private String stkNm;

    @Enumerated(EnumType.STRING)
    @Column(name = "strategy", nullable = false, length = 30)
    private StrategyType strategy;

    /**
     * 레거시 신호 점수 — Python 스코어링 도입 이전 Java에서 계산하던 값.
     * rule_score, ai_score 로 대체됨. 컬럼은 이력 목적으로 유지.
     */
    @Column(name = "signal_score")
    private Double signalScore;

    @Column(name = "entry_price")
    private Double entryPrice;

    /**
     * 레거시 목표가 — tp1_price, tp2_price 도입 이전 사용.
     * 컬럼은 이력 목적으로 유지.
     */
    @Column(name = "target_price")
    private Double targetPrice;

    /**
     * 레거시 손절가 — sl_price 도입 이전 사용.
     * 컬럼은 이력 목적으로 유지.
     */
    @Column(name = "stop_price")
    private Double stopPrice;

    @Column(name = "tp1_price")
    private Double tp1Price;

    @Column(name = "tp2_price")
    private Double tp2Price;

    @Column(name = "sl_price")
    private Double slPrice;

    @Column(name = "target_pct")
    private Double targetPct;

    @Column(name = "stop_pct")
    private Double stopPct;

    @Column(name = "gap_pct")
    private Double gapPct;

    @Column(name = "cntr_strength")
    private Double cntrStrength;

    @Column(name = "bid_ratio")
    private Double bidRatio;

    @Column(name = "vol_ratio")
    private Double volRatio;

    @Column(name = "pullback_pct")
    private Double pullbackPct;

    @Column(name = "theme_name", length = 100)
    private String themeName;

    @Column(name = "entry_type", length = 30)
    private String entryType;

    @Column(name = "market_type", length = 10)
    private String marketType;

    @Column(name = "position_status", length = 20)
    private String positionStatus;

    @Column(name = "sector", length = 50)
    private String sector;

    @Column(name = "entry_qty")
    private Integer entryQty;

    @Column(name = "entry_amount", precision = 14, scale = 0)
    private BigDecimal entryAmount;

    @Column(name = "entry_at")
    private OffsetDateTime entryAt;

    @Enumerated(EnumType.STRING)
    @Column(name = "signal_status", length = 20)
    @Builder.Default
    private SignalStatus signalStatus = SignalStatus.PENDING;

    @Column(name = "extra_info", columnDefinition = "TEXT")
    private String extraInfo;

    @CreatedDate
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "executed_at")
    private LocalDateTime executedAt;

    @Column(name = "closed_at")
    private LocalDateTime closedAt;

    @Column(name = "realized_pnl")
    private Double realizedPnl;

    // ── Python ai-engine 스코어링 결과 (V2 추가) ──────────────────────────
    /** 1차 규칙 기반 스코어 */
    @Column(name = "rule_score", precision = 5, scale = 2)
    private BigDecimal ruleScore;

    /** 최종 AI 스코어 (현재는 rule_score와 동일) */
    @Column(name = "ai_score", precision = 5, scale = 2)
    private BigDecimal aiScore;

    /** Risk:Reward 비율 (슬리피지 반영) */
    @Column(name = "rr_ratio", precision = 5, scale = 2)
    private BigDecimal rrRatio;

    /** 진입 판단: ENTER / CANCEL / HOLD */
    @Column(name = "action", length = 20)
    private String action;

    /** 신뢰도: HIGH / MEDIUM / LOW */
    @Column(name = "confidence", length = 10)
    private String confidence;

    /** 판단 사유 */
    @Column(name = "ai_reason", columnDefinition = "TEXT")
    private String aiReason;

    /** TP 계산 방법 (swing_resistance / fib_1272 / MA20_x099 등) */
    @Column(name = "tp_method", length = 60)
    private String tpMethod;

    /** SL 계산 방법 (swing_low_x099 / MA20_x099 / ATR_x20 등) */
    @Column(name = "sl_method", length = 60)
    private String slMethod;

    /** R:R < 1.0 경보 플래그 */
    @Column(name = "skip_entry")
    @Builder.Default
    private Boolean skipEntry = false;

    /** 스코어링 완료 시각 */
    @Column(name = "scored_at")
    private OffsetDateTime scoredAt;

    // ── 신호 시점 기술지표 스냅샷 ─────────────────────────────────────────
    @Column(name = "ma5_at_signal", precision = 10, scale = 0)
    private BigDecimal ma5AtSignal;

    @Column(name = "ma20_at_signal", precision = 10, scale = 0)
    private BigDecimal ma20AtSignal;

    @Column(name = "ma60_at_signal", precision = 10, scale = 0)
    private BigDecimal ma60AtSignal;

    @Column(name = "rsi14_at_signal", precision = 5, scale = 2)
    private BigDecimal rsi14AtSignal;

    @Column(name = "bb_upper_at_sig", precision = 10, scale = 0)
    private BigDecimal bbUpperAtSig;

    @Column(name = "bb_lower_at_sig", precision = 10, scale = 0)
    private BigDecimal bbLowerAtSig;

    @Column(name = "atr_at_signal", precision = 10, scale = 2)
    private BigDecimal atrAtSignal;

    // ── 신호 시점 시장 컨텍스트 ──────────────────────────────────────────
    @Column(name = "market_flu_rt", precision = 6, scale = 3)
    private BigDecimal marketFluRt;

    /** 신호 시점 뉴스 감성: BULLISH / NEUTRAL / BEARISH */
    @Column(name = "news_sentiment", length = 20)
    private String newsSentiment;

    /** 신호 시점 매매 제어 상태 */
    @Column(name = "news_ctrl", length = 20)
    private String newsCtrl;

    // ── 청산 결과 (Java ForceCloseScheduler 기록) ─────────────────────────
    /** TP1_HIT / TP2_HIT / SL_HIT / FORCE_CLOSE / EXPIRED */
    @Column(name = "exit_type", length = 20)
    private String exitType;

    @Column(name = "exit_price", precision = 10, scale = 0)
    private BigDecimal exitPrice;

    /** 슬리피지 반영 실현 수익률 */
    @Column(name = "exit_pnl_pct", precision = 7, scale = 4)
    private BigDecimal exitPnlPct;

    /** 손익 원화 */
    @Column(name = "exit_pnl_abs", precision = 14, scale = 0)
    private BigDecimal exitPnlAbs;

    @Column(name = "hold_duration_min")
    private Integer holdDurationMin;

    @Column(name = "exited_at")
    private OffsetDateTime exitedAt;

    @Column(name = "tp1_hit_at")
    private OffsetDateTime tp1HitAt;

    @Column(name = "tp1_exit_qty")
    private Integer tp1ExitQty;

    @Column(name = "remaining_qty")
    private Integer remainingQty;

    @Column(name = "peak_price", precision = 10, scale = 0)
    private BigDecimal peakPrice;

    @Column(name = "trailing_pct", precision = 5, scale = 2)
    private BigDecimal trailingPct;

    @Column(name = "trailing_activation", precision = 10, scale = 0)
    private BigDecimal trailingActivation;

    @Column(name = "trailing_basis", length = 40)
    private String trailingBasis;

    @Column(name = "strategy_version", length = 40)
    private String strategyVersion;

    @Column(name = "time_stop_type", length = 30)
    private String timeStopType;

    @Column(name = "time_stop_minutes")
    private Integer timeStopMinutes;

    @Column(name = "time_stop_session", length = 30)
    private String timeStopSession;

    @Column(name = "monitor_enabled")
    @Builder.Default
    private Boolean monitorEnabled = true;

    @Column(name = "is_overnight")
    @Builder.Default
    private Boolean isOvernight = false;

    @Column(name = "overnight_verdict", length = 20)
    private String overnightVerdict;

    @Column(name = "overnight_score", precision = 5, scale = 2)
    private BigDecimal overnightScore;

    @Column(name = "sl_alert_sent")
    @Builder.Default
    private Boolean slAlertSent = false;

    // ── 도메인 메서드 ────────────────────────────────────────────────────
    public void updateStatus(SignalStatus status) {
        this.signalStatus = status;
    }

    public void closeSignal(double pnl) {
        this.realizedPnl = pnl;
        this.closedAt = KstClock.now();
        this.positionStatus = "CLOSED";
        this.signalStatus = pnl >= 0 ? SignalStatus.WIN : SignalStatus.LOSS;
    }

    /** ForceCloseScheduler 가 청산 결과를 기록할 때 사용 */
    public void recordExit(String exitType, BigDecimal exitPrice,
                           BigDecimal exitPnlPct, BigDecimal exitPnlAbs,
                           int holdDurationMin) {
        this.exitType = exitType;
        this.exitPrice = exitPrice;
        this.exitPnlPct = exitPnlPct;
        this.exitPnlAbs = exitPnlAbs;
        this.holdDurationMin = holdDurationMin;
        this.exitedAt = KstClock.nowOffset();
        this.closedAt = KstClock.now();
        this.positionStatus = "CLOSED";
        if (exitType.startsWith("TP")) {
            this.signalStatus = SignalStatus.WIN;
        } else if ("SL_HIT".equals(exitType) || "FORCE_CLOSE".equals(exitType)) {
            this.signalStatus = SignalStatus.LOSS;
        } else {
            this.signalStatus = SignalStatus.EXPIRED;
        }
    }

    public boolean isActivePosition() {
        return "ACTIVE".equals(positionStatus)
                || "PARTIAL_TP".equals(positionStatus)
                || "OVERNIGHT".equals(positionStatus);
    }

    public void activatePosition() {
        this.positionStatus = "ACTIVE";
        if (this.entryAt == null) {
            this.entryAt = KstClock.nowOffset();
        }
    }

    public void markTp1Hit(int exitQty, int remainingQty, BigDecimal currentPrice) {
        this.tp1HitAt = KstClock.nowOffset();
        this.tp1ExitQty = exitQty;
        this.remainingQty = remainingQty;
        this.peakPrice = currentPrice;
        this.positionStatus = "PARTIAL_TP";
    }

    public void markOvernight(String verdict, BigDecimal score) {
        this.overnightVerdict = verdict;
        this.overnightScore = score;
        this.isOvernight = true;
        if ("HOLD".equalsIgnoreCase(verdict)) {
            this.positionStatus = "OVERNIGHT";
            this.signalStatus = SignalStatus.OVERNIGHT_HOLD;
        }
    }

    public enum SignalStatus {
        PENDING, SENT, EXECUTED, WIN, LOSS, EXPIRED, CANCELLED, OVERNIGHT_HOLD
    }

    public enum StrategyType {
        // ── 장전/시초가 ──────────────────────────
        S1_GAP_OPEN,        // 갭상승 + 체결강도 시초가
        S7_AUCTION,         // 레거시 동시호가 예상체결 갭 필터 (기존 데이터 호환용)
        S7_ICHIMOKU_BREAKOUT, // 일목균형표 구름대 돌파 스윙
        // ── 단기 이벤트 ─────────────────────────
        S2_VI_PULLBACK,     // VI 발동 후 눌림목 재진입
        S4_BIG_CANDLE,      // 장대양봉 + 거래량 급증 추격
        // ── 수급 기반 ────────────────────────────
        S3_INST_FRGN,       // 기관+외인 동시 순매수 돌파
        S5_PROG_FRGN,       // 프로그램 순매수 + 외인 동반
        S11_FRGN_CONT,      // 외국인 연속 순매수 스윙 (5일+)
        // ── 테마 ─────────────────────────────────
        S6_THEME_LAGGARD,   // 테마 상위 + 후발주
        // ── 스윙 / 기술적 ────────────────────────
        S8_GOLDEN_CROSS,    // 5일선 골든크로스 스윙
        S9_PULLBACK_SWING,  // 정배열 눌림목 지지 반등 스윙
        S10_NEW_HIGH,       // 52주 신고가 돌파 스윙
        S13_BOX_BREAKOUT,   // 거래량 폭발 박스권 돌파 스윙
        // ── 다중지표 기반 (신규) ─────────────────
        S14_OVERSOLD_BOUNCE, // 과매도 오실레이터 수렴 반등
        S15_MOMENTUM_ALIGN,  // 다중지표 모멘텀 동조 스윙
        // ── 종가 ─────────────────────────────────
        S12_CLOSING         // 종가 강도 확인 매수 (익일 갭)
    }
}
