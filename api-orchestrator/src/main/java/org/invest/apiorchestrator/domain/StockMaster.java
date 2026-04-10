package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * stock_master — 종목 기준 정보.
 * StockMasterScheduler (월요일 07:00) 가 전종목 UPSERT.
 */
@Entity
@Table(name = "stock_master",
    indexes = {
        @Index(name = "idx_sm_market", columnList = "market"),
        @Index(name = "idx_sm_sector", columnList = "sector")
    })
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StockMaster {

    @Id
    @Column(name = "stk_cd", length = 20)
    private String stkCd;

    @Column(name = "stk_nm", nullable = false, length = 100)
    private String stkNm;

    @Column(name = "market", length = 10)
    private String market;

    @Column(name = "sector", length = 50)
    private String sector;

    @Column(name = "industry", length = 50)
    private String industry;

    @Column(name = "listed_at")
    private LocalDate listedAt;

    @Column(name = "par_value")
    private Integer parValue;

    @Column(name = "listed_shares")
    private Long listedShares;

    @Column(name = "is_active")
    @Builder.Default
    private Boolean isActive = true;

    @Column(name = "last_price", precision = 10, scale = 0)
    private BigDecimal lastPrice;

    @Column(name = "last_price_date")
    private LocalDate lastPriceDate;

    @Column(name = "updated_at")
    @Builder.Default
    private OffsetDateTime updatedAt = OffsetDateTime.now();
}
