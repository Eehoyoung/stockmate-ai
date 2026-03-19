package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.SignalService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class ForceCloseScheduler {

    private final SignalService signalService;
    private final RedisMarketDataService redisService;
    private final ObjectMapper objectMapper;

    /**
     * 14:50 - 장마감 30분 전 미청산 포지션 강제 청산 알림
     * (실제 주문은 Python 또는 별도 OrderService에서 처리)
     */
    @Scheduled(cron = "0 50 14 * * MON-FRI")
    public void notifyForceClose() {
        log.info("=== 강제 청산 알림 시작 (14:50) ===");
        try {
            // SENT/EXECUTED 상태 신호 조회
            List<TradingSignal> activeSignals =
                    signalService.getTodaySignals().stream()
                            .filter(s -> s.getSignalStatus() == TradingSignal.SignalStatus.SENT
                                    || s.getSignalStatus() == TradingSignal.SignalStatus.EXECUTED)
                            .toList();

            if (activeSignals.isEmpty()) {
                log.info("강제 청산 대상 없음");
                return;
            }

            log.warn("강제 청산 대상: {}건", activeSignals.size());

            for (TradingSignal signal : activeSignals) {
                try {
                    String msg = objectMapper.writeValueAsString(Map.of(
                            "type",    "FORCE_CLOSE",
                            "stk_cd",  signal.getStkCd(),
                            "stk_nm",  signal.getStkNm() != null ? signal.getStkNm() : "",
                            "strategy",signal.getStrategy().name(),
                            "message", String.format(
                                    "⚠️ 강제 청산 [%s] %s %s\n장마감 30분 전 전량 시장가 청산",
                                    signal.getStrategy().name(),
                                    signal.getStkCd(),
                                    signal.getStkNm() != null ? signal.getStkNm() : "")
                    ));
                    redisService.pushTelegramQueue(msg);
                } catch (Exception e) {
                    log.error("강제 청산 알림 실패 [{}]: {}", signal.getStkCd(), e.getMessage());
                }
            }
        } catch (Exception e) {
            log.error("강제 청산 스케줄 오류: {}", e.getMessage());
        }
    }
}
