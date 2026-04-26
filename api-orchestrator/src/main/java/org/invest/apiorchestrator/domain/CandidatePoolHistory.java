package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * candidate_pool_history — 전략별 Redis 후보 풀 스냅샷 이력.
 *
 * CandidatePoolHistoryScheduler 가 1분마다 candidates:s{N}:{market} 를 읽어
 * ON CONFLICT (date, strategy, market, stk_cd) DO UPDATE 로 UPSERT 한다.
 *
 * - appear_count : 당일 해당 풀에 몇 번 관찰됐는지 (TTL 내 빈도)
 * - pool_score   : 풀 내 순위 기반 점수 (1위=100, 꼴찌≈0)
 * - led_to_signal: SignalService 가 신호 발행 시 TRUE 로 갱신
 */
@Entity
@Table(name = "candidate_pool_history")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class CandidatePoolHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "date", nullable = false)
    private LocalDate date;

    @Column(name = "strategy", nullable = false, length = 30)
    private String strategy;

    @Column(name = "market", nullable = false, length = 10)
    private String market;

    @Column(name = "stk_cd", nullable = false, length = 20)
    private String stkCd;

    @Column(name = "stk_nm", length = 100)
    private String stkNm;

    @Column(name = "pool_score", precision = 5, scale = 2)
    private BigDecimal poolScore;

    @Column(name = "appear_count")
    @Builder.Default
    private Integer appearCount = 1;

    @Column(name = "first_seen", nullable = false)
    @Builder.Default
    private OffsetDateTime firstSeen = KstClock.nowOffset();

    @Column(name = "last_seen", nullable = false)
    @Builder.Default
    private OffsetDateTime lastSeen = KstClock.nowOffset();

    @Column(name = "led_to_signal")
    @Builder.Default
    private Boolean ledToSignal = false;

    /**
     * 연결된 trading_signals.id.
     * V33에서 FK fk_cph_stk_cd (stk_cd → stock_master) 추가됨.
     * signal_id 는 ON DELETE SET NULL (V13 정의).
     */
    @Column(name = "signal_id")
    private Long signalId;
}
