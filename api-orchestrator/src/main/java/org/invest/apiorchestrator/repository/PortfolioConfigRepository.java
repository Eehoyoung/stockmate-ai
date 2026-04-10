package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.PortfolioConfig;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PortfolioConfigRepository extends JpaRepository<PortfolioConfig, Integer> {

    /** 싱글턴 설정 행 조회 (id=1) */
    default Optional<PortfolioConfig> findSingleton() {
        return findById(1);
    }
}
