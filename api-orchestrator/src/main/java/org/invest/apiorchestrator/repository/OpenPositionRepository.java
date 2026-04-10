package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.OpenPosition;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface OpenPositionRepository extends JpaRepository<OpenPosition, Long> {

    Optional<OpenPosition> findBySignalId(Long signalId);

    /** 특정 종목의 활성 포지션 존재 여부 (이중매수 방지) */
    @Query("SELECT COUNT(p) > 0 FROM OpenPosition p " +
           "WHERE p.stkCd = :stkCd AND p.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')")
    boolean existsActivePosition(@Param("stkCd") String stkCd);

    /** 모든 활성 포지션 목록 (ForceCloseScheduler 용) */
    @Query("SELECT p FROM OpenPosition p WHERE p.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')")
    List<OpenPosition> findAllActivePositions();

    /** 활성 포지션 수 (최대 포지션 수 제한 체크) */
    @Query("SELECT COUNT(p) FROM OpenPosition p WHERE p.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')")
    long countActivePositions();

    /** 전략별 활성 포지션 수 */
    @Query("SELECT COUNT(p) FROM OpenPosition p " +
           "WHERE p.strategy = :strategy AND p.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')")
    long countActiveByStrategy(@Param("strategy") String strategy);

    /** 오버나잇 판단 대상 포지션 (ForceCloseScheduler 14:50 배치용) */
    @Query("SELECT p FROM OpenPosition p WHERE p.status IN ('ACTIVE', 'PARTIAL_TP') " +
           "AND p.isOvernight = FALSE")
    List<OpenPosition> findOvernightCandidates();
}
