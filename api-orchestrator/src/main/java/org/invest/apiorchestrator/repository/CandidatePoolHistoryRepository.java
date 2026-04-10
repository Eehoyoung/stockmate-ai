package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.CandidatePoolHistory;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDate;
import java.util.List;

public interface CandidatePoolHistoryRepository extends JpaRepository<CandidatePoolHistory, Long> {

    /** 당일 특정 전략의 전체 기록 (appear_count 내림차순) */
    List<CandidatePoolHistory> findByDateAndStrategyOrderByAppearCountDesc(
            LocalDate date, String strategy);

    /** 당일 특정 종목이 등장한 전략 목록 */
    List<CandidatePoolHistory> findByDateAndStkCd(LocalDate date, String stkCd);

    /**
     * 신호 발행 시 led_to_signal = TRUE 로 갱신.
     * SignalService 에서 신호 저장 직후 호출.
     */
    @Modifying
    @Query(value = """
            UPDATE candidate_pool_history
               SET led_to_signal = TRUE,
                   signal_id     = :signalId
             WHERE date      = :date
               AND strategy  = :strategy
               AND market    = :market
               AND stk_cd    = :stkCd
            """, nativeQuery = true)
    void markLedToSignal(
            @Param("date")     LocalDate date,
            @Param("strategy") String strategy,
            @Param("market")   String market,
            @Param("stkCd")    String stkCd,
            @Param("signalId") Long signalId);
}
