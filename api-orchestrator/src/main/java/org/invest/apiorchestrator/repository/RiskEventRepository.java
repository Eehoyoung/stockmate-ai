package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.RiskEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.OffsetDateTime;
import java.util.List;

public interface RiskEventRepository extends JpaRepository<RiskEvent, Long> {

    List<RiskEvent> findByEventTypeOrderByOccurredAtDesc(String eventType);

    @Query("SELECT e FROM RiskEvent e WHERE e.occurredAt >= :since ORDER BY e.occurredAt DESC")
    List<RiskEvent> findRecent(@Param("since") OffsetDateTime since);

    @Query("SELECT COUNT(e) FROM RiskEvent e WHERE e.eventType = 'DAILY_LOSS_LIMIT' AND e.occurredAt >= :since")
    long countDailyLossLimitHits(@Param("since") OffsetDateTime since);
}
