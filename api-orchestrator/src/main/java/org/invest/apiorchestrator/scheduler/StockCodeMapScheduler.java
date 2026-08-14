package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.KiwoomStockService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * StockCodeMapScheduler – 매주 월요일 07:00 전종목(KOSPI+KOSDAQ) 코드:종목명 매핑 갱신.
 *
 * ai-engine candidates_builder.py 의 _filter_individual_stocks() 가 Redis stock:code_map
 * 해시에서 종목명을 조회해 ETF/ETN/레버리지/인버스/우선주 등을 후보 풀에서 제외한다.
 * 이 스케줄러가 없으면 stock:code_map 이 비어 있어 해당 필터가 항상 통과(fail-open)된다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StockCodeMapScheduler {

    private final KiwoomStockService kiwoomStockService;

    @Scheduled(cron = "0 0 7 * * MON", zone = "Asia/Seoul")
    public void refreshStockCodeMap() {
        log.info("=== stock:code_map 갱신 시작 (전종목 코드:종목명 동기화) ===");
        try {
            kiwoomStockService.syncAllStockCodes();
            log.info("[StockCodeMap] 갱신 완료");
        } catch (Exception e) {
            log.error("[StockCodeMap] 갱신 실패: {}", e.getMessage());
        }
    }
}
