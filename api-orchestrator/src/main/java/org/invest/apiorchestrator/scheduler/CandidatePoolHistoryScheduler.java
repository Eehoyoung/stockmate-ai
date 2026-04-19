package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.util.MarketTimeUtil;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Redis candidates:s{N}:{market} 풀을 1분마다 스냅샷하여
 * candidate_pool_history 에 UPSERT (appear_count 누적).
 *
 * 풀이 비어 있더라도 키가 존재하면 관찰 대상으로 간주한다.
 * 풀 내 순위 기반 pool_score: 1위=100점, 꼴찌≈0점.
 *
 * 거래 시간(07:30~15:20) 에만 동작.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class CandidatePoolHistoryScheduler {

    private final StringRedisTemplate redis;
    private final JdbcTemplate         jdbc;
    private final StockMasterRepository stockMasterRepo;

    /** Redis key suffix → DB strategy 이름 (StrategyType.name() 과 일치) */
    private static final Map<String, String> STRATEGY_MAP = new LinkedHashMap<>();
    static {
        STRATEGY_MAP.put("s1",  "S1_GAP_OPEN");
        STRATEGY_MAP.put("s2",  "S2_VI_PULLBACK");
        STRATEGY_MAP.put("s3",  "S3_INST_FRGN");
        STRATEGY_MAP.put("s4",  "S4_BIG_CANDLE");
        STRATEGY_MAP.put("s5",  "S5_PROG_FRGN");
        STRATEGY_MAP.put("s6",  "S6_THEME_LAGGARD");
        STRATEGY_MAP.put("s7",  "S7_ICHIMOKU_BREAKOUT");
        STRATEGY_MAP.put("s8",  "S8_GOLDEN_CROSS");
        STRATEGY_MAP.put("s9",  "S9_PULLBACK_SWING");
        STRATEGY_MAP.put("s10", "S10_NEW_HIGH");
        STRATEGY_MAP.put("s11", "S11_FRGN_CONT");
        STRATEGY_MAP.put("s12", "S12_CLOSING");
        STRATEGY_MAP.put("s13", "S13_BOX_BREAKOUT");
        STRATEGY_MAP.put("s14", "S14_OVERSOLD_BOUNCE");
        STRATEGY_MAP.put("s15", "S15_MOMENTUM_ALIGN");
    }

    private static final String[] MARKETS = {"001", "101"};

    private static final String UPSERT_SQL = """
            INSERT INTO candidate_pool_history
                (date, strategy, market, stk_cd, stk_nm, pool_score, appear_count, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, 1, NOW(), NOW())
            ON CONFLICT (date, strategy, market, stk_cd)
            DO UPDATE SET
                appear_count = candidate_pool_history.appear_count + 1,
                last_seen    = NOW(),
                pool_score   = EXCLUDED.pool_score,
                stk_nm       = COALESCE(EXCLUDED.stk_nm, candidate_pool_history.stk_nm)
            """;

    /**
     * 60초마다 (초기 30초 후 시작) – 거래 시간 외 자동 스킵.
     */
    @Scheduled(fixedDelay = 60_000, initialDelay = 30_000)
    public void snapshotCandidatePools() {
        if (!MarketTimeUtil.isTradingActive()) return;

        LocalDate today = LocalDate.now();

        // ── 1. Redis에서 전략별 후보 수집 ────────────────────────
        // row: [strategy, market, stkCd, poolScore]
        List<Object[]> rows    = new ArrayList<>();
        Set<String>    allCodes = new HashSet<>();

        for (Map.Entry<String, String> entry : STRATEGY_MAP.entrySet()) {
            String sKey     = entry.getKey();
            String strategy = entry.getValue();

            for (String market : MARKETS) {
                String redisKey = "candidates:" + sKey + ":" + market;
                List<String> codes = redis.opsForList().range(redisKey, 0, -1);
                if (codes == null || codes.isEmpty()) continue;

                int size = codes.size();
                for (int i = 0; i < size; i++) {
                    String stkCd = codes.get(i);
                    if (stkCd == null || stkCd.isBlank()) continue;

                    // 순위 기반 score: 1위(i=0)=100점, 꼴찌≈0점
                    BigDecimal score = size > 1
                            ? BigDecimal.valueOf(100.0 * (size - i) / size)
                                       .setScale(2, RoundingMode.HALF_UP)
                            : BigDecimal.valueOf(100.00).setScale(2, RoundingMode.HALF_UP);

                    rows.add(new Object[]{strategy, market, stkCd, score});
                    allCodes.add(stkCd);
                }
            }
        }

        if (rows.isEmpty()) {
            log.debug("[PoolHistory] Redis 후보 풀 전체 비어있음 – 스킵");
            return;
        }

        // ── 2. 종목명 일괄 조회 (StockMaster, 단일 IN 쿼리) ──────
        Map<String, String> nameMap = stockMasterRepo.findAllById(allCodes).stream()
                .collect(Collectors.toMap(
                        sm -> sm.getStkCd(),
                        sm -> sm.getStkNm(),
                        (a, b) -> a));

        // ── 3. JDBC 배치 UPSERT ───────────────────────────────────
        List<Object[]> batchArgs = rows.stream()
                .map(row -> new Object[]{
                        today,               // date
                        row[0],              // strategy
                        row[1],              // market
                        row[2],              // stkCd
                        nameMap.get(row[2]), // stkNm (null 허용)
                        row[3]               // pool_score
                })
                .collect(Collectors.toList());

        try {
            jdbc.batchUpdate(UPSERT_SQL, batchArgs);
            log.debug("[PoolHistory] 스냅샷 완료 – {} 전략키, {}건 UPSERT",
                    STRATEGY_MAP.size(), batchArgs.size());
        } catch (Exception e) {
            log.warn("[PoolHistory] 배치 UPSERT 실패: {}", e.getMessage());
        }
    }
}
