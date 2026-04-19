package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.StrategyParamSnapshotService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class StrategyParamSnapshotScheduler {

    private final StrategyParamSnapshotService strategyParamSnapshotService;

    @Scheduled(cron = "0 5 7 * * MON-FRI", zone = "Asia/Seoul")
    public void snapshotCurrentParams() {
        try {
            strategyParamSnapshotService.syncCurrentParams("SYSTEM_SNAPSHOT", "Scheduled current parameter snapshot");
        } catch (Exception e) {
            log.warn("[StrategyParam] scheduled snapshot failed: {}", e.getMessage());
        }
    }
}
