package org.invest.apiorchestrator.service;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.util.StockCodeNormalizer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;

/** Bounded REST fallback for final strategy candidates with stale WebSocket data. */
@Slf4j
@Service
public class KiwoomRestFallbackService {

    static final Duration DEFAULT_CACHE_TTL = Duration.ofSeconds(10);
    static final int DEFAULT_CALLS_PER_MINUTE = 5;
    private static final long WINDOW_MILLIS = Duration.ofMinutes(1).toMillis();

    private final KiwoomApiService apiService;
    private final LongSupplier nowMs;
    private final long cacheTtlMs;
    private final int callsPerMinute;
    private final Map<String, CachedStrength> strengthCache = new ConcurrentHashMap<>();
    private final Map<String, CachedInvestorFlow> investorFlowCache = new ConcurrentHashMap<>();
    private final Map<String, CachedViHistory> viHistoryCache = new ConcurrentHashMap<>();
    private final Object budgetLock = new Object();

    private long windowStartedAtMs;
    private int callsInWindow;

    @Autowired
    public KiwoomRestFallbackService(KiwoomApiService apiService) {
        this(apiService, System::currentTimeMillis, DEFAULT_CACHE_TTL, DEFAULT_CALLS_PER_MINUTE);
    }

    KiwoomRestFallbackService(KiwoomApiService apiService, LongSupplier nowMs,
                              Duration cacheTtl, int callsPerMinute) {
        if (cacheTtl == null || cacheTtl.isNegative()) {
            throw new IllegalArgumentException("cacheTtl must not be negative");
        }
        if (callsPerMinute <= 0) {
            throw new IllegalArgumentException("callsPerMinute must be positive");
        }
        this.apiService = apiService;
        this.nowMs = nowMs;
        this.cacheTtlMs = cacheTtl.toMillis();
        this.callsPerMinute = callsPerMinute;
    }

    public Optional<StrengthSnapshot> fetchStrength(String stkCd) {
        return fetchStrengthDetailed(stkCd).value();
    }

    public LookupResult<StrengthSnapshot> fetchStrengthDetailed(String stkCd) {
        stkCd = StockCodeNormalizer.normalize(stkCd);
        long now = nowMs.getAsLong();
        CachedStrength cached = strengthCache.get(stkCd);
        if (cached != null && now - cached.cachedAtMs <= cacheTtlMs) {
            return LookupResult.of(cached.snapshot, LookupStatus.CACHE_HIT);
        }
        if (!reserveCall(now)) {
            log.debug("[REST fallback] budget exhausted; ka10046 skipped stkCd={}", stkCd);
            return LookupResult.empty(LookupStatus.BUDGET_EXHAUSTED);
        }

        try {
            var response = apiService.fetchKa10046(stkCd);
            if (response == null || response.getCntrStrTm() == null || response.getCntrStrTm().isEmpty()) {
                return LookupResult.empty(LookupStatus.API_EMPTY);
            }
            var latest = response.getCntrStrTm().get(0);
            StrengthSnapshot snapshot = new StrengthSnapshot(
                    latest.getCntrTm(),
                    parse(latest.getCntrStr()),
                    parse(latest.getCntrStr5min()),
                    parse(latest.getCntrStr20min()),
                    parse(latest.getCntrStr60min())
            );
            if (snapshot.effectiveStrength() == null) {
                return LookupResult.empty(LookupStatus.API_EMPTY);
            }
            strengthCache.put(stkCd, new CachedStrength(snapshot, now));
            return LookupResult.of(snapshot, LookupStatus.REMOTE_SUCCESS);
        } catch (Exception e) {
            log.debug("[REST fallback] ka10046 failed stkCd={} cause={}", stkCd, e.getMessage());
            return LookupResult.empty(LookupStatus.API_ERROR);
        }
    }

    /**
     * Returns a bounded, short-lived ka10064 view for a final candidate. A negative
     * classification requires both the latest combined flow and the average of at
     * least two recent observations to be negative, avoiding a one-tick hard gate.
     */
    public Optional<InvestorFlowSnapshot> fetchInvestorFlow(String market, String stkCd) {
        return fetchInvestorFlowDetailed(market, stkCd).value();
    }

    public LookupResult<InvestorFlowSnapshot> fetchInvestorFlowDetailed(String market, String stkCd) {
        stkCd = StockCodeNormalizer.normalize(stkCd);
        String cacheKey = market + ":" + stkCd;
        long now = nowMs.getAsLong();
        CachedInvestorFlow cached = investorFlowCache.get(cacheKey);
        if (cached != null && now - cached.cachedAtMs <= cacheTtlMs) {
            return LookupResult.of(cached.snapshot, LookupStatus.CACHE_HIT);
        }
        if (!reserveCall(now)) {
            log.debug("[REST fallback] budget exhausted; ka10064 skipped stkCd={}", stkCd);
            return LookupResult.empty(LookupStatus.BUDGET_EXHAUSTED);
        }

        try {
            var response = apiService.fetchKa10064(market, stkCd);
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return LookupResult.empty(LookupStatus.API_EMPTY);
            }
            var recent = response.getItems().stream()
                    .filter(item -> item.getTime() != null)
                    .sorted((left, right) -> right.getTime().compareTo(left.getTime()))
                    .limit(3)
                    .toList();
            if (recent.isEmpty()) return LookupResult.empty(LookupStatus.API_EMPTY);

            var latest = recent.getFirst();
            long foreign = parseLong(latest.getForeignInvestor());
            long institution = parseLong(latest.getInstitution());
            double recentCombinedAverage = recent.stream()
                    .mapToLong(item -> parseLong(item.getForeignInvestor())
                            + parseLong(item.getInstitution()))
                    .average()
                    .orElse(0.0);
            long latestCombined = foreign + institution;
            var oldest = recent.getLast();
            long oldestForeign = parseLong(oldest.getForeignInvestor());
            long oldestInstitution = parseLong(oldest.getInstitution());
            long foreignSlope = foreign - oldestForeign;
            long institutionSlope = institution - oldestInstitution;
            long combinedSlope = foreignSlope + institutionSlope;
            long latestDelta = 0L;
            boolean recentReversal = false;
            String recentReversalDirection = "NONE";
            if (recent.size() >= 2) {
                var previous = recent.get(1);
                long previousCombined = parseLong(previous.getForeignInvestor())
                        + parseLong(previous.getInstitution());
                latestDelta = latestCombined - previousCombined;
                if (recent.size() >= 3) {
                    var prior = recent.get(2);
                    long priorCombined = parseLong(prior.getForeignInvestor())
                            + parseLong(prior.getInstitution());
                    long previousDelta = previousCombined - priorCombined;
                    recentReversal = latestDelta != 0 && previousDelta != 0
                            && Long.signum(latestDelta) != Long.signum(previousDelta);
                    if (recentReversal) recentReversalDirection = latestDelta > 0 ? "UP" : "DOWN";
                }
            }
            boolean clearlyNegative = recent.size() >= 2
                    && latestCombined < 0
                    && recentCombinedAverage < 0;
            InvestorFlowSnapshot snapshot = new InvestorFlowSnapshot(
                    latest.getTime(), foreign, institution, latestCombined,
                    recentCombinedAverage, recent.size(), clearlyNegative,
                    combinedSlope, foreignSlope, institutionSlope, latestDelta,
                    recentReversal, recentReversalDirection);
            investorFlowCache.put(cacheKey, new CachedInvestorFlow(snapshot, now));
            return LookupResult.of(snapshot, LookupStatus.REMOTE_SUCCESS);
        } catch (Exception e) {
            log.debug("[REST fallback] ka10064 failed stkCd={} cause={}", stkCd, e.getMessage());
            return LookupResult.empty(LookupStatus.API_ERROR);
        }
    }

    public Optional<ViHistorySnapshot> fetchViHistory(String market, String stkCd) {
        return fetchViHistoryDetailed(market, stkCd).value();
    }

    /** ka10054 history shares the same process-wide cache and minute call budget. */
    public LookupResult<ViHistorySnapshot> fetchViHistoryDetailed(String market, String stkCd) {
        stkCd = StockCodeNormalizer.normalize(stkCd);
        String cacheKey = market + ":" + stkCd;
        long now = nowMs.getAsLong();
        CachedViHistory cached = viHistoryCache.get(cacheKey);
        if (cached != null && now - cached.cachedAtMs <= cacheTtlMs) {
            return LookupResult.of(cached.snapshot, LookupStatus.CACHE_HIT);
        }
        if (!reserveCall(now)) {
            log.debug("[REST fallback] budget exhausted; ka10054 skipped stkCd={}", stkCd);
            return LookupResult.empty(LookupStatus.BUDGET_EXHAUSTED);
        }
        try {
            var response = apiService.fetchKa10054(market, stkCd);
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return LookupResult.empty(LookupStatus.API_EMPTY);
            }
            String targetStkCd = stkCd;
            var latest = response.getItems().stream()
                    .filter(item -> targetStkCd.equals(item.getStkCd()))
                    .max((left, right) -> viSortKey(left).compareTo(viSortKey(right)))
                    .orElse(null);
            if (latest == null) return LookupResult.empty(LookupStatus.API_EMPTY);

            String type = latest.getApplicationType();
            boolean dynamic = containsType(type, "동적", "2", "3");
            boolean staticVi = containsType(type, "정적", "1", "3");
            double activationPrice = parseOrZero(latest.getActivationPrice());
            double dynamicReference = parseOrZero(latest.getDynamicReferencePrice());
            double staticReference = parseOrZero(latest.getStaticReferencePrice());
            double dynamicDeviation = parseOrZero(latest.getDynamicDeviationRate());
            double staticDeviation = parseOrZero(latest.getStaticDeviationRate());
            boolean referenceConsistent = (!dynamic || referenceMatches(
                    activationPrice, dynamicReference, latest.getDynamicDeviationRate()))
                    && (!staticVi || referenceMatches(
                    activationPrice, staticReference, latest.getStaticDeviationRate()));
            ViHistorySnapshot snapshot = new ViHistorySnapshot(
                    latest.getReleaseTime(), latest.getActivationTime(), activationPrice,
                    type, dynamic, staticVi, dynamicReference, staticReference,
                    dynamicDeviation, staticDeviation,
                    (int) parseLong(latest.getActivationCount()),
                    referenceConsistent, latest.getExchangeType());
            viHistoryCache.put(cacheKey, new CachedViHistory(snapshot, now));
            return LookupResult.of(snapshot, LookupStatus.REMOTE_SUCCESS);
        } catch (Exception e) {
            log.debug("[REST fallback] ka10054 failed stkCd={} cause={}", stkCd, e.getMessage());
            return LookupResult.empty(LookupStatus.API_ERROR);
        }
    }

    private static String viSortKey(KiwoomApiResponses.ViActivationResponse.ViActivationItem item) {
        String release = item.getReleaseTime() != null ? item.getReleaseTime() : "";
        String activation = item.getActivationTime() != null ? item.getActivationTime() : "";
        return release + activation;
    }

    private static boolean containsType(String raw, String label, String... numericTypes) {
        if (raw == null) return false;
        if (raw.contains(label)) return true;
        for (String numericType : numericTypes) if (raw.equals(numericType)) return true;
        return false;
    }

    private static double parseOrZero(String raw) {
        Double value = parse(raw);
        return value != null ? value : 0.0;
    }

    private static boolean referenceMatches(double activationPrice, double referencePrice,
                                            String rawDeclaredDeviation) {
        if (activationPrice <= 0 || referencePrice <= 0) return false;
        Double declaredDeviation = parse(rawDeclaredDeviation);
        if (declaredDeviation == null) return true;
        double calculatedDeviation = (activationPrice - referencePrice) / referencePrice * 100.0;
        return Math.abs(calculatedDeviation - declaredDeviation) <= 1.0;
    }

    private boolean reserveCall(long now) {
        synchronized (budgetLock) {
            if (windowStartedAtMs == 0 || now - windowStartedAtMs >= WINDOW_MILLIS) {
                windowStartedAtMs = now;
                callsInWindow = 0;
            }
            if (callsInWindow >= callsPerMinute) return false;
            callsInWindow++;
            return true;
        }
    }

    private static Double parse(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try {
            return Double.parseDouble(raw.replace(",", "").replace("+", "").trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static long parseLong(String raw) {
        Double parsed = parse(raw);
        return parsed != null ? parsed.longValue() : 0L;
    }

    public record StrengthSnapshot(String observedAt, Double current, Double fiveMinute,
                                   Double twentyMinute, Double sixtyMinute) {
        public Double effectiveStrength() {
            return fiveMinute != null && fiveMinute > 0 ? fiveMinute
                    : current != null && current > 0 ? current : null;
        }
    }

    public record InvestorFlowSnapshot(String observedAt, long foreignAmount,
                                       long institutionAmount, long latestCombinedAmount,
                                       double recentCombinedAverage, int sampleCount,
                                       boolean clearlyNegative, long combinedSlope,
                                       long foreignSlope, long institutionSlope,
                                       long latestDelta, boolean recentReversal,
                                       String recentReversalDirection) {}

    public record ViHistorySnapshot(String releaseTime, String activationTime,
                                    double activationPrice, String applicationType,
                                    boolean dynamic, boolean staticVi,
                                    double dynamicReferencePrice, double staticReferencePrice,
                                    double dynamicDeviationRate, double staticDeviationRate,
                                    int activationCount, boolean referenceConsistent,
                                    String exchangeType) {}

    public enum LookupStatus {
        REMOTE_SUCCESS,
        CACHE_HIT,
        BUDGET_EXHAUSTED,
        API_EMPTY,
        API_ERROR
    }

    public record LookupResult<T>(Optional<T> value, LookupStatus status) {
        static <T> LookupResult<T> of(T value, LookupStatus status) {
            return new LookupResult<>(Optional.of(value), status);
        }

        static <T> LookupResult<T> empty(LookupStatus status) {
            return new LookupResult<>(Optional.empty(), status);
        }
    }

    private record CachedStrength(StrengthSnapshot snapshot, long cachedAtMs) {}
    private record CachedInvestorFlow(InvestorFlowSnapshot snapshot, long cachedAtMs) {}
    private record CachedViHistory(ViHistorySnapshot snapshot, long cachedAtMs) {}
}
