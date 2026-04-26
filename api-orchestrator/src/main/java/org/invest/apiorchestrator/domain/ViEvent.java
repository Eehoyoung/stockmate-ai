package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

// V33: trigger_price → vi_price, reference_price → ref_price 로 컬럼명 통일.
//      stk_nm, vi_status, vi_price, acc_volume, ref_price, upper_limit,
//      lower_limit, market_type, released_at 컬럼이 DB에 추가됨.
@Entity
@Table(name = "vi_events", indexes = {
        @Index(name = "idx_vi_stk_cd",     columnList = "stk_cd"),
        @Index(name = "idx_vi_created_at", columnList = "created_at"),
        @Index(name = "idx_vi_status_cd",  columnList = "vi_status, stk_cd")
})
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ViEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    @Column(name = "stk_nm", length = 40)
    private String stkNm;

    @Column(name = "vi_type", length = 2)
    private String viType;  // 1:정적, 2:동적, 3:동적+정적

    @Column(name = "vi_status", length = 2)
    private String viStatus;  // 1:발동, 2:해제

    /** VI 발동 가격 (V33: 구 trigger_price 컬럼에서 이관) */
    @Column(name = "vi_price")
    private Double viPrice;

    @Column(name = "acc_volume")
    private Long accVolume;

    /** 기준 가격 (V33: 구 reference_price 컬럼에서 이관) */
    @Column(name = "ref_price")
    private Double refPrice;

    @Column(name = "upper_limit")
    private Double upperLimit;

    @Column(name = "lower_limit")
    private Double lowerLimit;

    @Column(name = "market_type", length = 10)
    private String marketType;

    @CreatedDate
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    /** VI 해제 시각 (vi_status=2 시 채워짐) */
    @Column(name = "released_at")
    private LocalDateTime releasedAt;

    public boolean isDynamic() {
        return "2".equals(viType) || "3".equals(viType);
    }

    public boolean isActive() {
        return "1".equals(viStatus);
    }
}
