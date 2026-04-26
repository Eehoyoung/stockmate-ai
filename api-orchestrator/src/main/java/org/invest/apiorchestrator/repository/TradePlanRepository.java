package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.TradePlan;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface TradePlanRepository extends JpaRepository<TradePlan, Long> {

    Optional<TradePlan> findFirstBySignalIdOrderByVariantRankAscIdAsc(Long signalId);

    List<TradePlan> findBySignalId(Long signalId);
}
