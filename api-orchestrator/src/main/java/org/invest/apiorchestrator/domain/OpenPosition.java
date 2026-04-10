package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * open_positions — 실시간 포지션 원장
 * <p>
 * 이 테이블 없이는:
 * - 같은 종목 이중매수 방지 불가
 * - 최대 포지션 수 제한 불가
 * - 섹터별 익스포저 계산 불가
 * - 실시간 포트폴리오 P&amp;L 계산 불가
 * <p>
 * 쓰기 주체:
 * - Java SignalService        → ENTER 확정 시 INSERT
 * - Java ForceCloseScheduler  → TP/SL/FORCE_CLOSE 시 UPDATE
 * - Python overnight_worker   → overnight_verdict UPDATE
 */
@Entity
@Table(name = "open_positions", indexes = {
        @Index(name = "idx_op_stk_status",      columnList = "stk_cd, status"),
        @Index(name = "idx_op_strategy_status",  columnList = "strategy, status")
})
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class OpenPosition {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "signal_id", nullable = false, unique = true)
    private TradingSignal signal;

    @Column(name = "stk_cd", nullable = false, length = 20) private String stkCd;
    @Column(name = "stk_nm", length = 100)                  private String stkNm;
    @Column(name = "strategy", nullable = false, length = 30) private String strategy;
    @Column(name = "market", length = 10)                   private String market;
    @Column(name = "sector", length = 50)                   private String sector;

    // ── 진입 정보 ─────────────────────────────────────────────────────────
    @Column(name = "entry_price", nullable = false, precision = 10, scale = 0)
    private BigDecimal entryPrice;

    @Column(name = "entry_qty")   private Integer entryQty;
    @Column(name = "entry_amount", precision = 14, scale = 0) private BigDecimal entryAmount;

    @Column(name = "entry_at", nullable = false)
    @Builder.Default
    private OffsetDateTime entryAt = OffsetDateTime.now();

    // ── TP/SL ─────────────────────────────────────────────────────────────
    @Column(name = "tp1_price", precision = 10, scale = 0) private BigDecimal tp1Price;
    @Column(name = "tp2_price", precision = 10, scale = 0) private BigDecimal tp2Price;
    @Column(name = "sl_price",  nullable = false, precision = 10, scale = 0) private BigDecimal slPrice;
    @Column(name = "tp_method", length = 60) private String tpMethod;
    @Column(name = "sl_method", length = 60) private String slMethod;
    @Column(name = "rr_ratio",  precision = 5, scale = 2) private BigDecimal rrRatio;

    // ── 상태 ──────────────────────────────────────────────────────────────
    /** ACTIVE / PARTIAL_TP / OVERNIGHT / CLOSING / CLOSED */
    @Column(name = "status", nullable = false, length = 20)
    @Builder.Default
    private String status = "ACTIVE";

    // ── 부분 TP ───────────────────────────────────────────────────────────
    @Column(name = "tp1_hit_at")  private OffsetDateTime tp1HitAt;
    @Column(name = "tp1_exit_qty") private Integer tp1ExitQty;
    @Column(name = "remaining_qty") private Integer remainingQty;

    // ── 오버나잇 ──────────────────────────────────────────────────────────
    @Column(name = "is_overnight") @Builder.Default private Boolean isOvernight = false;
    @Column(name = "overnight_verdict", length = 20) private String overnightVerdict;
    @Column(name = "overnight_score", precision = 5, scale = 2) private BigDecimal overnightScore;

    // ── 알림 ──────────────────────────────────────────────────────────────
    @Column(name = "sl_alert_sent") @Builder.Default private Boolean slAlertSent = false;
    @Column(name = "rule_score", precision = 5, scale = 2) private BigDecimal ruleScore;
    @Column(name = "ai_score",   precision = 5, scale = 2) private BigDecimal aiScore;

    // ── 청산 완료 ─────────────────────────────────────────────────────────
    @Column(name = "closed_at") private OffsetDateTime closedAt;
    /** TP1_HIT / TP2_HIT / SL_HIT / FORCE_CLOSE / MANUAL */
    @Column(name = "exit_type", length = 20)  private String exitType;
    @Column(name = "exit_price", precision = 10, scale = 0) private BigDecimal exitPrice;
    @Column(name = "realized_pnl_pct", precision = 7, scale = 4) private BigDecimal realizedPnlPct;
    @Column(name = "realized_pnl_abs", precision = 14, scale = 0) private BigDecimal realizedPnlAbs;
    @Column(name = "hold_duration_min") private Integer holdDurationMin;

    // ── 도메인 메서드 ─────────────────────────────────────────────────────
    public boolean isActive() {
        return "ACTIVE".equals(status) || "PARTIAL_TP".equals(status) || "OVERNIGHT".equals(status);
    }

    public void markTp1Hit(int exitQty, int remainingQty, BigDecimal tp1Price) {
        this.tp1HitAt  = OffsetDateTime.now();
        this.tp1ExitQty = exitQty;
        this.remainingQty = remainingQty;
        this.exitPrice = tp1Price;
        this.status = "PARTIAL_TP";
    }

    public void close(String exitType, BigDecimal exitPrice,
                      BigDecimal pnlPct, BigDecimal pnlAbs, int holdMin) {
        this.exitType = exitType;
        this.exitPrice = exitPrice;
        this.realizedPnlPct = pnlPct;
        this.realizedPnlAbs = pnlAbs;
        this.holdDurationMin = holdMin;
        this.closedAt = OffsetDateTime.now();
        this.status = "CLOSED";
    }

    public void markOvernight(String verdict, BigDecimal score) {
        this.overnightVerdict = verdict;
        this.overnightScore = score;
        this.isOvernight = true;
        this.status = "OVERNIGHT";
    }
}
