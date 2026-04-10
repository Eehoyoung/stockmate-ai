package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.OvernightEvaluation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

public interface OvernightEvaluationRepository extends JpaRepository<OvernightEvaluation, Long> {

    Optional<OvernightEvaluation> findBySignalId(Long signalId);

    /** 익일 검증이 아직 안 된 HOLD 결정 목록 (next_day_open IS NULL) */
    @Query("SELECT e FROM OvernightEvaluation e WHERE e.verdict = 'HOLD' AND e.nextDayOpen IS NULL AND e.evaluatedAt < :cutoff")
    List<OvernightEvaluation> findPendingVerification(@Param("cutoff") OffsetDateTime cutoff);
}
