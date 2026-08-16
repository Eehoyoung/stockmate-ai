package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.TossInvestProperties;
import org.invest.apiorchestrator.service.TossAuthService;
import org.invest.apiorchestrator.service.TossMarketCalendarService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 토스 토큰(만료 24h)을 장 시작 전 미리 발급/갱신해 첫 폴링 시 지연이 없도록 한다.
 * TossMarketIndicatorService 가 어차피 지연 발급(getValidToken)을 지원하므로 이 스케줄러가
 * 실패해도 트레이딩에는 영향이 없다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TossTokenRefreshScheduler {

    private final TossAuthService tossAuthService;
    private final TossInvestProperties tossProperties;
    private final TossMarketCalendarService marketCalendarService;

    @Scheduled(cron = "0 0 7 * * MON-FRI", zone = "Asia/Seoul")
    public void refreshMorning() {
        if (!tossProperties.isEnabled()) {
            return;
        }
        try {
            var tradingDay = marketCalendarService.ensureTradingDay(KstClock.today(), true);
            if (tradingDay.isEmpty() || !tradingDay.get()) {
                log.info("[Toss] 07:00 token refresh skipped - market status={}",
                        tradingDay.isPresent() ? "CLOSED" : "UNKNOWN");
                return;
            }
            tossAuthService.getValidToken();
            log.info("[Toss] 07:00 토큰 갱신 완료");
        } catch (Exception e) {
            log.warn("[Toss] 07:00 토큰 갱신 실패 (지연 발급으로 폴백): {}", e.getMessage());
        }
    }
}
