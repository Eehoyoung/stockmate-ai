package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class RedisMarketDataService {

    private final StringRedisTemplate redis;

    // Redis 키 접두사 (Python websocket-listener 가 쓰는 키, Java 는 읽기 전용)
    private static final String KEY_TICK      = "ws:tick:";
    private static final String KEY_EXPECTED  = "ws:expected:";
    private static final String KEY_HOGA      = "ws:hoga:";
    private static final String KEY_STRENGTH  = "ws:strength:";
    private static final String KEY_VI        = "vi:";

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
     * 체결강도(ws:strength) 최근 N개 평균. 값이 클수록 매수 우위.
     * ws:strength 키가 없으면 100.0(중립) 반환.
     * 실제 데이터 유무는 hasStrengthData() 로 구분하라.
     *
     * 주의: Python redis_reader.get_hoga_ratio() 는 매도잔량/매수잔량 비율로
     * 분자·분모가 반대이다(ratio > 1.0 → 매도 우위). 두 값을 혼용하지 말 것.
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
     * ws:strength 데이터 존재 여부.
     * 데이터가 없으면 getAvgCntrStrength()가 항상 100.0을 반환하므로,
     * 임계값 필터를 적용하기 전에 이 메서드로 데이터 유무를 확인해야 한다.
     */
    public boolean hasStrengthData(String stkCd) {
        List<String> list = redis.opsForList().range(KEY_STRENGTH + stkCd, 0, 0);
        return list != null && !list.isEmpty();
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
        String key = "signal:daily_count:" + KstClock.today();
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
        String key = "signal:daily_count:" + KstClock.today();
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
     * 텔레그램 알림 큐에 푸시
     */
    public void pushTelegramQueue(String message) {
        redis.opsForList().leftPush("telegram_queue", message);
        redis.expire("telegram_queue", Duration.ofHours(12));
    }

}
