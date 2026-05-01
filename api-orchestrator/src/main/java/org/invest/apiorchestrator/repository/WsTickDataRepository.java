package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.WsTickData;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

@Repository
public interface WsTickDataRepository extends JpaRepository<WsTickData, Long> {

    List<WsTickData> findByStkCdAndTickTypeAndCreatedAtAfterOrderByCreatedAtDesc(
            String stkCd, String tickType, LocalDateTime after);

    @Modifying
    @Query("DELETE FROM WsTickData w WHERE w.createdAt < :before AND w.mustPersist = false")
    int deleteOldTickData(@Param("before") LocalDateTime before);
}
