package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.SignalScoreComponents;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface SignalScoreComponentsRepository extends JpaRepository<SignalScoreComponents, Long> {

    Optional<SignalScoreComponents> findBySignalId(Long signalId);

    boolean existsBySignalId(Long signalId);
}
