package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.StrategyDailyStat;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface StrategyDailyStatRepository extends JpaRepository<StrategyDailyStat, Long> {

    Optional<StrategyDailyStat> findByDateAndStrategy(LocalDate date, String strategy);

    List<StrategyDailyStat> findByDateOrderByStrategyAsc(LocalDate date);

    List<StrategyDailyStat> findByStrategyOrderByDateDesc(String strategy);
}
