package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.KiwoomToken;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface KiwoomTokenRepository extends JpaRepository<KiwoomToken, Long> {

    Optional<KiwoomToken> findTopByActiveTrueOrderByUpdatedAtDesc();

    @Modifying
    @Query("UPDATE KiwoomToken t SET t.active = false WHERE t.active = true")
    int deactivateAllTokens();
}
