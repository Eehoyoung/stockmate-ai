package org.invest.apiorchestrator;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.PortfolioConfig;
import org.invest.apiorchestrator.repository.PortfolioConfigRepository;
import org.invest.apiorchestrator.service.StrategyParamSnapshotService;
import org.invest.apiorchestrator.service.TokenService;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class ApplicationStartupRunner implements ApplicationRunner {

    private final TokenService tokenService;
    private final PortfolioConfigRepository portfolioConfigRepository;
    private final StrategyParamSnapshotService strategyParamSnapshotService;

    @Override
    public void run(ApplicationArguments args) {
        log.info("=== Stockmate Trading System Startup ===");

        try {
            if (portfolioConfigRepository.findSingleton().isEmpty()) {
                portfolioConfigRepository.save(PortfolioConfig.builder().build());
                log.info("[Startup] portfolio_config bootstrap complete");
            } else {
                log.info("[Startup] portfolio_config already initialized");
            }
        } catch (Exception e) {
            log.warn("[Startup] portfolio_config bootstrap failed: {}", e.getMessage());
        }

        try {
            strategyParamSnapshotService.syncCurrentParams(
                    "SYSTEM_BOOTSTRAP",
                    "Initial activation metadata snapshot"
            );
        } catch (Exception e) {
            log.warn("[Startup] strategy_param_history bootstrap failed: {}", e.getMessage());
        }

        try {
            tokenService.refreshToken();
            log.info("[Startup] initial token refresh complete");
        } catch (Exception e) {
            log.error("[Startup] initial token refresh failed - scheduler retry will handle it: {}", e.getMessage());
            return;
        }

        log.info("[Startup] WebSocket listener is managed by python websocket-listener");
        log.info("=== Startup Complete ===");
    }
}
