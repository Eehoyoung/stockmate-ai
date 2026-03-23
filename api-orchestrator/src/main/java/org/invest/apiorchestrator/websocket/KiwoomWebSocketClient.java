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
            // 키움 WS 프로토콜: item 과 type 은 배열로 전송해야 함
            List<Map<String, Object>> dataList = items.stream()
                    .map(item -> Map.<String, Object>of(
                            "item", List.of(item),
                            "type", List.of(type)))
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
                    // 키움 실시간 데이터는 trnm="REAL" 로 수신되며 data 배열 안에 type 으로 구분됨
                    case "REAL"  -> handleRealData(root);
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
     * 키움 실시간 데이터 공통 진입점.
     * trnm="REAL", data=[{type, item, values:{숫자키:값}}] 형식
     */
    private void handleRealData(JsonNode root) {
        JsonNode dataArray = root.path("data");
        if (!dataArray.isArray()) return;
        for (JsonNode item : dataArray) {
            String type = item.path("type").asText("");
            switch (type) {
                case "0B" -> handleStockTick(item);
                case "0D" -> handleHoga(item);
                case "0H" -> handleExpected(item);
                case "1h" -> handleVi(item);
                default   -> log.trace("[WS] 미처리 실시간 타입: {}", type);
            }
        }
    }

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

    /**
     * 0B 주식체결 – values 숫자키 파싱
     * 10:현재가, 11:전일대비, 12:등락율, 13:누적거래량, 14:누적거래대금, 20:체결시간, 228:체결강도
     */
    private void handleStockTick(JsonNode item) {
        try {
            String stkCd = item.path("item").asText("");
            if (stkCd.isEmpty()) return;
            JsonNode v = item.path("values");
            if (v.isMissingNode()) return;

            WsMarketData.StockTick tick = new WsMarketData.StockTick();
            tick.setStkCd(stkCd);
            tick.setCurPrc(v.path("10").asText(""));
            tick.setPredPre(v.path("11").asText(""));
            tick.setFluRt(v.path("12").asText(""));
            tick.setAccTrdeQty(v.path("13").asText(""));
            tick.setAccTrdePrica(v.path("14").asText(""));
            tick.setCntrTm(v.path("20").asText(""));
            tick.setCntrStr(v.path("228").asText(""));
            redisService.saveStockTick(tick);
        } catch (Exception e) {
            log.warn("[WS] StockTick 파싱 오류: {}", e.getMessage());
        }
    }

    /**
     * 0D 호가잔량 – values 숫자키 파싱
     * 21:호가시간, 41:매도1호가, 51:매수1호가, 61:매도1수량, 71:매수1수량, 121:매도총잔량, 125:매수총잔량
     */
    private void handleHoga(JsonNode item) {
        try {
            String stkCd = item.path("item").asText("");
            if (stkCd.isEmpty()) return;
            JsonNode v = item.path("values");
            if (v.isMissingNode()) return;

            WsMarketData.StockHoga hoga = new WsMarketData.StockHoga();
            hoga.setStkCd(stkCd);
            hoga.setBidReqBaseTm(v.path("21").asText(""));
            hoga.setSelBidPric1(v.path("41").asText(""));
            hoga.setBuyBidPric1(v.path("51").asText(""));
            hoga.setSelBidReq1(v.path("61").asText(""));
            hoga.setBuyBidReq1(v.path("71").asText(""));
            hoga.setTotalSelBidReq(v.path("121").asText(""));
            hoga.setTotalBuyBidReq(v.path("125").asText(""));
            redisService.saveHoga(hoga);
        } catch (Exception e) {
            log.warn("[WS] Hoga 파싱 오류: {}", e.getMessage());
        }
    }

    /**
     * 0H 예상체결 – values 숫자키 파싱
     * 10:예상체결가, 12:예상등락율, 15:예상체결수량, 20:예상체결시간
     */
    private void handleExpected(JsonNode item) {
        try {
            String stkCd = item.path("item").asText("");
            if (stkCd.isEmpty()) return;
            JsonNode v = item.path("values");
            if (v.isMissingNode()) return;

            WsMarketData.ExpectedExecution exp = new WsMarketData.ExpectedExecution();
            exp.setStkCd(stkCd);
            exp.setExpCntrPric(v.path("10").asText(""));
            exp.setExpFluRt(v.path("12").asText(""));
            exp.setExpCntrQty(v.path("15").asText(""));
            exp.setExpCntrTm(v.path("20").asText(""));
            redisService.saveExpectedExecution(exp);
        } catch (Exception e) {
            log.warn("[WS] Expected 파싱 오류: {}", e.getMessage());
        }
    }

    /**
     * 1h VI발동/해제 – values 숫자키 파싱
     * 9001:종목코드, 9068:VI발동구분(1발동/2해제), 1225:VI적용구분(정적/동적/동적+정적),
     * 1221:VI발동가격, 9008:시장구분
     */
    private void handleVi(JsonNode item) {
        try {
            JsonNode v = item.path("values");
            if (v.isMissingNode()) return;

            // values.9001 우선, fallback: item 필드
            String stkCd = v.path("9001").asText(item.path("item").asText(""));
            if (stkCd.isEmpty()) return;

            WsMarketData.ViActivation vi = new WsMarketData.ViActivation();
            vi.setStkCd(stkCd);
            vi.setStkNm(v.path("302").asText(""));
            vi.setViStat(v.path("9068").asText(""));   // "1"=발동, "2"=해제
            vi.setViType(v.path("1225").asText(""));   // "정적"/"동적"/"동적+정적"
            vi.setViPric(v.path("1221").asText(""));
            vi.setMrktCls(v.path("9008").asText(""));
            viWatchService.handleViEvent(vi);
        } catch (Exception e) {
            log.warn("[WS] VI 파싱 오류: {}", e.getMessage());
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
