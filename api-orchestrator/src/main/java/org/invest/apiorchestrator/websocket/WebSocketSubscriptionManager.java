package org.invest.apiorchestrator.websocket;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.CandidateService;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * WebSocket 구독 종목/타입 관리
 * - 그룹번호별 구독 타입 분리
 *   GRP 1: 주식체결(0B) - 전체 후보
 *   GRP 2: 호가잔량(0D) - 상위 50
 *   GRP 3: 예상체결(0H) - 장전용
 *   GRP 4: VI발동해제(1h) - 전체
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WebSocketSubscriptionManager {

    private final KiwoomWebSocketClient wsClient;
    private final CandidateService candidateService;

    private static final String GRP_TICK     = "1";
    private static final String GRP_HOGA     = "2";
    private static final String GRP_EXPECTED = "3";
    private static final String GRP_VI       = "4";

    private static final String TYPE_TICK     = "0B";
    private static final String TYPE_HOGA     = "0D";
    private static final String TYPE_EXPECTED = "0H";
    private static final String TYPE_VI       = "1h";

    /**
     * 장전 구독 설정 (07:30~09:00)
     * - 예상체결(0H), 호가잔량(0D) 위주
     */
    public void setupPreMarketSubscription() {
        if (!wsClient.isConnected()) {
            wsClient.connect();
            sleepMs(2000);
        }
        List<String> candidates = candidateService.getAllCandidates();
        if (candidates.isEmpty()) {
            log.warn("장전 구독: 후보 종목 없음");
            return;
        }

        List<String> top100 = candidates.subList(0, Math.min(100, candidates.size()));
        List<String> top50  = candidates.subList(0, Math.min(50, candidates.size()));

        // 배치 구독 (최대 100개 단위)
        subscribeInBatches(GRP_EXPECTED, top100, TYPE_EXPECTED);
        subscribeInBatches(GRP_HOGA,    top50,  TYPE_HOGA);

        // VI는 종목코드 없이 전체 구독
        wsClient.subscribe(GRP_VI, List.of(""), TYPE_VI);

        log.info("장전 구독 완료: 예상체결={}개, 호가={}개", top100.size(), top50.size());
    }

    /**
     * 정규장 구독 설정 (09:00~15:20)
     * - 체결(0B), 호가(0D), VI(1h)
     */
    public void setupMarketHoursSubscription() {
        if (!wsClient.isConnected()) {
            wsClient.connect();
            sleepMs(2000);
        }
        List<String> candidates = candidateService.getAllCandidates();
        if (candidates.isEmpty()) {
            log.warn("정규장 구독: 후보 종목 없음");
            return;
        }

        List<String> top200 = candidates.subList(0, Math.min(200, candidates.size()));
        List<String> top100 = candidates.subList(0, Math.min(100, candidates.size()));

        subscribeInBatches(GRP_TICK, top200, TYPE_TICK);
        subscribeInBatches(GRP_HOGA, top100, TYPE_HOGA);
        wsClient.subscribe(GRP_VI, List.of(""), TYPE_VI);

        // 예상체결 구독 해제 (장중에는 불필요)
        wsClient.unsubscribe(GRP_EXPECTED, TYPE_EXPECTED);

        log.info("정규장 구독 완료: 체결={}개, 호가={}개", top200.size(), top100.size());
    }

    /**
     * 장 종료 후 구독 해제
     */
    public void teardownSubscriptions() {
        wsClient.unsubscribe(GRP_TICK,     TYPE_TICK);
        wsClient.unsubscribe(GRP_HOGA,     TYPE_HOGA);
        wsClient.unsubscribe(GRP_EXPECTED, TYPE_EXPECTED);
        wsClient.unsubscribe(GRP_VI,       TYPE_VI);
        log.info("전체 구독 해제 완료");
    }

    /**
     * 후보 종목 갱신 (스케줄러에서 주기적 호출)
     */
    public void refreshCandidateSubscription() {
        List<String> newCandidates = candidateService.getAllCandidates();
        if (newCandidates.isEmpty()) return;

        List<String> top200 = newCandidates.subList(0, Math.min(200, newCandidates.size()));
        subscribeInBatches(GRP_TICK, top200, TYPE_TICK);

        List<String> top100 = newCandidates.subList(0, Math.min(100, newCandidates.size()));
        subscribeInBatches(GRP_HOGA, top100, TYPE_HOGA);
    }

    private void subscribeInBatches(String grpNo, List<String> items, String type) {
        int batchSize = 100;
        for (int i = 0; i < items.size(); i += batchSize) {
            List<String> batch = new ArrayList<>(
                    items.subList(i, Math.min(i + batchSize, items.size())));
            wsClient.subscribe(grpNo, batch, type);
            sleepMs(300); // 빠른 연속 요청 방지
        }
    }

    private void sleepMs(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }
}
