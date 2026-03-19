package org.invest.apiorchestrator;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.TokenService;
import org.invest.apiorchestrator.util.MarketTimeUtil;
import org.invest.apiorchestrator.websocket.WebSocketSubscriptionManager;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class ApplicationStartupRunner implements ApplicationRunner {

    private final TokenService tokenService;
    private final WebSocketSubscriptionManager subscriptionManager;

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

        // 거래 시간 중 앱 재시작 시 즉시 WebSocket 연결
        if (MarketTimeUtil.isPreMarket()) {
            log.info("장전 시간 - 예상체결/호가 구독 시작");
            try { subscriptionManager.setupPreMarketSubscription(); }
            catch (Exception e) { log.error("장전 구독 실패: {}", e.getMessage()); }
        } else if (MarketTimeUtil.isMarketHours()) {
            log.info("정규장 시간 - 실시간 시세 구독 시작");
            try { subscriptionManager.setupMarketHoursSubscription(); }
            catch (Exception e) { log.error("정규장 구독 실패: {}", e.getMessage()); }
        } else {
            log.info("거래 시간 외 - WebSocket 대기 상태");
        }

        log.info("=== 시스템 초기화 완료 ===");
    }
}
