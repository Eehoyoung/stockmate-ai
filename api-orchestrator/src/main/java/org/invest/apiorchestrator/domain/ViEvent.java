package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

@Entity
@Table(name = "vi_events", indexes = {
        @Index(name = "idx_vi_stk_cd", columnList = "stk_cd"),
        @Index(name = "idx_vi_created_at", columnList = "created_at")
})
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ViEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "vi_seq")
    @SequenceGenerator(name = "vi_seq", sequenceName = "vi_events_seq", allocationSize = 50)
    private Long id;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    @Column(name = "stk_nm", length = 40)
    private String stkNm;

    @Column(name = "vi_type", length = 2)
    private String viType;  // 1:정적, 2:동적, 3:동적+정적

    @Column(name = "vi_status", length = 2)
    private String viStatus;  // 1:발동, 2:해제

    @Column(name = "vi_price")
    private Double viPrice;

    @Column(name = "acc_volume")
    private Long accVolume;

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

    @Column(name = "released_at")
    private LocalDateTime releasedAt;

    public boolean isDynamic() {
        return "2".equals(viType) || "3".equals(viType);
    }

    public boolean isActive() {
        return "1".equals(viStatus);
    }
}
