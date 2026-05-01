package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

// V33: V1 baseline 의 cntr_qty 컬럼 제거됨. 신규 컬럼 pred_pre, acc_trde_qty,
//      acc_trde_prica, cntr_str, total_bid_qty, total_ask_qty, bid_ask_ratio,
//      tick_type 이 DB에 추가됨.
@Entity
@Table(name = "ws_tick_data", indexes = {
        @Index(name = "idx_tick_stk_cd_created", columnList = "stk_cd, created_at"),
        @Index(name = "idx_tick_type_created",   columnList = "tick_type, created_at")
})
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WsTickData {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "tick_seq")
    @SequenceGenerator(name = "tick_seq", sequenceName = "ws_tick_data_seq", allocationSize = 200)
    private Long id;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    @Column(name = "cur_prc")
    private Double curPrc;

    /** 전일 종가 */
    @Column(name = "pred_pre")
    private Double predPre;

    @Column(name = "flu_rt")
    private Double fluRt;

    /** 누적 체결량 */
    @Column(name = "acc_trde_qty")
    private Long accTrdeQty;

    /** 누적 거래대금 */
    @Column(name = "acc_trde_prica")
    private Long accTrdePrica;

    /** 체결강도 (매수체결량/매도체결량 × 100) */
    @Column(name = "cntr_str")
    private Double cntrStr;

    @Column(name = "total_bid_qty")
    private Long totalBidQty;

    @Column(name = "total_ask_qty")
    private Long totalAskQty;

    @Column(name = "bid_ask_ratio")
    private Double bidAskRatio;

    /** 0B=체결, 0D=호가, 0H=예상체결 */
    @Column(name = "tick_type", length = 4)
    private String tickType;

    @Builder.Default
    @Column(name = "must_persist", nullable = false)
    private Boolean mustPersist = false;

    @CreatedDate
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
