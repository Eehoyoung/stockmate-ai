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
    private final org.invest.apiorchestrator.config.KiwoomProperties kiwoomProperties;

    // Redis 키 접두사
    private static final String KEY_TICK      = "ws:tick:";
    private static final String KEY_EXPECTED  = "ws:expected:";
    private static final String KEY_HOGA      = "ws:hoga:";
    private static final String KEY_STRENGTH  = "ws:strength:";
    private static final String KEY_VI        = "vi:";

    private static final Duration TICK_TTL      = Duration.ofSeconds(30);
    private static final Duration EXPECTED_TTL  = Duration.ofSeconds(60);
    private static final Duration HOGA_TTL      = Duration.ofSeconds(10);
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
     * 신호 중복 여부 체크 (set → 전략별 TTL).
     * 전략별 TTL: S1(갭상승)=1800s, S2(VI눌림목)=3600s, S7(동시호가)=7200s, 그외=기본값
     * 기본값은 kiwoom.trading.signal-ttl-seconds (application.yml / SIGNAL_DUPLICATE_TTL 환경변수)
     */
    public boolean isSignalDuplicate(String stkCd, String strategy) {
        String key = "signal:" + stkCd + ":" + strategy;
        long ttlSeconds = getSignalTtl(strategy);
        Boolean absent = redis.opsForValue().setIfAbsent(key, "1", Duration.ofSeconds(ttlSeconds));
        return Boolean.FALSE.equals(absent);  // false = 이미 존재 = 중복
    }

    /**
     * 전략별 신호 중복 방지 TTL 반환 (초)
     */
    private long getSignalTtl(String strategy) {
        if (strategy == null) return kiwoomProperties.getTrading().getSignalTtlSeconds();
        return switch (strategy) {
            case "S1_GAP_OPEN"    -> 1800L;   // 갭상승: 30분 (시초가 이후 의미 없음)
            case "S2_VI_PULLBACK" -> 3600L;   // VI 눌림목: 1시간
            case "S7_AUCTION"     -> 7200L;   // 동시호가: 2시간
            default               -> kiwoomProperties.getTrading().getSignalTtlSeconds();
        };
    }

    /**
     * VI 눌림목 감시 큐에 다시 넣기 (조건 미충족 → 재시도)
     */
    public void pushViWatchBack(String item) {
        redis.opsForList().rightPush("vi_watch_queue", item);
    }

    /**
     * 텔레그램 알림 큐에 푸시
     */
    public void pushTelegramQueue(String message) {
        redis.opsForList().leftPush("telegram_queue", message);
        redis.expire("telegram_queue", Duration.ofHours(12));
    }

    private String nvl(String v) { return v != null ? v : ""; }
    private String nvl(Object v) { return v != null ? v.toString() : ""; }
}
