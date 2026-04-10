package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.DailyPnl;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface DailyPnlRepository extends JpaRepository<DailyPnl, Long> {

    Optional<DailyPnl> findByDate(LocalDate date);

    /** 최근 N일 손익 (성과 리포트용) */
    @Query("SELECT p FROM DailyPnl p ORDER BY p.date DESC")
    List<DailyPnl> findRecentDays(org.springframework.data.domain.Pageable pageable);

    /** 특정 기간 손익 합계 */
    @Query("SELECT SUM(p.netPnlAbs) FROM DailyPnl p WHERE p.date BETWEEN :from AND :to")
    java.math.BigDecimal sumNetPnlBetween(LocalDate from, LocalDate to);
}
