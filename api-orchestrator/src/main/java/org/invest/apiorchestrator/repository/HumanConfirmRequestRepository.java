package org.invest.apiorchestrator.repository;

import org.invest.apiorchestrator.domain.HumanConfirmRequest;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface HumanConfirmRequestRepository extends JpaRepository<HumanConfirmRequest, Long> {

    Optional<HumanConfirmRequest> findBySignalIdAndStatus(Long signalId, String status);

    List<HumanConfirmRequest> findByStatusAndExpiresAtBefore(String status, OffsetDateTime now);
}
