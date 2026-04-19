package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.repository.WsTickDataRepository;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataCleanupScheduler {

    private final WsTickDataRepository tickDataRepository;

    /**
     * 매일 23:30 - 3일 이상 된 틱 데이터 삭제
     */
    @Scheduled(cron = "0 30 23 * * *", zone = "Asia/Seoul")
    @Transactional
    public void cleanupOldTickData() {
        LocalDateTime cutoff = KstClock.now().minusDays(3);
        try {
            int deleted = tickDataRepository.deleteOldTickData(cutoff);
            log.info("틱 데이터 정리 완료: {}건 삭제 (3일 이전)", deleted);
        } catch (Exception e) {
            log.error("틱 데이터 정리 실패: {}", e.getMessage());
        }
    }
}
