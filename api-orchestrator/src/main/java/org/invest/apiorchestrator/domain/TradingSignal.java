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
        S1_GAP_OPEN, S2_VI_PULLBACK, S3_INST_FRGN,
        S4_BIG_CANDLE, S5_PROG_FRGN, S6_THEME_LAGGARD, S7_AUCTION
        , S8_VI_OPEN, S9_VI_CLOSE, S10_NEW_HIGH, S11_FRGN_CONT, S12_CLOSING
    }
}
