package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * strategy_param_history — 전략 파라미터 변경 이력.
 * 임계값 변경 전후 성과 비교를 위해 불변 감사 추적.
 */
@Entity
@Table(name = "strategy_param_history",
    indexes = @Index(name = "idx_sph_strategy", columnList = "strategy, changed_at DESC"))
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StrategyParamHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "strategy", nullable = false, length = 30)
    private String strategy;

    @Column(name = "param_name", nullable = false, length = 50)
    private String paramName;

    @Column(name = "old_value", length = 100)
    private String oldValue;

    @Column(name = "new_value", nullable = false, length = 100)
    private String newValue;

    @Column(name = "changed_at", nullable = false)
    @Builder.Default
    private OffsetDateTime changedAt = KstClock.nowOffset();

    @Column(name = "changed_by", length = 50)
    private String changedBy;

    @Column(name = "reason")
    private String reason;
}
