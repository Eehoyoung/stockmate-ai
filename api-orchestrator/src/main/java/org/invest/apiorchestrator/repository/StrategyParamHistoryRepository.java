package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.StrategyParamHistory;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface StrategyParamHistoryRepository extends JpaRepository<StrategyParamHistory, Long> {

    List<StrategyParamHistory> findByStrategyOrderByChangedAtDesc(String strategy);

    List<StrategyParamHistory> findByStrategyAndParamNameOrderByChangedAtDesc(String strategy, String paramName);
}
