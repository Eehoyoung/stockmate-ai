package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.DailyIndicators;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface DailyIndicatorsRepository extends JpaRepository<DailyIndicators, Long> {

    Optional<DailyIndicators> findByDateAndStkCd(LocalDate date, String stkCd);

    List<DailyIndicators> findByDateOrderByComputedAtDesc(LocalDate date);
}
