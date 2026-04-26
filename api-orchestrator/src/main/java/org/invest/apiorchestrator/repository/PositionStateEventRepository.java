package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.PositionStateEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PositionStateEventRepository extends JpaRepository<PositionStateEvent, Long> {

    List<PositionStateEvent> findBySignalIdOrderByEventTsDesc(Long signalId);
}
