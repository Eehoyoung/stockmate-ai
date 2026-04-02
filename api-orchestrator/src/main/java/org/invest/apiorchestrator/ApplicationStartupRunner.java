package org.invest.apiorchestrator;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.TokenService;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class ApplicationStartupRunner implements ApplicationRunner {

    private final TokenService tokenService;

    @Override
    public void run(ApplicationArguments args) {
        log.info("=== 키움 트레이딩 시스템 시작 ===");

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
