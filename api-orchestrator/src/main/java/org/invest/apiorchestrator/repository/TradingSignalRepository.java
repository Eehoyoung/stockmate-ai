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
        SELECT s.strategy, COUNT(s), AVG(s.aiScore)
        FROM TradingSignal s
        WHERE s.action = 'ENTER'
          AND s.signalStatus IN ('SENT','EXPIRED','WIN','LOSS')
          AND s.createdAt >= :startAt
        GROUP BY s.strategy
        """)
    List<Object[]> getStrategyStats(@Param("startAt") LocalDateTime startAt);

    boolean existsByStkCdAndStrategyAndCreatedAtAfter(
            String stkCd, TradingSignal.StrategyType strategy, LocalDateTime after);

    /**
     * Feature 1 – 전략별 가상 성과 통계 (WIN/LOSS/SENT 포함)
     * 반환: [strategy, total, wins, losses, avgPnl]
     */
    @Query("""
        SELECT s.strategy,
               COUNT(s),
               SUM(CASE WHEN s.signalStatus = 'WIN'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN s.signalStatus = 'LOSS' THEN 1 ELSE 0 END),
               AVG(CASE WHEN s.realizedPnl IS NOT NULL THEN s.realizedPnl ELSE 0 END)
        FROM TradingSignal s
        WHERE s.createdAt >= :startAt
          AND s.signalStatus IN ('WIN', 'LOSS', 'SENT', 'EXPIRED')
        GROUP BY s.strategy
        """)
    List<Object[]> getStrategyPerformanceStats(@Param("startAt") LocalDateTime startAt);
}
