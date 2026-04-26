package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.TradeOutcome;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface TradeOutcomeRepository extends JpaRepository<TradeOutcome, Long> {

    Optional<TradeOutcome> findBySignalId(Long signalId);
}
