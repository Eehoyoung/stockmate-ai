package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.TokenService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class TokenRefreshScheduler {

    private final TokenService tokenService;

    /**
     * 매일 06:50, 07:20, 토큰 갱신
     * 키움 토큰 유효시간은 약 24시간이나 여유 있게 갱신
     */
    @Scheduled(cron = "0 50 6 * * MON-FRI", zone = "Asia/Seoul")
    public void refreshMorning() {
        refresh("06:50");
    }

    @Scheduled(cron = "0 20 7 * * MON-FRI", zone = "Asia/Seoul")
    public void refreshPreMarket() {
        refresh("07:20");
    }

    /** 장중 토큰 만료 대비 - 매 23시간마다 갱신 */
    @Scheduled(fixedDelay = 82_800_000L, initialDelay = 3_600_000L)
    public void refreshPeriodic() {
        refresh("주기적");
    }

    private void refresh(String when) {
        try {
            tokenService.refreshToken();
            log.info("[{}] 토큰 갱신 완료", when);
        } catch (Exception e) {
            log.error("[{}] 토큰 갱신 실패: {}", when, e.getMessage());
        }
    }
}
