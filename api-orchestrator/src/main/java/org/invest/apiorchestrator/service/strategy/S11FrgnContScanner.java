package org.invest.apiorchestrator.service.strategy;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.KiwoomRestFallbackService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class S11FrgnContScanner implements StrategyScanner {

    static final int DEFAULT_ENRICHMENT_TOP_N = 5;

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;
    private final KiwoomRestFallbackService restFallbackService;
    private final int enrichmentTopN;

    @Autowired
    public S11FrgnContScanner(KiwoomApiService apiService,
                              RedisMarketDataService redisService,
                              KiwoomRestFallbackService restFallbackService,
                              @Value("${strategy.s11.enrichment-top-n:5}") int enrichmentTopN) {
        this.apiService = apiService;
        this.redisService = redisService;
        this.restFallbackService = restFallbackService;
        this.enrichmentTopN = enrichmentTopN > 0 ? enrichmentTopN : DEFAULT_ENRICHMENT_TOP_N;
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S11_FRGN_CONT;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        String market = context.market();
        log.info("[S11] foreign continuation scanner started market={}", market);
        try {
            var contResp = apiService.fetchKa10035(
                    StrategyRequests.FrgnContNettrdRequest.builder()
                            .mrktTp(market)
                            .trdeTp("2")
                            .baseDtTp("0")
                            .build());
            if (contResp == null || contResp.getItems() == null) {
                return Collections.emptyList();
            }

            List<Candidate> primaryCandidates = new ArrayList<>();
            for (var item : contResp.getItems()) {
                double dm1 = parseDoubleSign(item.getDm1());
                double dm2 = parseDoubleSign(item.getDm2());
                double dm3 = parseDoubleSign(item.getDm3());
                if (dm1 <= 0 || dm2 <= 0 || dm3 <= 0) continue;

                String stkCd = item.getStkCd();
                double total = parseDoubleSign(item.getTot());
                double limitExhRt = parseDouble(item.getLimitExhRt());
                var freshTick = redisService.getFreshTick(
                        stkCd, RedisMarketDataService.ENTRY_TICK_POLICY);
                Map<Object, Object> tick = freshTick.usable() && freshTick.value() != null
                        ? freshTick.value() : Collections.emptyMap();
                double cachedVolRatio = parseDouble(tick, "vol_ratio");
                double volRatio = cachedVolRatio > 0 ? cachedVolRatio : 1.5;
                var freshStrength = redisService.getFreshStrength(
                        stkCd, 5, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
                double cntrStr = freshStrength.usable() && freshStrength.value() != null
                        ? freshStrength.value() : 100.0;
                double baseScore = 15.0
                        + Math.min(total / 100_000.0, 20.0)
                        + limitExhRt * 0.5
                        + volRatio * 3.0
                        + Math.max(cntrStr - 100, 0) * 0.2;
                double curPrice = parseDouble(tick, "cur_prc");
                primaryCandidates.add(new Candidate(stkCd, item.getStkNm(), baseScore,
                        volRatio, cntrStr, curPrice,
                        freshTick.state().name(), freshStrength.state().name()));
            }

            List<Candidate> topCandidates = primaryCandidates.stream()
                    .sorted(Comparator.comparingDouble(Candidate::baseScore).reversed())
                    .limit(enrichmentTopN)
                    .toList();

            List<TradingSignalDto> results = new ArrayList<>();
            for (Candidate candidate : topCandidates) {
                var lookup = restFallbackService.fetchInvestorFlowDetailed(market, candidate.stkCd());
                var flow = lookup.value().orElse(null);
                double score = candidate.baseScore();
                Map<String, Object> extra = new LinkedHashMap<>();
                extra.put("strategy_evaluation_owner", "python");
                extra.put("java_enrichment_mode", "live_feature_transport");
                extra.put("s11_tick_freshness", candidate.tickFreshness());
                extra.put("s11_strength_freshness", candidate.strengthFreshness());
                extra.put("s11_investor_flow_source", lookup.status().name());
                if (flow != null) {
                    extra.put("s11_flow_observed_at", flow.observedAt());
                    extra.put("s11_foreign_amount", flow.foreignAmount());
                    extra.put("s11_institution_amount", flow.institutionAmount());
                    extra.put("s11_latest_combined_amount", flow.latestCombinedAmount());
                    extra.put("s11_recent_combined_average", round(flow.recentCombinedAverage()));
                    extra.put("s11_flow_sample_count", flow.sampleCount());
                    extra.put("s11_flow_clearly_negative", flow.clearlyNegative());
                    extra.put("s11_flow_combined_slope", flow.combinedSlope());
                    extra.put("s11_flow_foreign_slope", flow.foreignSlope());
                    extra.put("s11_flow_institution_slope", flow.institutionSlope());
                    extra.put("s11_flow_latest_delta", flow.latestDelta());
                    extra.put("s11_flow_recent_reversal", flow.recentReversal());
                    extra.put("s11_flow_recent_reversal_direction", flow.recentReversalDirection());
                }

                results.add(toSignal(candidate, market, score, extra));
            }
            results.sort(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed());
            return results;
        } catch (Exception e) {
            log.error("[S11] scanner failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    private TradingSignalDto toSignal(Candidate candidate, String market, double score,
                                      Map<String, Object> extra) {
        double curPrice = candidate.curPrice();
        return TradingSignalDto.builder()
                .stkCd(candidate.stkCd())
                .stkNm(candidate.stkNm())
                .strategy(TradingSignal.StrategyType.S11_FRGN_CONT)
                .signalScore(round(score))
                .continuousDays(3)
                .volRatio(round(candidate.volRatio()))
                .cntrStrength(round(candidate.cntrStrength()))
                .marketType(market)
                .entryType("foreign_continuation_1min")
                .holdingDays("5~10 trading days")
                .targetPct(9.0)
                .target2Pct(14.0)
                .stopPct(-5.0)
                .tp1Price(curPrice > 0 ? round(curPrice * 1.09) : null)
                .tp2Price(curPrice > 0 ? round(curPrice * 1.14) : null)
                .slPrice(curPrice > 0 ? round(curPrice * 0.95) : null)
                .extra(extra)
                .build();
    }

    private double parseDouble(Map<Object, Object> map, String key) {
        try {
            return Double.parseDouble(map.getOrDefault(key, "0").toString()
                    .replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double parseDouble(String value) {
        try {
            return value == null ? 0 : Double.parseDouble(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double parseDoubleSign(String value) {
        try {
            return value == null ? 0 : Double.parseDouble(value.replace(",", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private record Candidate(String stkCd, String stkNm, double baseScore,
                             double volRatio, double cntrStrength, double curPrice,
                             String tickFreshness, String strengthFreshness) {}
}
