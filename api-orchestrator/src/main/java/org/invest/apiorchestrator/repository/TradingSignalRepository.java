package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface TradingSignalRepository extends JpaRepository<TradingSignal, Long> {

    List<TradingSignal> findByStkCdAndCreatedAtAfterOrderByCreatedAtDesc(
            String stkCd, LocalDateTime after);

    List<TradingSignal> findByStrategyAndCreatedAtAfterOrderBySignalScoreDesc(
            TradingSignal.StrategyType strategy, LocalDateTime after);

    List<TradingSignal> findBySignalStatusAndCreatedAtAfter(
            TradingSignal.SignalStatus status, LocalDateTime after);

    Optional<TradingSignal> findTopByStkCdAndStrategyAndCreatedAtAfterOrderByCreatedAtDesc(
            String stkCd, TradingSignal.StrategyType strategy, LocalDateTime after);

    @Query("""
        SELECT s FROM TradingSignal s
        WHERE s.createdAt >= :startAt
        ORDER BY s.signalScore DESC NULLS LAST, s.createdAt DESC
        """)
    List<TradingSignal> findTodaySignals(@Param("startAt") LocalDateTime startAt);

    @Query("""
        SELECT s FROM TradingSignal s
        WHERE s.createdAt >= :startAt
          AND s.signalStatus IN ('PENDING','SENT')
        ORDER BY s.createdAt DESC
        """)
    List<TradingSignal> findActiveTodaySignals(@Param("startAt") LocalDateTime startAt);

    @Modifying
    @Query("""
        UPDATE TradingSignal s SET s.signalStatus = 'EXPIRED'
        WHERE s.signalStatus IN ('PENDING','SENT')
          AND s.createdAt < :expireBefore
        """)
    int expireOldSignals(@Param("expireBefore") LocalDateTime expireBefore);

    @Query("""
        SELECT s.strategy, COUNT(s), AVG(s.realizedPnl)
        FROM TradingSignal s
        WHERE s.signalStatus IN ('WIN','LOSS')
          AND s.createdAt >= :startAt
        GROUP BY s.strategy
        """)
    List<Object[]> getStrategyStats(@Param("startAt") LocalDateTime startAt);

    boolean existsByStkCdAndStrategyAndCreatedAtAfter(
            String stkCd, TradingSignal.StrategyType strategy, LocalDateTime after);
}
