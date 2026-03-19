package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

@Entity
@Table(name = "ws_tick_data", indexes = {
        @Index(name = "idx_tick_stk_cd_created", columnList = "stk_cd, created_at")
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

    @Column(name = "pred_pre")
    private Double predPre;

    @Column(name = "flu_rt")
    private Double fluRt;

    @Column(name = "acc_trde_qty")
    private Long accTrdeQty;

    @Column(name = "acc_trde_prica")
    private Long accTrdePrica;

    @Column(name = "cntr_str")
    private Double cntrStr;

    @Column(name = "total_bid_qty")
    private Long totalBidQty;

    @Column(name = "total_ask_qty")
    private Long totalAskQty;

    @Column(name = "bid_ask_ratio")
    private Double bidAskRatio;

    @Column(name = "tick_type", length = 4)
    private String tickType;  // 0B체결, 0D호가, 0H예상체결

    @CreatedDate
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
