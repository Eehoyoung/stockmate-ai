package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.KiwoomToken;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.Optional;

@Repository
public interface KiwoomTokenRepository extends JpaRepository<KiwoomToken, Long> {

    Optional<KiwoomToken> findTopByActiveTrueOrderByUpdatedAtDesc();

    @Modifying
    @Query("UPDATE KiwoomToken t SET t.active = false WHERE t.active = true")
    int deactivateAllTokens();

    @Modifying
    @Query("DELETE FROM KiwoomToken t WHERE t.active = false AND t.updatedAt < :before")
    int deleteOldInactiveTokens(@Param("before") LocalDateTime before);
}
