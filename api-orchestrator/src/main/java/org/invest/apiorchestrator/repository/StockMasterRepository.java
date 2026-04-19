package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.StockMaster;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface StockMasterRepository extends JpaRepository<StockMaster, String> {

    List<StockMaster> findByIsActiveTrue();

    List<StockMaster> findByMarketAndIsActiveTrue(String market);

    List<StockMaster> findBySectorAndIsActiveTrue(String sector);

    Optional<StockMaster> findByStkCd(String stkCd);
}
