package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.EconomicEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;

@Repository
public interface EconomicEventRepository extends JpaRepository<EconomicEvent, Long> {

    List<EconomicEvent> findByEventDateBetweenOrderByEventDateAsc(LocalDate from, LocalDate to);

    List<EconomicEvent> findByEventDateOrderByEventTimeAsc(LocalDate date);

    @Query("""
        SELECT e FROM EconomicEvent e
        WHERE e.eventDate = :date
          AND e.notified = false
          AND e.expectedImpact = 'HIGH'
        ORDER BY e.eventTime ASC NULLS LAST
        """)
    List<EconomicEvent> findUnnotifiedHighImpactToday(@Param("date") LocalDate date);
}
