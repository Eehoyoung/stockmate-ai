package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import org.invest.apiorchestrator.dto.res.CandidateSearchResponse;
import org.invest.apiorchestrator.util.KstClock;
import org.invest.apiorchestrator.util.StockCodeNormalizer;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class CandidateSearchService {

    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 200;
    private static final int ROW_SCAN_LIMIT = 2_000;

    private static final Map<String, String> STRATEGY_TO_REDIS_SUFFIX = Map.ofEntries(
            Map.entry("S1_GAP_OPEN", "s1"),
            Map.entry("S2_VI_PULLBACK", "s2"),
            Map.entry("S3_INST_FRGN", "s3"),
            Map.entry("S4_BIG_CANDLE", "s4"),
            Map.entry("S5_PROG_FRGN", "s5"),
            Map.entry("S6_THEME_LAGGARD", "s6"),
            Map.entry("S7_ICHIMOKU_BREAKOUT", "s7"),
            Map.entry("S8_GOLDEN_CROSS", "s8"),
            Map.entry("S9_PULLBACK_SWING", "s9"),
            Map.entry("S10_NEW_HIGH", "s10"),
            Map.entry("S11_FRGN_CONT", "s11"),
            Map.entry("S12_CLOSING", "s12"),
            Map.entry("S13_BOX_BREAKOUT", "s13"),
            Map.entry("S14_OVERSOLD_BOUNCE", "s14"),
            Map.entry("S15_MOMENTUM_ALIGN", "s15")
    );

    private static final Map<String, String> REDIS_SUFFIX_TO_STRATEGY = Map.ofEntries(
            Map.entry("s1", "S1_GAP_OPEN"),
            Map.entry("s2", "S2_VI_PULLBACK"),
            Map.entry("s3", "S3_INST_FRGN"),
            Map.entry("s4", "S4_BIG_CANDLE"),
            Map.entry("s5", "S5_PROG_FRGN"),
            Map.entry("s6", "S6_THEME_LAGGARD"),
            Map.entry("s7", "S7_ICHIMOKU_BREAKOUT"),
            Map.entry("s8", "S8_GOLDEN_CROSS"),
            Map.entry("s9", "S9_PULLBACK_SWING"),
            Map.entry("s10", "S10_NEW_HIGH"),
            Map.entry("s11", "S11_FRGN_CONT"),
            Map.entry("s12", "S12_CLOSING"),
            Map.entry("s13", "S13_BOX_BREAKOUT"),
            Map.entry("s14", "S14_OVERSOLD_BOUNCE"),
            Map.entry("s15", "S15_MOMENTUM_ALIGN")
    );

    private final NamedParameterJdbcTemplate jdbc;
    private final StringRedisTemplate redis;

    public CandidateSearchResponse search(SearchRequest request) {
        SearchRequest normalized = request.normalized();
        LiveCandidateSnapshot liveSnapshot = loadLiveSnapshot(normalized.strategies(), normalized.markets());

        List<CandidateRow> rows = jdbc.query(buildSql(normalized), buildParams(normalized), this::mapRow);
        Set<String> rowKeys = new LinkedHashSet<>();
        Map<String, CandidateAggregate> grouped = new LinkedHashMap<>();
        for (CandidateRow row : rows) {
            rowKeys.add(liveKey(row.strategy(), row.market(), row.stkCd()));
            String groupKey = row.market() + "|" + row.stkCd();
            grouped.computeIfAbsent(groupKey, ignored -> new CandidateAggregate(row))
                    .add(row, liveSnapshot.liveKeys().contains(liveKey(row.strategy(), row.market(), row.stkCd())));
        }
        for (CandidateRow liveRow : liveSnapshot.redisRows()) {
            if (rowKeys.contains(liveKey(liveRow.strategy(), liveRow.market(), liveRow.stkCd()))) {
                continue;
            }
            if (!matchesRedisOnlyFilters(liveRow, normalized)) {
                continue;
            }
            String groupKey = liveRow.market() + "|" + liveRow.stkCd();
            grouped.computeIfAbsent(groupKey, ignored -> new CandidateAggregate(liveRow))
                    .add(liveRow, true);
        }

        List<CandidateAggregate> sortedMatches = grouped.values().stream()
                .filter(item -> !normalized.liveOnly() || item.live)
                .sorted(aggregateComparator(normalized.sort()))
                .toList();
        int totalMatches = sortedMatches.size();
        List<CandidateSearchResponse.CandidateSearchItem> items = sortedMatches.stream()
                .limit(normalized.limit())
                .map(this::toItem)
                .toList();

        long liveCount = items.stream().filter(CandidateSearchResponse.CandidateSearchItem::live).count();
        Map<String, Object> filters = new LinkedHashMap<>();
        filters.put("query", normalized.query());
        filters.put("sector", normalized.sector());
        filters.put("min_pool_score", normalized.minPoolScore());
        filters.put("min_appear_count", normalized.minAppearCount());
        filters.put("seen_within_min", normalized.seenWithinMin());
        filters.put("led_to_signal", normalized.ledToSignal());
        filters.put("live_only", normalized.liveOnly());
        filters.put("sort", normalized.sort());
        filters.put("limit", normalized.limit());

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("live_count", liveCount);
        summary.put("history_only_count", items.size() - liveCount);
        summary.put("returned_count", items.size());
        summary.put("total_matching_candidates", totalMatches);
        summary.put("live_ratio", items.isEmpty() ? 0.0 : Math.round((liveCount * 10000.0) / items.size()) / 100.0);
        summary.put("scope", "candidate_pool_search_not_full_market_screener");
        summary.put("execution_validation", "BEST_HOGA_SPREAD_ESTIMATE_WHEN_AVAILABLE_NOT_REAL_FILL");

        return new CandidateSearchResponse(
                normalized.date(),
                normalized.market(),
                normalized.strategies(),
                totalMatches,
                rows.size(),
                filters,
                summary,
                items
        );
    }

    public Map<String, Object> buildDataQualityReport(String market, List<String> strategies) {
        SearchRequest normalized = new SearchRequest(
                KstClock.today(), market, strategies, null, null, null, null, null, null, false, "score", DEFAULT_LIMIT
        ).normalized();
        LiveCandidateSnapshot liveSnapshot = loadLiveSnapshot(normalized.strategies(), normalized.markets());
        Set<String> codes = new LinkedHashSet<>();
        for (CandidateRow row : liveSnapshot.redisRows()) {
            codes.add(row.stkCd());
        }

        int tickMissing = 0;
        int hogaMissing = 0;
        int tickStale = 0;
        int hogaStale = 0;
        int fresh = 0;
        List<Map<String, Object>> worst = new ArrayList<>();
        for (String code : codes) {
            Map<Object, Object> tick = redisHash("ws:tick:" + code);
            Map<Object, Object> hoga = redisHash("ws:hoga:" + code);
            Long tickAge = ageMs(tick.get("updated_at_ms"));
            Long hogaAge = ageMs(hoga.get("updated_at_ms"));
            boolean missingTick = tick.isEmpty();
            boolean missingHoga = hoga.isEmpty();
            boolean staleTick = tickAge != null && tickAge > 30_000;
            boolean staleHoga = hogaAge != null && hogaAge > 30_000;
            if (missingTick) tickMissing++;
            if (missingHoga) hogaMissing++;
            if (staleTick) tickStale++;
            if (staleHoga) hogaStale++;
            if (!missingTick && !missingHoga && !staleTick && !staleHoga) fresh++;
            if (missingTick || missingHoga || staleTick || staleHoga) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("stk_cd", code);
                item.put("tick_age_ms", tickAge);
                item.put("hoga_age_ms", hogaAge);
                item.put("tick_missing", missingTick);
                item.put("hoga_missing", missingHoga);
                item.put("tick_stale", staleTick);
                item.put("hoga_stale", staleHoga);
                worst.add(item);
            }
        }

        int total = codes.size();
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("market", normalized.market());
        report.put("strategies", normalized.strategies());
        report.put("unique_live_candidates", total);
        report.put("fresh_count", fresh);
        report.put("tick_missing_count", tickMissing);
        report.put("hoga_missing_count", hogaMissing);
        report.put("tick_stale_count", tickStale);
        report.put("hoga_stale_count", hogaStale);
        report.put("fresh_ratio", total == 0 ? 0.0 : round2(fresh * 100.0 / total));
        report.put("status", total == 0 ? "NO_LIVE_CANDIDATES" : (fresh * 100.0 / total >= 80.0 ? "OK" : "DEGRADED"));
        report.put("worst", worst.stream().limit(20).toList());
        return report;
    }

    private String buildSql(SearchRequest request) {
        StringBuilder sql = new StringBuilder("""
                SELECT c.date,
                       c.strategy,
                       c.market,
                       c.stk_cd,
                       COALESCE(c.stk_nm, sm.stk_nm) AS stk_nm,
                       sm.sector,
                       sm.industry,
                       sm.market_cap,
                       c.pool_score,
                       c.appear_count,
                       c.first_seen,
                       c.last_seen,
                       c.led_to_signal,
                       c.signal_id
                  FROM candidate_pool_history c
                  LEFT JOIN stock_master sm ON sm.stk_cd = c.stk_cd
                 WHERE c.date = :date
                   AND c.market IN (:markets)
                   AND c.strategy IN (:strategies)
                """);
        if (request.query() != null && !request.query().isBlank()) {
            sql.append("""
                   AND (
                         c.stk_cd = :normalizedCode
                         OR LOWER(COALESCE(c.stk_nm, sm.stk_nm, '')) LIKE :queryLike
                         OR LOWER(COALESCE(sm.sector, '')) LIKE :queryLike
                         OR LOWER(COALESCE(sm.industry, '')) LIKE :queryLike
                   )
                """);
        }
        if (request.sector() != null && !request.sector().isBlank()) {
            sql.append("   AND LOWER(COALESCE(sm.sector, '')) LIKE :sectorLike\n");
        }
        if (request.seenWithinMin() != null) {
            sql.append("   AND c.last_seen >= :seenAfter\n");
        }
        if (request.minPoolScore() != null) {
            sql.append("   AND c.pool_score >= :minPoolScore\n");
        }
        if (request.minAppearCount() != null) {
            sql.append("   AND c.appear_count >= :minAppearCount\n");
        }
        if (request.ledToSignal() != null) {
            sql.append("   AND COALESCE(c.led_to_signal, FALSE) = :ledToSignal\n");
        }
        sql.append("""
                 ORDER BY c.last_seen DESC, c.pool_score DESC NULLS LAST, c.appear_count DESC
                 LIMIT :rowLimit
                """);
        return sql.toString();
    }

    private MapSqlParameterSource buildParams(SearchRequest request) {
        MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("date", request.date())
                .addValue("markets", request.markets())
                .addValue("strategies", request.strategies())
                .addValue("rowLimit", ROW_SCAN_LIMIT);
        if (request.query() != null && !request.query().isBlank()) {
            params.addValue("normalizedCode", StockCodeNormalizer.normalize(request.query()));
            params.addValue("queryLike", "%" + request.query().toLowerCase(Locale.ROOT).trim() + "%");
        }
        if (request.sector() != null && !request.sector().isBlank()) {
            params.addValue("sectorLike", "%" + request.sector().toLowerCase(Locale.ROOT).trim() + "%");
        }
        if (request.seenWithinMin() != null) {
            params.addValue("seenAfter", KstClock.nowOffset().minusMinutes(request.seenWithinMin()));
        }
        if (request.minPoolScore() != null) {
            params.addValue("minPoolScore", request.minPoolScore());
        }
        if (request.minAppearCount() != null) {
            params.addValue("minAppearCount", request.minAppearCount());
        }
        if (request.ledToSignal() != null) {
            params.addValue("ledToSignal", request.ledToSignal());
        }
        return params;
    }

    private CandidateRow mapRow(ResultSet rs, int rowNum) throws SQLException {
        return new CandidateRow(
                rs.getString("strategy"),
                rs.getString("market"),
                rs.getString("stk_cd"),
                rs.getString("stk_nm"),
                rs.getString("sector"),
                rs.getString("industry"),
                rs.getObject("market_cap", Long.class),
                rs.getBigDecimal("pool_score"),
                valueOrZero(rs.getObject("appear_count", Integer.class)),
                rs.getObject("first_seen", OffsetDateTime.class),
                rs.getObject("last_seen", OffsetDateTime.class),
                rs.getBoolean("led_to_signal"),
                rs.getObject("signal_id", Long.class),
                false
        );
    }

    private LiveCandidateSnapshot loadLiveSnapshot(List<String> strategies, List<String> markets) {
        Set<String> keys = new LinkedHashSet<>();
        List<CandidateRow> rows = new ArrayList<>();
        for (String strategy : strategies) {
            String suffix = STRATEGY_TO_REDIS_SUFFIX.get(strategy);
            if (suffix == null) {
                continue;
            }
            for (String market : markets) {
                try {
                    List<String> codes = redis.opsForList().range("candidates:" + suffix + ":" + market, 0, -1);
                    if (codes == null) {
                        continue;
                    }
                    int size = codes.size();
                    for (int i = 0; i < size; i++) {
                        String code = codes.get(i);
                        String normalizedCode = StockCodeNormalizer.normalize(code);
                        if (normalizedCode != null && !normalizedCode.isBlank()) {
                            keys.add(liveKey(strategy, market, normalizedCode));
                            rows.add(redisOnlyRow(strategy, market, normalizedCode, i, size));
                        }
                    }
                } catch (Exception ignored) {
                    return new LiveCandidateSnapshot(Set.of(), List.of());
                }
            }
        }
        return new LiveCandidateSnapshot(keys, rows);
    }

    private CandidateRow redisOnlyRow(String strategy, String market, String stkCd, int index, int size) {
        BigDecimal score = size > 1
                ? BigDecimal.valueOf(100.0 * (size - index) / size).setScale(2, java.math.RoundingMode.HALF_UP)
                : BigDecimal.valueOf(100.00).setScale(2, java.math.RoundingMode.HALF_UP);
        OffsetDateTime now = KstClock.nowOffset();
        return new CandidateRow(
                strategy,
                market,
                stkCd,
                null,
                null,
                null,
                null,
                score,
                0,
                now,
                now,
                false,
                null,
                true
        );
    }

    private boolean matchesRedisOnlyFilters(CandidateRow row, SearchRequest request) {
        if (request.minAppearCount() != null && request.minAppearCount() > 0) {
            return false;
        }
        if (request.ledToSignal() != null && request.ledToSignal()) {
            return false;
        }
        if (request.sector() != null) {
            return false;
        }
        if (request.minPoolScore() != null && (row.poolScore() == null || row.poolScore().compareTo(request.minPoolScore()) < 0)) {
            return false;
        }
        if (request.query() == null) {
            return true;
        }
        String normalizedQuery = StockCodeNormalizer.normalize(request.query());
        return row.stkCd().equals(normalizedQuery);
    }

    private CandidateSearchResponse.CandidateSearchItem toItem(CandidateAggregate aggregate) {
        Map<Object, Object> tick = redisHash("ws:tick:" + aggregate.stkCd);
        Map<Object, Object> hoga = redisHash("ws:hoga:" + aggregate.stkCd);
        Map<String, Object> dataQuality = buildDataQuality(aggregate, tick, hoga);
        Map<String, Object> executionValidation = buildExecutionValidation(hoga);
        return new CandidateSearchResponse.CandidateSearchItem(
                aggregate.stkCd,
                aggregate.stkNm,
                aggregate.market,
                aggregate.sector,
                aggregate.industry,
                aggregate.marketCap,
                aggregate.maxPoolScore,
                aggregate.totalAppearCount,
                aggregate.strategies.size(),
                aggregate.firstSeen,
                aggregate.lastSeen,
                aggregate.live,
                new ArrayList<>(aggregate.strategies),
                new ArrayList<>(aggregate.liveStrategies),
                aggregate.ledToSignal,
                new ArrayList<>(aggregate.signalIds),
                dataQuality,
                executionValidation
        );
    }

    private Map<Object, Object> redisHash(String key) {
        try {
            Map<Object, Object> data = redis.opsForHash().entries(key);
            return data == null ? Map.of() : data;
        } catch (Exception ignored) {
            return Map.of();
        }
    }

    private Map<String, Object> buildDataQuality(CandidateAggregate aggregate, Map<Object, Object> tick, Map<Object, Object> hoga) {
        Long tickAgeMs = ageMs(tick.get("updated_at_ms"));
        Long hogaAgeMs = ageMs(hoga.get("updated_at_ms"));
        List<String> missing = new ArrayList<>();
        if (aggregate.stkNm == null || aggregate.stkNm.isBlank()) {
            missing.add("stock_master");
        }
        if (tick.isEmpty()) {
            missing.add("tick");
        } else if (tickAgeMs == null) {
            missing.add("tick_updated_at_ms");
        }
        if (hoga.isEmpty()) {
            missing.add("hoga");
        } else if (hogaAgeMs == null) {
            missing.add("hoga_updated_at_ms");
        }
        boolean tickFresh = tickAgeMs != null && tickAgeMs <= 10_000;
        boolean hogaFresh = hogaAgeMs != null && hogaAgeMs <= 10_000;
        boolean stale = tickAgeMs == null || hogaAgeMs == null || tickAgeMs > 30_000 || hogaAgeMs > 30_000;
        String grade;
        if (tick.isEmpty() || hoga.isEmpty() || tickAgeMs == null || hogaAgeMs == null) {
            grade = "D";
        } else if (tickFresh && hogaFresh) {
            grade = "A";
        } else if (stale) {
            grade = "C";
        } else {
            grade = "B";
        }
        Map<String, Object> quality = new LinkedHashMap<>();
        quality.put("grade", grade);
        quality.put("source", aggregate.live ? (aggregate.totalAppearCount > 0 ? "redis+db" : "redis_only") : "db_only");
        quality.put("live", aggregate.live);
        quality.put("stock_master_missing", aggregate.stkNm == null || aggregate.stkNm.isBlank());
        quality.put("tick_present", !tick.isEmpty());
        quality.put("hoga_present", !hoga.isEmpty());
        quality.put("tick_age_ms", tickAgeMs);
        quality.put("hoga_age_ms", hogaAgeMs);
        quality.put("stale", stale);
        quality.put("missing_fields", missing);
        return quality;
    }

    private Map<String, Object> buildExecutionValidation(Map<Object, Object> hoga) {
        Map<String, Object> execution = new LinkedHashMap<>();
        Long bid = parseLong(hoga.get("buy_bid_pric_1"));
        Long ask = parseLong(hoga.get("sel_bid_pric_1"));
        Long topBidSize = parseLong(hoga.get("buy_bid_req_1"));
        Long topAskSize = parseLong(hoga.get("sel_bid_req_1"));
        if (bid == null || ask == null || bid <= 0 || ask <= 0 || ask < bid) {
            execution.put("status", "NOT_AVAILABLE");
            execution.put("reason", "hoga_missing_or_invalid");
            return execution;
        }
        double mid = (bid + ask) / 2.0;
        double spreadPct = (ask - bid) / mid * 100.0;
        double estimatedBuySlippagePct = (ask - mid) / mid * 100.0;
        String liquidityGrade = liquidityGrade(spreadPct, topAskSize);
        execution.put("status", "SPREAD_ESTIMATE_ONLY");
        execution.put("method", "best_hoga_spread_estimate");
        execution.put("bid_price", bid);
        execution.put("ask_price", ask);
        execution.put("spread_pct", round2(spreadPct));
        execution.put("estimated_buy_slippage_pct", round2(estimatedBuySlippagePct));
        execution.put("top_bid_size", topBidSize);
        execution.put("top_ask_size", topAskSize);
        execution.put("liquidity_grade", liquidityGrade);
        execution.put("note", "best_hoga_only_not_order_size_depth_or_real_fill");
        return execution;
    }

    private static String liquidityGrade(double spreadPct, Long topAskSize) {
        if (topAskSize == null || topAskSize < 1_000) {
            return "D";
        }
        if (topAskSize < 5_000) {
            return spreadPct <= 0.10 ? "B" : "C";
        }
        if (spreadPct <= 0.10) return "A";
        if (spreadPct <= 0.25) return "B";
        if (spreadPct <= 0.50) return "C";
        return "D";
    }

    private static Long ageMs(Object updatedAtMs) {
        Long ts = parseLong(updatedAtMs);
        return ts == null ? null : Math.max(0L, System.currentTimeMillis() - ts);
    }

    private static Long parseLong(Object raw) {
        if (raw == null) {
            return null;
        }
        try {
            String value = raw.toString().replace(",", "").replace("+", "").trim();
            if (value.isBlank()) {
                return null;
            }
            return Math.abs(Long.parseLong(value));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static double round2(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private static Comparator<CandidateAggregate> aggregateComparator(String sort) {
        Comparator<BigDecimal> scoreDescNullsLast = Comparator.nullsLast(Comparator.reverseOrder());
        Comparator<OffsetDateTime> timeDescNullsLast = Comparator.nullsLast(Comparator.reverseOrder());
        Comparator<CandidateAggregate> byScore =
                Comparator.comparing(item -> item.maxPoolScore, scoreDescNullsLast);
        return switch (sort) {
            case "last_seen" -> Comparator.comparing(item -> item.lastSeen, timeDescNullsLast);
            case "appear_count" -> Comparator.comparingInt((CandidateAggregate item) -> item.totalAppearCount).reversed();
            case "strategy_count" -> Comparator.comparingInt((CandidateAggregate item) -> item.strategies.size()).reversed()
                    .thenComparing(byScore);
            case "code" -> Comparator.comparing(item -> item.stkCd);
            default -> byScore.thenComparing(item -> item.lastSeen, timeDescNullsLast);
        };
    }

    private static String liveKey(String strategy, String market, String stkCd) {
        return strategy + "|" + market + "|" + StockCodeNormalizer.normalize(stkCd);
    }

    private static int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }

    private record CandidateRow(
            String strategy,
            String market,
            String stkCd,
            String stkNm,
            String sector,
            String industry,
            Long marketCap,
            BigDecimal poolScore,
            int appearCount,
            OffsetDateTime firstSeen,
            OffsetDateTime lastSeen,
            boolean ledToSignal,
            Long signalId,
            boolean redisOnly
    ) {
    }

    private record LiveCandidateSnapshot(Set<String> liveKeys, List<CandidateRow> redisRows) {
    }

    private static final class CandidateAggregate {
        private final String stkCd;
        private final String stkNm;
        private final String market;
        private final String sector;
        private final String industry;
        private final Long marketCap;
        private BigDecimal maxPoolScore;
        private int totalAppearCount;
        private OffsetDateTime firstSeen;
        private OffsetDateTime lastSeen;
        private boolean live;
        private boolean ledToSignal;
        private final Set<String> strategies = new LinkedHashSet<>();
        private final Set<String> liveStrategies = new LinkedHashSet<>();
        private final Set<Long> signalIds = new LinkedHashSet<>();

        private CandidateAggregate(CandidateRow row) {
            this.stkCd = row.stkCd();
            this.stkNm = row.stkNm();
            this.market = row.market();
            this.sector = row.sector();
            this.industry = row.industry();
            this.marketCap = row.marketCap();
        }

        private void add(CandidateRow row, boolean rowLive) {
            strategies.add(row.strategy());
            if (rowLive) {
                live = true;
                liveStrategies.add(row.strategy());
            }
            if (row.poolScore() != null && (maxPoolScore == null || row.poolScore().compareTo(maxPoolScore) > 0)) {
                maxPoolScore = row.poolScore();
            }
            totalAppearCount += row.appearCount();
            if (firstSeen == null || (row.firstSeen() != null && row.firstSeen().isBefore(firstSeen))) {
                firstSeen = row.firstSeen();
            }
            if (lastSeen == null || (row.lastSeen() != null && row.lastSeen().isAfter(lastSeen))) {
                lastSeen = row.lastSeen();
            }
            ledToSignal = ledToSignal || row.ledToSignal();
            if (row.signalId() != null) {
                signalIds.add(row.signalId());
            }
        }

    }

    public record SearchRequest(
            LocalDate date,
            String market,
            List<String> strategies,
            String query,
            String sector,
            BigDecimal minPoolScore,
            Integer minAppearCount,
            Integer seenWithinMin,
            Boolean ledToSignal,
            boolean liveOnly,
            String sort,
            int limit
    ) {
        private SearchRequest normalized() {
            String normalizedMarket = normalizeMarket(market);
            return new SearchRequest(
                    date == null ? KstClock.today() : date,
                    normalizedMarket,
                    normalizeStrategies(strategies),
                    query == null || query.isBlank() ? null : query.trim(),
                    sector == null || sector.isBlank() ? null : sector.trim(),
                    minPoolScore,
                    minAppearCount,
                    seenWithinMin == null || seenWithinMin <= 0 ? null : seenWithinMin,
                    ledToSignal,
                    liveOnly,
                    normalizeSort(sort),
                    Math.max(1, Math.min(limit <= 0 ? DEFAULT_LIMIT : limit, MAX_LIMIT))
            );
        }

        private List<String> markets() {
            return "000".equals(market) ? List.of("001", "101") : List.of(market);
        }
    }

    private static String normalizeMarket(String market) {
        if (market == null || market.isBlank() || "all".equalsIgnoreCase(market) || "kospi+kosdaq".equalsIgnoreCase(market)) {
            return "000";
        }
        String normalized = market.trim().toLowerCase(Locale.ROOT);
        return switch (normalized) {
            case "kospi" -> "001";
            case "kosdaq" -> "101";
            case "001", "101", "000" -> normalized;
            default -> "000";
        };
    }

    private static List<String> normalizeStrategies(List<String> strategies) {
        if (strategies == null || strategies.isEmpty()) {
            return new ArrayList<>(STRATEGY_TO_REDIS_SUFFIX.keySet());
        }
        Set<String> normalized = new LinkedHashSet<>();
        for (String raw : strategies) {
            if (raw == null || raw.isBlank()) {
                continue;
            }
            String value = raw.trim().toLowerCase(Locale.ROOT);
            if (REDIS_SUFFIX_TO_STRATEGY.containsKey(value)) {
                normalized.add(REDIS_SUFFIX_TO_STRATEGY.get(value));
                continue;
            }
            String upper = raw.trim().toUpperCase(Locale.ROOT);
            if (STRATEGY_TO_REDIS_SUFFIX.containsKey(upper)) {
                normalized.add(upper);
            }
        }
        return normalized.isEmpty() ? new ArrayList<>(STRATEGY_TO_REDIS_SUFFIX.keySet()) : new ArrayList<>(normalized);
    }

    private static String normalizeSort(String sort) {
        if (sort == null || sort.isBlank()) {
            return "score";
        }
        String normalized = sort.trim().toLowerCase(Locale.ROOT);
        return switch (normalized) {
            case "score", "last_seen", "appear_count", "strategy_count", "code" -> normalized;
            default -> "score";
        };
    }
}
