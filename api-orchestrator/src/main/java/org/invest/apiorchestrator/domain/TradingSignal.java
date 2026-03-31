package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

@Entity
@Table(name = "trading_signals", indexes = {
        @Index(name = "idx_signal_stk_cd", columnList = "stk_cd"),
        @Index(name = "idx_signal_strategy", columnList = "strategy"),
        @Index(name = "idx_signal_created_at", columnList = "created_at")
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

    @Column(name = "signal_score")
    private Double signalScore;

    @Column(name = "entry_price")
    private Double entryPrice;

    @Column(name = "target_price")
    private Double targetPrice;

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

    public void updateStatus(SignalStatus status) {
        this.signalStatus = status;
    }

    public void closeSignal(double pnl) {
        this.realizedPnl = pnl;
        this.closedAt = LocalDateTime.now();
        this.signalStatus = pnl >= 0 ? SignalStatus.WIN : SignalStatus.LOSS;
    }

    public enum SignalStatus {
        PENDING, SENT, EXECUTED, WIN, LOSS, EXPIRED, CANCELLED, OVERNIGHT_HOLD
    }

    public enum StrategyType {
        // ── 장전/시초가 ──────────────────────────
        S1_GAP_OPEN,        // 갭상승 + 체결강도 시초가
        S7_AUCTION,         // 동시호가 예상체결 갭 필터
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
