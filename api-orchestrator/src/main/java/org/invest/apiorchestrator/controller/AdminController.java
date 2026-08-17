package org.invest.apiorchestrator.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.service.OperationsHealthService;
import org.invest.apiorchestrator.service.SystemHealthSnapshotService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** 운영 대시보드(/dashboard) 전용 조회 API. 기존 /api/trading/** 를 대체하지 않고 그 위에 얹는 집계 엔드포인트. */
@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private static final DateTimeFormatter YYYYMMDD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /**
     * 대시보드에서 온오프 가능한 런타임 플래그.
     * bypass_market_hours       : websocket-listener 가 장 시간 외에도 Kiwoom WS 연결을 유지/재시도.
     * strategy_session_filter   : ai-engine 전략 스캐너가 장 세션(is_trading_active) 기준으로 스캔 자체를 건너뛸지 여부.
     * strategy_session_dry_run  : 세션 필터가 "닫힘"으로 판단해도 실제로는 건너뛰지 않고 로그만 남김(운영 검증용).
     * strategy_session_fail_open: 세션 판정 로직이 예외를 던지면 안전하게 열림(계속 스캔)으로 처리할지 여부. false 면 닫힘 처리.
     * session_enter_guard       : queue_worker 가 세션 상 진입 불가 시간대 신호의 ENTER 승격을 차단하는 가드 활성화 여부.
     * calendar_pre_event 는 EconomicCalendarScheduler 가 자동 계산하는 값이라 토글 대상에서 제외한다.
     */
    private static final Set<String> TOGGLEABLE_FLAGS = Set.of(
            "bypass_market_hours",
            "strategy_session_filter",
            "strategy_session_dry_run",
            "strategy_session_fail_open",
            "session_enter_guard");

    private final OperationsHealthService operationsHealthService;
    private final SystemHealthSnapshotService systemHealthSnapshotService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final JdbcTemplate jdbcTemplate;

    @Value("${claude.max-calls-per-day:100}")
    private int maxClaudeCallsPerDay;

    /** api-orchestrator 자체 상세 헬스(큐/ws하트비트/플래그/스케줄러) + 4개 서비스 교차 헬스체크를 한 번에 반환 */
    @GetMapping("/overview")
    public ResponseEntity<Map<String, Object>> overview() {
        Map<String, Object> result = new LinkedHashMap<>(operationsHealthService.buildHealthSnapshot());
        result.put("cross_service", systemHealthSnapshotService.buildSnapshot());
        return ResponseEntity.ok(result);
    }

    /** ai-engine이 scorer.py/analyzer.py에서 기록하는 일별 Claude 호출/토큰 카운터 조회 (claude:daily_calls:{yyyyMMdd}) */
    @GetMapping("/claude-usage")
    public ResponseEntity<Map<String, Object>> claudeUsage() {
        String dateKey = KstClock.today().format(YYYYMMDD);
        long calls = parseLongOrZero(redis.opsForValue().get("claude:daily_calls:" + dateKey));
        long tokens = parseLongOrZero(redis.opsForValue().get("claude:daily_tokens:" + dateKey));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("business_date", KstClock.today().toString());
        result.put("calls_today", calls);
        result.put("tokens_today", tokens);
        result.put("max_calls_per_day", maxClaudeCallsPerDay);
        result.put("usage_pct", maxClaudeCallsPerDay > 0
                ? Math.round(calls * 1000.0 / maxClaudeCallsPerDay) / 10.0
                : null);
        return ResponseEntity.ok(result);
    }

    /** Toss 국내 장 운영 캘린더를 대시보드가 외부 호출 없이 확인한다. */
    @GetMapping("/market-calendar")
    public ResponseEntity<Map<String, Object>> marketCalendar() {
        String date = KstClock.today().toString();
        String status = redis.opsForValue().get("market:kr:calendar:" + date);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("business_date", date);
        result.put("status", status == null ? "UNKNOWN" : status);
        result.put("source", status == null ? "NONE" : "TOSS");
        result.put("scheduled_work_enabled", "OPEN".equals(status));
        return ResponseEntity.ok(result);
    }

    /** 예약 발송된 뉴스 브리핑 원문과 분석 메타데이터를 최신순으로 반환한다. */
    @GetMapping("/briefing-history")
    public ResponseEntity<Map<String, Object>> briefingHistory(@RequestParam(defaultValue = "30") int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        List<String> raw = redis.opsForList().range("news:brief:history", 0, safeLimit - 1L);
        List<Map<String, Object>> items = new ArrayList<>();
        for (String value : raw == null ? List.<String>of() : raw) {
            try {
                items.add(objectMapper.readValue(value, new TypeReference<Map<String, Object>>() {}));
            } catch (Exception e) {
                log.debug("[Admin] briefing history parse failed: {}", e.getMessage());
            }
        }
        if (items.isEmpty()) {
            String latest = redis.opsForValue().get("news:analysis");
            if (latest != null && !latest.isBlank()) {
                try {
                    Map<String, Object> analysis = objectMapper.readValue(
                            latest, new TypeReference<Map<String, Object>>() {});
                    Map<String, Object> fallback = new LinkedHashMap<>();
                    fallback.put("id", "latest-cache");
                    fallback.put("business_date", KstClock.today().toString());
                    fallback.put("published_at", redis.opsForValue().get("ops:scheduler:news_scheduler:last_success_at"));
                    fallback.put("slot_name", analysis.getOrDefault("brief_slot", "LATEST"));
                    fallback.put("market_sentiment", analysis.getOrDefault("market_sentiment", "NEUTRAL"));
                    fallback.put("news_count", analysis.getOrDefault("news_count", 0));
                    fallback.put("ai_used", false);
                    fallback.put("used_cached_analysis", true);
                    fallback.put("message", analysis.getOrDefault("summary", "최근 캐시 브리핑"));
                    fallback.put("analysis", analysis);
                    items.add(fallback);
                } catch (Exception e) {
                    log.debug("[Admin] latest briefing fallback parse failed: {}", e.getMessage());
                }
            }
        }
        return ResponseEntity.ok(Map.of("count", items.size(), "items", items));
    }

    /** hold_monitor_worker가 관리하는 관심종목(HOLD_WATCH) 추적 큐 현황 (hold_monitor:items 해시 파싱) */
    @GetMapping("/hold-watch")
    public ResponseEntity<List<Map<String, Object>>> holdWatch() {
        Map<Object, Object> entries;
        try {
            entries = redis.opsForHash().entries("hold_monitor:items");
        } catch (Exception e) {
            log.warn("[Admin] hold_monitor:items 조회 실패: {}", e.getMessage());
            return ResponseEntity.ok(List.of());
        }

        long nowEpoch = Instant.now().getEpochSecond();
        List<Map<String, Object>> items = new ArrayList<>();
        for (Map.Entry<Object, Object> e : entries.entrySet()) {
            try {
                Map<String, Object> parsed = objectMapper.readValue(
                        String.valueOf(e.getValue()), new TypeReference<Map<String, Object>>() {});
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("key", String.valueOf(e.getKey()));
                item.put("stk_cd", parsed.get("stk_cd"));
                item.put("stk_nm", parsed.get("stk_nm"));
                item.put("strategy", parsed.get("strategy"));
                item.put("hold_reason", parsed.getOrDefault("hold_reason", parsed.get("hold_monitor_last_gate")));
                item.put("ai_score", parsed.get("ai_score"));
                item.put("attempts", parsed.getOrDefault("hold_monitor_attempts", 0));
                Object enqueuedAt = parsed.get("hold_monitor_enqueued_at");
                if (enqueuedAt != null) {
                    long enqueued = (long) Double.parseDouble(String.valueOf(enqueuedAt));
                    item.put("age_sec", Math.max(0L, nowEpoch - enqueued));
                } else {
                    item.put("age_sec", null);
                }
                items.add(item);
            } catch (Exception parseEx) {
                log.debug("[Admin] hold_monitor item 파싱 실패 key={}: {}", e.getKey(), parseEx.getMessage());
            }
        }
        items.sort(Comparator.comparing(
                (Map<String, Object> m) -> m.get("age_sec") == null ? -1L : ((Number) m.get("age_sec")).longValue(),
                Comparator.reverseOrder()));
        return ResponseEntity.ok(items);
    }

    /** 런타임 플래그 온오프. flags:{name} Redis 키에 저장하며, 각 서비스는 다음 조회 시점에 즉시 이 값을 반영한다. */
    @PostMapping("/flags/{name}")
    public ResponseEntity<Map<String, Object>> setFlag(@PathVariable String name, @RequestBody(required = false) Map<String, Object> body) {
        String key = name == null ? "" : name.trim().toLowerCase();
        if (!TOGGLEABLE_FLAGS.contains(key)) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body(Map.of("status", "error", "message", "unsupported flag: " + name));
        }
        Object rawValue = body == null ? null : body.get("enabled");
        boolean enabled = Boolean.TRUE.equals(rawValue) || "true".equalsIgnoreCase(String.valueOf(rawValue));
        redis.opsForValue().set("flags:" + key, enabled ? "true" : "false");
        log.info("[Admin] runtime flag override name={} enabled={}", key, enabled);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "ok");
        result.put("name", key);
        result.put("enabled", enabled);
        return ResponseEntity.ok(result);
    }

    /**
     * 스코어링 시점 데이터 신선도 감사 로그 (signal_data_freshness_log, 기본 3일 보관).
     * 최근 N건 상세 목록 + 지난 24시간 REST 폴백/신선도 분포 요약을 함께 반환한다.
     */
    @GetMapping("/freshness")
    public ResponseEntity<Map<String, Object>> freshness(@RequestParam(defaultValue = "200") int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 500));

        List<Map<String, Object>> rows;
        try {
            rows = jdbcTemplate.queryForList(
                    """
                    SELECT f.id, f.signal_id, f.stk_cd, ts.stk_nm, f.strategy, f.action, f.freshness_status,
                           f.tick_state, f.tick_source, f.tick_age_ms,
                           f.hoga_state, f.hoga_source, f.hoga_age_ms,
                           f.strength_state, f.strength_source, f.strength_age_ms,
                           f.vi_state, f.vi_source, f.vi_age_ms,
                           f.rest_fallback_used, f.rest_fallback_fields, f.rest_failure_classes,
                           f.created_at
                    FROM signal_data_freshness_log f
                    LEFT JOIN trading_signals ts ON ts.id = f.signal_id
                    ORDER BY f.created_at DESC
                    LIMIT ?
                    """,
                    safeLimit);
        } catch (Exception e) {
            log.warn("[Admin] signal_data_freshness_log 조회 실패: {}", e.getMessage());
            return ResponseEntity.ok(Map.of("summary", Map.of(), "items", List.of()));
        }
        for (Map<String, Object> row : rows) {
            row.put("rest_fallback_fields", parseJsonbColumn(row.get("rest_fallback_fields")));
            row.put("rest_failure_classes", parseJsonbColumn(row.get("rest_failure_classes")));
        }

        Map<String, Object> summary;
        try {
            Map<String, Object> agg = jdbcTemplate.queryForMap(
                    """
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE rest_fallback_used) AS rest_fallback_count,
                           COUNT(*) FILTER (WHERE freshness_status = 'FRESH') AS fresh_count,
                           COUNT(*) FILTER (WHERE freshness_status = 'CAUTION') AS caution_count,
                           COUNT(*) FILTER (WHERE freshness_status = 'STALE') AS stale_count,
                           COUNT(*) FILTER (WHERE freshness_status IS NULL) AS unknown_count
                    FROM signal_data_freshness_log
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                    """);
            long total = ((Number) agg.getOrDefault("total", 0L)).longValue();
            long restFallback = ((Number) agg.getOrDefault("rest_fallback_count", 0L)).longValue();
            Map<String, Object> summaryMap = new LinkedHashMap<>(agg);
            summaryMap.put("rest_fallback_pct", total > 0 ? Math.round(restFallback * 1000.0 / total) / 10.0 : 0.0);
            summaryMap.put("window", "24h");
            summary = summaryMap;
        } catch (Exception e) {
            log.warn("[Admin] signal_data_freshness_log 요약 조회 실패: {}", e.getMessage());
            summary = Map.of();
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("summary", summary);
        result.put("items", rows);
        return ResponseEntity.ok(result);
    }

    /** 활성 포지션(ACTIVE/PARTIAL_TP/OVERNIGHT) 실시간 모니터. ws:tick:{stk_cd} 최신 체결가로 PnL%/PnL금액을 계산한다. */
    @GetMapping("/positions")
    public ResponseEntity<List<Map<String, Object>>> positions() {
        List<Map<String, Object>> rows;
        try {
            rows = jdbcTemplate.queryForList(
                    """
                    SELECT stk_cd, stk_nm, strategy, status, entry_price, entry_qty, remaining_qty,
                           entry_at, tp1_price, tp2_price, sl_price, rr_ratio, is_overnight,
                           ROUND(EXTRACT(EPOCH FROM (NOW() - entry_at)) / 60)::bigint AS holding_min
                    FROM open_positions
                    WHERE status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
                    ORDER BY entry_at DESC
                    """);
        } catch (Exception e) {
            log.warn("[Admin] open_positions 조회 실패: {}", e.getMessage());
            return ResponseEntity.ok(List.of());
        }
        for (Map<String, Object> row : rows) {
            Double curPrc = fetchCurrentPrice(String.valueOf(row.get("stk_cd")));
            row.put("cur_prc", curPrc);
            Object entryPriceObj = row.get("entry_price");
            if (curPrc != null && entryPriceObj instanceof Number entryPriceNum && entryPriceNum.doubleValue() != 0) {
                double entryPrice = entryPriceNum.doubleValue();
                double pnlPct = (curPrc - entryPrice) / entryPrice * 100.0;
                row.put("pnl_pct", Math.round(pnlPct * 100) / 100.0);
                Object qtyObj = row.get("remaining_qty") != null ? row.get("remaining_qty") : row.get("entry_qty");
                if (qtyObj instanceof Number qtyNum) {
                    row.put("pnl_abs", Math.round((curPrc - entryPrice) * qtyNum.doubleValue()));
                }
            }
        }
        return ResponseEntity.ok(rows);
    }

    private Double fetchCurrentPrice(String stkCd) {
        try {
            Object val = redis.opsForHash().get("ws:tick:" + stkCd, "cur_prc");
            if (val == null) return null;
            String text = String.valueOf(val).replace(",", "").replace("+", "").trim();
            return text.isEmpty() ? null : Math.abs(Double.parseDouble(text));
        } catch (Exception e) {
            return null;
        }
    }

    /** daily_pnl 일별 손익 추이 (기본 최근 30일, 오래된순으로 반환해 차트가 시간순으로 그리기 쉽게 함). */
    @GetMapping("/pnl-history")
    public ResponseEntity<List<Map<String, Object>>> pnlHistory(@RequestParam(defaultValue = "30") int days) {
        int safeDays = Math.max(1, Math.min(days, 180));
        try {
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                    """
                    SELECT date, net_pnl_pct, cumulative_pnl_pct, gross_pnl_pct, win_rate,
                           enter_count, closed_count, tp_hit_count, sl_hit_count, force_close_count,
                           current_drawdown_pct, kospi_change_pct, kosdaq_change_pct
                    FROM daily_pnl
                    ORDER BY date DESC
                    LIMIT ?
                    """,
                    safeDays);
            java.util.Collections.reverse(rows);
            return ResponseEntity.ok(rows);
        } catch (Exception e) {
            log.warn("[Admin] daily_pnl 조회 실패: {}", e.getMessage());
            return ResponseEntity.ok(List.of());
        }
    }

    /** error_queue Redis 리스트에 쌓인 처리 실패 신호를 그대로 확인 (파괴적이지 않은 LRANGE 조회, pop 하지 않음). */
    @GetMapping("/error-queue")
    public ResponseEntity<List<Map<String, Object>>> errorQueue(@RequestParam(defaultValue = "50") int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 200));
        List<String> raw;
        try {
            raw = redis.opsForList().range("error_queue", 0, safeLimit - 1L);
        } catch (Exception e) {
            log.warn("[Admin] error_queue 조회 실패: {}", e.getMessage());
            return ResponseEntity.ok(List.of());
        }
        List<Map<String, Object>> items = new ArrayList<>();
        for (String rawItem : (raw == null ? List.<String>of() : raw)) {
            try {
                items.add(objectMapper.readValue(rawItem, new TypeReference<Map<String, Object>>() {}));
            } catch (Exception e) {
                Map<String, Object> fallback = new LinkedHashMap<>();
                fallback.put("raw", rawItem);
                items.add(fallback);
            }
        }
        return ResponseEntity.ok(items);
    }

    private Object parseJsonbColumn(Object value) {
        if (value == null) return List.of();
        try {
            return objectMapper.readValue(value.toString(), new TypeReference<List<Object>>() {});
        } catch (Exception e) {
            return List.of();
        }
    }

    private long parseLongOrZero(String value) {
        if (value == null || value.isBlank()) return 0L;
        try {
            return Long.parseLong(value.trim());
        } catch (NumberFormatException e) {
            return 0L;
        }
    }
}
