package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.CandidateService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.websocket.WebSocketSubscriptionManager;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Feature 5 – 데이터 품질 모니터링 스케쥴러.
 *
 * - WebSocket tick 데이터 침묵 감지 → 자동 재연결
 * - 텔레그램 큐 적체 감지 → 경고 알림
 * - error_queue 누적 감지 → 경고 알림
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DataQualityScheduler {

    private static final int  WS_MISSING_RATIO_THRESHOLD = 30;   // 후보 종목 30% 이상 누락 시 재연결
    private static final int  QUEUE_DEPTH_WARN            = 50;   // 텔레그램 큐 적체 임계값
    private static final int  ERROR_QUEUE_WARN            = 5;    // error_queue 경고 임계값
    private static final long WS_ALERT_COOLDOWN_MS        = 10 * 60 * 1000L; // WS 경고 최소 간격 10분
    private static final String KEY_WS_RECONNECT_COUNT    = "monitor:ws_reconnect_count";

    /** WS 경고 마지막 발행 시각 – 연속 스팸 방지 */
    private final AtomicLong lastWsAlertMs = new AtomicLong(0);

    private final CandidateService candidateService;
    private final RedisMarketDataService redisService;
    private final WebSocketSubscriptionManager subscriptionManager;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    /**
     * 2분 후 시작, 1분마다 실행 (Feature 5)
     */
    @Scheduled(fixedDelay = 60_000, initialDelay = 120_000)
    public void checkDataQuality() {
        List<String> alerts = new ArrayList<>();

        // 1. WebSocket tick 데이터 누락 체크
        try {
            checkWebSocketHealth(alerts);
        } catch (Exception e) {
            log.debug("[DataQuality] WS 헬스 체크 오류 (무시): {}", e.getMessage());
        }

        // 2. 텔레그램 큐 적체 체크
        try {
            long qDepth = redisService.getTelegramQueueDepth();
            if (qDepth > QUEUE_DEPTH_WARN) {
                alerts.add(String.format("⚠️ telegram_queue 적체: %d건", qDepth));
                log.warn("[DataQuality] telegram_queue 적체 {}건", qDepth);
            }
        } catch (Exception e) {
            log.debug("[DataQuality] 큐 깊이 체크 오류: {}", e.getMessage());
        }

        // 3. error_queue 누적 체크
        try {
            long errCount = redisService.getErrorQueueDepth();
            if (errCount > ERROR_QUEUE_WARN) {
                alerts.add(String.format("🔴 AI 엔진 에러 큐: %d건 누적", errCount));
                log.warn("[DataQuality] error_queue 누적 {}건", errCount);
            }
        } catch (Exception e) {
            log.debug("[DataQuality] error_queue 체크 오류: {}", e.getMessage());
        }

        // 4. SYSTEM_ALERT 발행
        if (!alerts.isEmpty()) {
            publishSystemAlert(alerts);
        }
    }

    private void checkWebSocketHealth(List<String> alerts) {
        // WS 자체가 끊긴 상태면 tick 데이터 없는 게 당연 – 알림 스팸 방지
        if (!redisService.isWsConnected()) {
            log.debug("[DataQuality] WS 미연결 상태 – tick 체크 스킵");
            return;
        }

        List<String> candidates = candidateService.getAllCandidates();
        if (candidates.isEmpty()) return;

        long missing = candidates.stream()
                .filter(c -> redisService.getTickData(c).isEmpty())
                .count();

        double missingRatio = (double) missing / candidates.size() * 100.0;

        if (missingRatio >= WS_MISSING_RATIO_THRESHOLD) {
            log.warn("[DataQuality] tick 데이터 누락 {}/{} ({}%) → WS 재연결 시도",
                    missing, candidates.size(), String.format("%.1f", missingRatio));

            // 거래 시간 외에는 재연결 시도 안 함
            if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
                log.info("[DataQuality] 거래 시간 외 → WS 재연결 건너뜀");
                return;
            }

            // 재연결
            subscriptionManager.setupMarketHoursSubscription();

            // 재연결 횟수 카운트
            Long reconnectCount = redis.opsForValue().increment(KEY_WS_RECONNECT_COUNT);
            if (reconnectCount != null && reconnectCount == 1) {
                redis.expire(KEY_WS_RECONNECT_COUNT, Duration.ofHours(24));
            }

            // 쿨다운 내 중복 경고 발행 방지 (10분)
            long now = System.currentTimeMillis();
            if (now - lastWsAlertMs.get() < WS_ALERT_COOLDOWN_MS) {
                log.debug("[DataQuality] WS 경고 쿨다운 중 – SYSTEM_ALERT 생략");
                return;
            }
            lastWsAlertMs.set(now);

            alerts.add(String.format("📡 WebSocket 데이터 이상 (누락 %.0f%%) – 재연결 완료", missingRatio));
        }
    }

    private void publishSystemAlert(List<String> alertMessages) {
        try {
            String joined = String.join("\n", alertMessages);
            String msg = objectMapper.writeValueAsString(Map.of(
                    "type",    "SYSTEM_ALERT",
                    "alerts",  alertMessages,
                    "message", "🔧 <b>[시스템 경고]</b>\n" + joined
            ));
            redisService.pushScoredQueue(msg);
            log.info("[DataQuality] SYSTEM_ALERT 발행: {}건 경고", alertMessages.size());
        } catch (Exception e) {
            log.warn("[DataQuality] SYSTEM_ALERT 발행 실패: {}", e.getMessage());
        }
    }
}
