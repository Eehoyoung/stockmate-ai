package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.MarketDailyContext;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.Optional;

public interface MarketDailyContextRepository extends JpaRepository<MarketDailyContext, Long> {

    Optional<MarketDailyContext> findByDate(LocalDate date);

    boolean existsByDate(LocalDate date);
}
