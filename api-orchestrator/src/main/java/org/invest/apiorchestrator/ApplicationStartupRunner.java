package org.invest.apiorchestrator;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.PortfolioConfig;
import org.invest.apiorchestrator.repository.PortfolioConfigRepository;
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

    @Override
    public void run(ApplicationArguments args) {
        log.info("=== 키움 트레이딩 시스템 시작 ===");

        // portfolio_config 기본 행 보장 (없으면 INSERT)
        try {
            if (portfolioConfigRepository.findSingleton().isEmpty()) {
                PortfolioConfig defaultConfig = PortfolioConfig.builder().build();
                portfolioConfigRepository.save(defaultConfig);
                log.info("[Startup] portfolio_config 기본 행 생성 완료");
            } else {
                log.info("[Startup] portfolio_config 기본 행 확인 완료");
            }
        } catch (Exception e) {
            log.warn("[Startup] portfolio_config 초기화 실패 (무시): {}", e.getMessage());
        }

        // 토큰 발급
        try {
            tokenService.refreshToken();
            log.info("초기 토큰 발급 완료");
        } catch (Exception e) {
            log.error("초기 토큰 발급 실패 - 스케줄러에서 재시도: {}", e.getMessage());
            return;
        }

        // WebSocket 은 Python websocket-listener 가 단독 운영
        log.info("WebSocket: Python websocket-listener 단독 운영 중");
        log.info("=== 시스템 초기화 완료 ===");
    }
}
