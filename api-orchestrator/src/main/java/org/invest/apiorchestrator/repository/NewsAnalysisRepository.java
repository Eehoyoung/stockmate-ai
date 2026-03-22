package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.NewsAnalysis;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface NewsAnalysisRepository extends JpaRepository<NewsAnalysis, Long> {

    /** 가장 최근 분석 결과 1건 */
    Optional<NewsAnalysis> findTopByOrderByAnalyzedAtDesc();

    /** 특정 시간 이후 분석 결과 목록 */
    List<NewsAnalysis> findByAnalyzedAtAfterOrderByAnalyzedAtDesc(LocalDateTime since);
}
