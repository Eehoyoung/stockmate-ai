package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import org.invest.apiorchestrator.util.KstClock;

/**
 * human_confirm_requests — Telegram 인간 확인 요청 레코드 (V23)
 * <p>
 * Python ai-engine 이 PENDING 상태로 INSERT하고,
 * telegram-bot 이 SENT → CONFIRMED/REJECTED/EXPIRED 로 갱신한다.
 */
@Entity
@Table(name = "human_confirm_requests", indexes = {
        @Index(name = "idx_human_confirm_requests_status_expires", columnList = "status, expires_at"),
        @Index(name = "idx_human_confirm_requests_signal_id",      columnList = "signal_id")
})
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class HumanConfirmRequest {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 중복 요청 방지용 유니크 키 (예: stk_cd:strategy:signal_id) */
    @Column(name = "request_key", nullable = false, length = 80, unique = true)
    private String requestKey;

    /** trading_signals.id 참조 (nullable — 신호 삭제 후에도 이력 보존) */
    @Column(name = "signal_id")
    private Long signalId;

    @Column(name = "stk_cd", nullable = false, length = 16)
    private String stkCd;

    @Column(name = "stk_nm", length = 120)
    private String stkNm;

    @Column(name = "strategy", nullable = false, length = 64)
    private String strategy;

    @Column(name = "rule_score", precision = 6, scale = 2)
    private BigDecimal ruleScore;

    @Column(name = "rr_ratio", precision = 8, scale = 2)
    private BigDecimal rrRatio;

    /**
     * 요청 상태: PENDING / SENT / CONFIRMED / REJECTED / EXPIRED
     */
    @Column(name = "status", nullable = false, length = 24)
    @Builder.Default
    private String status = "PENDING";

    /** 원본 신호 페이로드 (JSON) */
    @Column(name = "payload", nullable = false, columnDefinition = "jsonb")
    @JdbcTypeCode(SqlTypes.JSON)
    private String payload;

    @Column(name = "requested_at", nullable = false)
    @Builder.Default
    private OffsetDateTime requestedAt = KstClock.nowOffset();

    @Column(name = "expires_at", nullable = false)
    private OffsetDateTime expiresAt;

    @Column(name = "decided_at")
    private OffsetDateTime decidedAt;

    @Column(name = "decision_chat_id")
    private Long decisionChatId;

    @Column(name = "decision_message_id")
    private Long decisionMessageId;

    @Column(name = "last_sent_at")
    private OffsetDateTime lastSentAt;

    @Column(name = "last_enqueued_at")
    private OffsetDateTime lastEnqueuedAt;

    // ── ai-engine 2차 분석 결과 ─────────────────────────────────────────────
    @Column(name = "ai_score", precision = 6, scale = 2)
    private BigDecimal aiScore;

    @Column(name = "ai_action", length = 24)
    private String aiAction;

    @Column(name = "ai_confidence", length = 24)
    private String aiConfidence;

    @Column(name = "ai_reason", columnDefinition = "TEXT")
    private String aiReason;
}
