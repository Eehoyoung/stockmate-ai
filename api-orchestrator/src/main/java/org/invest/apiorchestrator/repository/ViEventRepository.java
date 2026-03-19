package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.ViEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface ViEventRepository extends JpaRepository<ViEvent, Long> {

    List<ViEvent> findByStkCdAndCreatedAtAfterOrderByCreatedAtDesc(
            String stkCd, LocalDateTime after);

    Optional<ViEvent> findTopByStkCdAndViStatusOrderByCreatedAtDesc(
            String stkCd, String viStatus);

    @Query("""
        SELECT v FROM ViEvent v
        WHERE v.viStatus = '1'
          AND v.releasedAt IS NULL
          AND v.createdAt >= :after
        ORDER BY v.createdAt DESC
        """)
    List<ViEvent> findActiveViEvents(@Param("after") LocalDateTime after);

    @Query("""
        SELECT COUNT(v) FROM ViEvent v
        WHERE v.stkCd = :stkCd
          AND v.createdAt >= :after
        """)
    long countViEventsByStkCd(@Param("stkCd") String stkCd,
                              @Param("after") LocalDateTime after);
}
