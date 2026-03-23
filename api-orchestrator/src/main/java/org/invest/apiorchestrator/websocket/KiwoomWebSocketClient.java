package org.invest.apiorchestrator.websocket;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.dto.res.WsMarketData;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.service.TokenService;
import org.invest.apiorchestrator.service.ViWatchService;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

@Slf4j
@Component
public class KiwoomWebSocketClient {

    private final TokenService tokenService;
    private final KiwoomProperties properties;
    private final ObjectMapper objectMapper;
    private final RedisMarketDataService redisService;
    private final ViWatchService viWatchService;

    private okhttp3.WebSocket webSocket;
    private final AtomicBoolean connected = new AtomicBoolean(false);
    private final AtomicInteger reconnectCount = new AtomicInteger(0);
    /** 현재 실행 중인 ping 스케줄 – 재연결 시 이전 것을 취소하기 위해 추적 */
    private volatile ScheduledFuture<?> pingFuture;
    private final ScheduledExecutorService pingExecutor =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "ws-ping");
                t.setDaemon(true);
                return t;
            });

    /** disconnect() 호출 시 true – onClosing 에서 재연결 방지 */
    private volatile boolean voluntaryClose = false;

    private final OkHttpClient httpClient = new OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)   // WebSocket: 무제한 읽기
            .build();

    private static final String WS_PATH = "/api/dostk/websocket";

    public KiwoomWebSocketClient(TokenService tokenService, KiwoomProperties properties, ObjectMapper objectMapper, RedisMarketDataService redisService, ViWatchService viWatchService) {
        this.tokenService = tokenService;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.redisService = redisService;
        this.viWatchService = viWatchService;
    }

    /**
     * WebSocket 연결 시작
     */
    public void connect() {
        if (connected.get()) {
            log.debug("WebSocket 이미 연결됨");
            return;
        }
        String wsUrl = properties.getApi().getWsUrl() + WS_PATH;
        String token = tokenService.getBearerToken();

        Request request = new Request.Builder()
                .url(wsUrl)
                .header("authorization", token)
                .build();

        webSocket = httpClient.newWebSocket(request, new KiwoomWsListener());
        log.info("WebSocket 연결 시도: {}", wsUrl);
    }

    /**
     * WebSocket 연결 종료 (정상 종료 – 재연결 없음)
     */
    public void disconnect() {
        voluntaryClose = true;
        if (webSocket != null) {
            webSocket.close(1000, "정상 종료");
        }
        connected.set(false);
        log.info("WebSocket 연결 종료");
    }

    /**
     * 실시간 데이터 구독 등록
     *
     * @param grpNo 그룹번호 (1~9999)
     * @param items 종목코드 목록
     * @param type  TR 타입 (0B, 0D, 0H, 1h 등)
     */
    public void subscribe(String grpNo, List<String> items, String type) {
        if (!connected.get()) {
            log.warn("WebSocket 미연결 상태 - 구독 불가");
            return;
        }
        try {
            List<Map<String, String>> dataList = items.stream()
                    .map(item -> Map.of("item", item, "type", type))
                    .toList();
            Map<String, Object> req = Map.of(
                    "trnm",    "REG",
                    "grp_no",  grpNo,
                    "refresh", "1",
                    "data",    dataList
            );
            String json = objectMapper.writeValueAsString(req);
            webSocket.send(json);
            log.info("WebSocket 구독 등록 grp={} type={} items={}개", grpNo, type, items.size());
        } catch (Exception e) {
            log.error("구독 등록 실패: {}", e.getMessage());
        }
    }

    /**
     * 구독 해제
     */
    public void unsubscribe(String grpNo, String type) {
        if (!connected.get()) return;
        try {
            Map<String, Object> req = Map.of(
                    "trnm",   "REMOVE",
                    "grp_no", grpNo,
                    "data",   List.of(Map.of("type", type))
            );
            webSocket.send(objectMapper.writeValueAsString(req));
        } catch (Exception e) {
            log.error("구독 해제 실패: {}", e.getMessage());
        }
    }

    public boolean isConnected() { return connected.get(); }

    // ───── WebSocket Listener ─────

    private class KiwoomWsListener extends WebSocketListener {

        @Override
        public void onOpen(WebSocket ws, Response response) {
            reconnectCount.set(0);
            voluntaryClose = false;
            log.info("WebSocket 연결 성공 – LOGIN 패킷 전송 중");
            // connected 는 LOGIN 응답(return_code=0) 수신 후 설정됨

            // ── LOGIN 패킷 전송 (키움 WS 프로토콜 필수) ──────────────
            // HTTP 헤더 인증과 별개로 반드시 LOGIN 패킷을 먼저 전송해야
            // 실시간 데이터 구독(REG)이 가능함. 미전송 시 서버가 ~10초 후
            // code=1000 "Bye" 로 연결 종료.
            try {
                String loginJson = objectMapper.writeValueAsString(
                        Map.of("trnm", "LOGIN", "token", tokenService.getValidToken()));
                ws.send(loginJson);
                log.info("LOGIN 패킷 전송 완료");
            } catch (Exception e) {
                log.error("LOGIN 패킷 전송 실패: {}", e.getMessage());
                ws.close(1011, "LOGIN 전송 오류");
            }
        }

        @Override
        public void onMessage(WebSocket ws, String text) {
            try {
                JsonNode root = objectMapper.readTree(text);
                String trnm = root.path("trnm").asText("");

                switch (trnm) {
                    case "LOGIN" -> handleLogin(ws, root);
                    case "PING"  -> ws.send("{\"trnm\":\"PONG\"}");
                    case "0B"    -> handleStockTick(root);
                    case "0D"    -> handleHoga(root);
                    case "0H"    -> handleExpected(root);
                    case "1h"    -> handleVi(root);
                    default      -> log.trace("WS 메시지 [{}]: {}", trnm, text.length() > 200 ? text.substring(0,200) : text);
                }
            } catch (Exception e) {
                log.error("WS 메시지 파싱 오류: {} / msg={}", e.getMessage(),
                        text.length() > 100 ? text.substring(0,100) : text);
            }
        }

        @Override
        public void onClosing(WebSocket ws, int code, String reason) {
            connected.set(false);
            redisService.setWsConnected(false);
            log.info("WebSocket 연결 종료 code={} reason={}", code, reason);
            // 서버 측 종료(비자발적) 이고 거래 시간 중이면 재연결
            if (!voluntaryClose && org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
                log.info("WebSocket 서버 측 종료 감지 – 재연결 예약");
                scheduleReconnect();
            } else if (!voluntaryClose) {
                log.info("WebSocket 종료 감지 (거래 시간 외) – 재연결 보류");
            }
        }

        @Override
        public void onFailure(WebSocket ws, Throwable t, Response response) {
            connected.set(false);
            redisService.setWsConnected(false);
            log.error("WebSocket 오류: {}", t.getMessage());
            if (org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
                scheduleReconnect();
            } else {
                log.info("WebSocket 오류 (거래 시간 외) – 재연결 보류");
            }
        }
    }

    // ───── 메시지 핸들러 ─────

    /**
     * LOGIN 응답 처리.
     * return_code == "0" 일 때 connected = true 로 전환하고 ping 스케줄 시작.
     * 실패 시 ws 종료 → onClosing → scheduleReconnect 흐름으로 재연결.
     */
    private void handleLogin(WebSocket ws, JsonNode root) {
        // return_code 필드명 snake_case / camelCase 모두 대응
        String returnCode = root.path("return_code").asText(
                root.path("returnCode").asText("-1"));

        if (!"0".equals(returnCode)) {
            log.error("WebSocket LOGIN 실패 – return_code={} msg={}",
                    returnCode, root.path("return_msg").asText(""));
            ws.close(1008, "LOGIN 실패");
            return;
        }

        log.info("WebSocket LOGIN 성공 – connected = true");
        connected.set(true);
        redisService.setWsConnected(true);

        // 이전 ping 스케줄 취소 후 새 스케줄 등록
        if (pingFuture != null && !pingFuture.isCancelled()) {
            pingFuture.cancel(false);
        }
        int pingInterval = properties.getWebsocket().getPingIntervalSeconds();
        pingFuture = pingExecutor.scheduleAtFixedRate(
                () -> {
                    if (connected.get()) {
                        ws.send("{\"trnm\":\"PING\"}");
                        redisService.refreshWsHeartbeat();
                    }
                },
                pingInterval, pingInterval, TimeUnit.SECONDS);
    }

    private void handleStockTick(JsonNode root) {
        try {
            JsonNode data = root.path("data");
            if (data.isMissingNode()) return;
            WsMarketData.StockTick tick = objectMapper.treeToValue(data, WsMarketData.StockTick.class);
            tick.setStkCd(root.path("item").asText(tick.getStkCd()));
            redisService.saveStockTick(tick);
        } catch (Exception e) {
            log.debug("StockTick 파싱 오류: {}", e.getMessage());
        }
    }

    private void handleHoga(JsonNode root) {
        try {
            JsonNode data = root.path("data");
            if (data.isMissingNode()) return;
            WsMarketData.StockHoga hoga = objectMapper.treeToValue(data, WsMarketData.StockHoga.class);
            hoga.setStkCd(root.path("item").asText(hoga.getStkCd()));
            redisService.saveHoga(hoga);
        } catch (Exception e) {
            log.debug("Hoga 파싱 오류: {}", e.getMessage());
        }
    }

    private void handleExpected(JsonNode root) {
        try {
            JsonNode data = root.path("data");
            if (data.isMissingNode()) return;
            WsMarketData.ExpectedExecution exp =
                    objectMapper.treeToValue(data, WsMarketData.ExpectedExecution.class);
            exp.setStkCd(root.path("item").asText(exp.getStkCd()));
            redisService.saveExpectedExecution(exp);
        } catch (Exception e) {
            log.debug("Expected 파싱 오류: {}", e.getMessage());
        }
    }

    private void handleVi(JsonNode root) {
        try {
            JsonNode data = root.path("data");
            if (data.isMissingNode()) return;
            WsMarketData.ViActivation vi =
                    objectMapper.treeToValue(data, WsMarketData.ViActivation.class);
            vi.setStkCd(root.path("item").asText(vi.getStkCd()));
            viWatchService.handleViEvent(vi);
        } catch (Exception e) {
            log.debug("VI 파싱 오류: {}", e.getMessage());
        }
    }

    // ───── 재연결 ─────

    private void scheduleReconnect() {
        int maxAttempts = properties.getWebsocket().getMaxReconnectAttempts();
        int attempt = reconnectCount.incrementAndGet();
        if (attempt > maxAttempts) {
            log.error("WebSocket 최대 재연결 횟수({}) 초과 - 포기", maxAttempts);
            return;
        }
        long delayMs = properties.getWebsocket().getReconnectDelayMs() * attempt;
        log.info("WebSocket 재연결 예정 - {}ms 후 ({}번째)", delayMs, attempt);
        pingExecutor.schedule(this::connect, delayMs, TimeUnit.MILLISECONDS);
    }
}
