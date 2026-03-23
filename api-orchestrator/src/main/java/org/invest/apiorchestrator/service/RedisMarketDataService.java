package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.res.WsMarketData;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class RedisMarketDataService {

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    // Redis 키 접두사
    private static final String KEY_TICK      = "ws:tick:";
    private static final String KEY_EXPECTED  = "ws:expected:";
    private static final String KEY_HOGA      = "ws:hoga:";
    private static final String KEY_STRENGTH  = "ws:strength:";
    private static final String KEY_VI        = "vi:";

    private static final Duration TICK_TTL      = Duration.ofSeconds(30);
    private static final Duration EXPECTED_TTL  = Duration.ofSeconds(60);
    private static final Duration HOGA_TTL      = Duration.ofSeconds(30);
    private static final Duration STRENGTH_TTL  = Duration.ofMinutes(5);
    private static final Duration VI_TTL        = Duration.ofHours(1);

    // ───── WRITE ─────

    public void saveStockTick(WsMarketData.StockTick tick) {
        if (tick.getStkCd() == null) return;
        String key = KEY_TICK + tick.getStkCd();
        try {
            Map<String, String> map = Map.of(
                    "cur_prc",       nvl(tick.getCurPrc()),
                    "pred_pre",      nvl(tick.getPredPre()),
                    "flu_rt",        nvl(tick.getFluRt()),
                    "acc_trde_qty",  nvl(tick.getAccTrdeQty()),
                    "acc_trde_prica",nvl(tick.getAccTrdePrica()),
                    "cntr_str",      nvl(tick.getCntrStr()),
                    "cntr_tm",       nvl(tick.getCntrTm())
            );
            redis.opsForHash().putAll(key, map);
            redis.expire(key, TICK_TTL);

            // 체결강도 리스트 최근 10개 유지
            if (tick.getCntrStr() != null) {
                String strKey = KEY_STRENGTH + tick.getStkCd();
                redis.opsForList().leftPush(strKey, tick.getCntrStr());
                redis.opsForList().trim(strKey, 0, 9);
                redis.expire(strKey, STRENGTH_TTL);
            }
        } catch (Exception e) {
            log.warn("Redis tick 저장 실패 [{}]: {}", tick.getStkCd(), e.getMessage());
        }
    }

    public void saveExpectedExecution(WsMarketData.ExpectedExecution exp) {
        if (exp.getStkCd() == null) return;
        String key = KEY_EXPECTED + exp.getStkCd();
        try {
            Map<String, String> map = Map.of(
                    "exp_cntr_pric",  nvl(exp.getExpCntrPric()),
                    "exp_pred_pre",   nvl(exp.getExpPredPre()),
                    "exp_flu_rt",     nvl(exp.getExpFluRt()),
                    "exp_cntr_qty",   nvl(exp.getExpCntrQty()),
                    "pred_pre_pric",  nvl(exp.getPredPrePric()),
                    "exp_cntr_tm",    nvl(exp.getExpCntrTm())
            );
            redis.opsForHash().putAll(key, map);
            redis.expire(key, EXPECTED_TTL);
        } catch (Exception e) {
            log.warn("Redis expected 저장 실패 [{}]: {}", exp.getStkCd(), e.getMessage());
        }
    }

    public void saveHoga(WsMarketData.StockHoga hoga) {
        if (hoga.getStkCd() == null) return;
        String key = KEY_HOGA + hoga.getStkCd();
        try {
            Map<String, String> map = Map.of(
                    "total_buy_bid_req", nvl(hoga.getTotalBuyBidReq()),
                    "total_sel_bid_req", nvl(hoga.getTotalSelBidReq()),
                    "buy_bid_pric_1",   nvl(hoga.getBuyBidPric1()),
                    "sel_bid_pric_1",   nvl(hoga.getSelBidPric1()),
                    "bid_req_base_tm",  nvl(hoga.getBidReqBaseTm())
            );
            redis.opsForHash().putAll(key, map);
            redis.expire(key, HOGA_TTL);
        } catch (Exception e) {
            log.warn("Redis hoga 저장 실패 [{}]: {}", hoga.getStkCd(), e.getMessage());
        }
    }

    public void saveViEvent(WsMarketData.ViActivation vi) {
        if (vi.getStkCd() == null) return;
        String key = KEY_VI + vi.getStkCd();
        try {
            Map<String, String> map = Map.of(
                    "vi_price",     nvl(vi.getViPric()),
                    "vi_type",      nvl(vi.getViType()),
                    "status",       vi.isActivation() ? "active" : "released",
                    "acc_volume",   nvl(vi.getAccTrdeQty()),
                    "vi_upper",     nvl(vi.getViUpper()),
                    "vi_lower",     nvl(vi.getViLower()),
                    "mrkt_cls",     nvl(vi.getMrktCls())
            );
            redis.opsForHash().putAll(key, map);
            redis.expire(key, VI_TTL);

            // VI 해제 시 눌림목 감시 큐 등록
            if (vi.isRelease()) {
                String watchItem = objectMapper.writeValueAsString(Map.of(
                        "stk_cd",       vi.getStkCd(),
                        "stk_nm",       nvl(vi.getStkNm()),
                        "vi_price",     vi.getViPricDouble(),
                        "watch_until",  System.currentTimeMillis() + 600_000L,
                        "is_dynamic",   vi.isDynamic()
                ));
                redis.opsForList().leftPush("vi_watch_queue", watchItem);
                redis.expire("vi_watch_queue", Duration.ofHours(2));
                log.info("VI 해제 → 눌림목 감시 등록 [{}] vi_price={}", vi.getStkCd(), vi.getViPricDouble());
            }
        } catch (Exception e) {
            log.warn("Redis VI 저장 실패 [{}]: {}", vi.getStkCd(), e.getMessage());
        }
    }

    // ───── READ ─────

    public Optional<Map<Object, Object>> getTickData(String stkCd) {
        Map<Object, Object> data = redis.opsForHash().entries(KEY_TICK + stkCd);
        return data.isEmpty() ? Optional.empty() : Optional.of(data);
    }

    public Optional<Map<Object, Object>> getExpectedData(String stkCd) {
        Map<Object, Object> data = redis.opsForHash().entries(KEY_EXPECTED + stkCd);
        return data.isEmpty() ? Optional.empty() : Optional.of(data);
    }

    public Optional<Map<Object, Object>> getHogaData(String stkCd) {
        Map<Object, Object> data = redis.opsForHash().entries(KEY_HOGA + stkCd);
        return data.isEmpty() ? Optional.empty() : Optional.of(data);
    }

    public Optional<Map<Object, Object>> getViData(String stkCd) {
        Map<Object, Object> data = redis.opsForHash().entries(KEY_VI + stkCd);
        return data.isEmpty() ? Optional.empty() : Optional.of(data);
    }

    /**
     * 체결강도 최근 N개 평균
     */
    public double getAvgCntrStrength(String stkCd, int count) {
        List<String> list = redis.opsForList().range(KEY_STRENGTH + stkCd, 0, count - 1);
        if (list == null || list.isEmpty()) return 100.0;
        return list.stream()
                .mapToDouble(s -> {
                    try { return Double.parseDouble(s.replace(",", "").replace("+", "")); }
                    catch (Exception e) { return 100.0; }
                })
                .average().orElse(100.0);
    }

    /**
     * VI 눌림목 감시 큐에서 아이템 꺼내기 (RPOP)
     */
    public Optional<String> pollViWatchQueue() {
        String item = redis.opsForList().rightPop("vi_watch_queue");
        return Optional.ofNullable(item);
    }

    /**
     * 신호 중복 여부 체크 (set → TTL 1시간)
     */
    public boolean isSignalDuplicate(String stkCd, String strategy) {
        String key = "signal:" + stkCd + ":" + strategy;
        Boolean absent = redis.opsForValue().setIfAbsent(key, "1", Duration.ofSeconds(3600));
        return Boolean.FALSE.equals(absent);  // false = 이미 존재 = 중복
    }

    /**
     * 종목 크로스-전략 쿨다운 (Feature 4).
     * @return true = 쿨다운 없음(진행 허용), false = 쿨다운 중(거부)
     */
    public boolean tryAcquireStockCooldown(String stkCd, int cooldownMinutes) {
        String key = "signal:stock:" + stkCd;
        Boolean absent = redis.opsForValue().setIfAbsent(key, "1", Duration.ofMinutes(cooldownMinutes));
        return Boolean.TRUE.equals(absent);  // true = 새로 설정됨 = 허용
    }

    /**
     * 일일 전체 신호 카운터 증가 (Feature 4).
     * @return 오늘 발행된 총 신호 수 (증가 후 값)
     */
    public long incrementDailySignalCount() {
        String key = "signal:daily_count:" + java.time.LocalDate.now();
        Long count = redis.opsForValue().increment(key);
        if (count != null && count == 1) {
            redis.expire(key, Duration.ofHours(25));
        }
        return count != null ? count : 1L;
    }

    /**
     * 섹터별 1시간 신호 카운터 증가 (Feature 4).
     */
    public long incrementSectorSignalCount(String sector) {
        String key = "signal:sector:" + sector;
        Long count = redis.opsForValue().increment(key);
        if (count != null && count == 1) {
            redis.expire(key, Duration.ofHours(1));
        }
        return count != null ? count : 1L;
    }

    /**
     * ai_scored_queue 에 직접 발행 (SECTOR_OVERHEAT, CALENDAR_ALERT, SYSTEM_ALERT 용)
     */
    public void pushScoredQueue(String message) {
        redis.opsForList().leftPush("ai_scored_queue", message);
        redis.expire("ai_scored_queue", Duration.ofHours(12));
    }

    /**
     * 오늘 일일 신호 카운터 조회
     */
    public long getDailySignalCount() {
        String key = "signal:daily_count:" + java.time.LocalDate.now();
        String val = redis.opsForValue().get(key);
        return val != null ? Long.parseLong(val) : 0L;
    }

    /**
     * telegram_queue 현재 길이 조회 (Feature 5 모니터링)
     */
    public long getTelegramQueueDepth() {
        Long len = redis.opsForList().size("telegram_queue");
        return len != null ? len : 0L;
    }

    /**
     * error_queue 현재 길이 조회 (Feature 5 모니터링)
     */
    public long getErrorQueueDepth() {
        Long len = redis.opsForList().size("error_queue");
        return len != null ? len : 0L;
    }

    /**
     * VI 눌림목 감시 큐에 다시 넣기 (조건 미충족 → 재시도)
     */
    public void pushViWatchBack(String item) {
        redis.opsForList().rightPush("vi_watch_queue", item);
    }

    /**
     * 오버나잇 Claude 평가 큐에 푸시 (ForceCloseScheduler → overnight_worker.py)
     */
    public void pushOvernightEvalQueue(String message) {
        redis.opsForList().leftPush("overnight_eval_queue", message);
        redis.expire("overnight_eval_queue", Duration.ofHours(2));
    }

    /**
     * 텔레그램 알림 큐에 푸시
     */
    public void pushTelegramQueue(String message) {
        redis.opsForList().leftPush("telegram_queue", message);
        redis.expire("telegram_queue", Duration.ofHours(12));
    }

    /**
     * Java WebSocket 연결 상태를 Redis 에 기록 (telegram-bot /상태 명령 표시용).
     * 연결 시: ws:connected="1" TTL 45s (ping 주기 30s 보다 짧게 – ping 없으면 자동 만료)
     * 끊김 시: ws:connected="0" TTL 10s, ws:stable 삭제
     */
    public void setWsConnected(boolean connected) {
        try {
            if (connected) {
                redis.opsForValue().set("ws:connected", "1", Duration.ofSeconds(45));
            } else {
                redis.opsForValue().set("ws:connected", "0", Duration.ofSeconds(10));
                redis.delete("ws:stable");   // 안정 연결 플래그 즉시 해제
            }
        } catch (Exception e) {
            log.debug("ws:connected 상태 저장 실패: {}", e.getMessage());
        }
    }

    /**
     * WS 가 실제로 안정적으로 연결 중인지 확인.
     * ws:stable 키는 ping 전송 성공 시(≥30초 유지)에만 설정되므로,
     * 잠깐 연결됐다 끊기는 brief reconnect 는 false 반환.
     */
    public boolean isWsConnected() {
        try {
            return "1".equals(redis.opsForValue().get("ws:stable"));
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * Java WebSocket heartbeat 갱신 – ping 전송 성공마다 호출 (30s 주기).
     * ws:heartbeat 와 ws:stable 을 함께 갱신하여 "안정 연결" 상태 표시.
     * ws:stable 이 존재하는 동안만 DataQualityScheduler 가 tick 체크를 수행함.
     */
    public void refreshWsHeartbeat() {
        try {
            redis.opsForValue().set("ws:connected", "1", Duration.ofSeconds(45));
            redis.opsForValue().set("ws:stable",    "1", Duration.ofSeconds(45));
            redis.opsForValue().set("ws:heartbeat", "1", Duration.ofSeconds(45));
        } catch (Exception e) {
            log.debug("ws:heartbeat 갱신 실패: {}", e.getMessage());
        }
    }

    private String nvl(String v) { return v != null ? v : ""; }
    private String nvl(Object v) { return v != null ? v.toString() : ""; }
}
