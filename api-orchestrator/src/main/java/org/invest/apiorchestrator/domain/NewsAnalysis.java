package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

/**
 * 뉴스 분석 결과 엔티티.
 * Python news_scheduler 가 Claude API로 분석한 결과를 DB에 영속화한다.
 *
 * V33: 구형 컬럼 headline(→summary로 이관), sector 제거됨 (V1 baseline 잔재, 엔티티에 없음).
 *      sectors, risk_factors, summary, confidence, news_count 는 V22에서 추가됨.
 */
@Entity
@Table(name = "news_analysis", indexes = {
        @Index(name = "idx_news_analysis_at", columnList = "analyzed_at")
})
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class NewsAnalysis {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "news_analysis_seq")
    @SequenceGenerator(name = "news_analysis_seq", sequenceName = "news_analysis_seq", allocationSize = 10)
    private Long id;

    @Column(name = "analyzed_at", nullable = false)
    private LocalDateTime analyzedAt;

    /** BULLISH / NEUTRAL / BEARISH */
    @Column(name = "sentiment", length = 10)
    private String sentiment;

    /** CONTINUE / CAUTIOUS / PAUSE */
    @Column(name = "trading_ctrl", length = 10)
    private String tradingCtrl;

    /** JSON 배열 – 추천 섹터 목록 */
    @Column(name = "sectors", columnDefinition = "TEXT")
    private String sectors;

    /** JSON 배열 – 리스크 요인 목록 */
    @Column(name = "risk_factors", columnDefinition = "TEXT")
    private String riskFactors;

    /** Claude 분석 요약 */
    @Column(name = "summary", columnDefinition = "TEXT")
    private String summary;

    /** HIGH / MEDIUM / LOW */
    @Column(name = "confidence", length = 10)
    private String confidence;

    /** 분석된 뉴스 건수 */
    @Column(name = "news_count")
    private Integer newsCount;
}
