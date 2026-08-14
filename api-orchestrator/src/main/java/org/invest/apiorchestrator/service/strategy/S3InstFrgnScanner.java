package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.KiwoomRestFallbackService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Component
@RequiredArgsConstructor
public class S3InstFrgnScanner implements StrategyScanner {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;
    private final KiwoomRestFallbackService restFallbackService;

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S3_INST_FRGN;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        String market = context.market();
        log.info("[S3] inst/frgn scanner started market={}", market);
        try {
            var intradayResp = apiService.post(
                    "ka10063", "/api/dostk/mrkcond",
                    StrategyRequests.IntradayInvestorRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.IntradayInvestorResponse.class);

            if (intradayResp.getItems() == null) {
                return Collections.emptyList();
            }

            var contResp = apiService.post(
                    "ka10131", "/api/dostk/frgnistt",
                    StrategyRequests.InstFrgnContinuousRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.InstFrgnContinuousResponse.class);

            Map<String, Integer> contMap = contResp.getItems() == null ? Collections.emptyMap()
                    : contResp.getItems().stream()
                    .filter(c -> c.getStkCd() != null)
                    .collect(Collectors.toMap(
                            KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem::getStkCd,
                            c -> {
                                int days = parseInt(c.getContDtCnt());
                                return days > 0 ? days : 1;
                            },
                            (a, b) -> a
                    ));

            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : intradayResp.getItems()) {
                String stkCd = item.getStkCd();
                if (!contMap.containsKey(stkCd)) {
                    continue;
                }

                var freshTick = redisService.getFreshTick(
                        stkCd, RedisMarketDataService.ENTRY_TICK_POLICY);
                if (!freshTick.usable() || freshTick.value() == null) {
                    continue;
                }
                double volRatio = calcVolRatio(freshTick.value());
                if (volRatio < 1.5) {
                    continue;
                }

                long netBuyAmt = parseLong(item.getNetBuyAmt());
                double score = netBuyAmt / 1_000_000.0 + volRatio * 5;

                double curPrice = parseDouble(freshTick.value(), "cur_prc");
                if (curPrice <= 0) {
                    continue;
                }
                Map<String, Object> extra = new LinkedHashMap<>();
                extra.put("tick_freshness_state", freshTick.state().name());
                extra.put("tick_freshness_source", freshTick.source());
                extra.put("tick_freshness_age_ms", freshTick.age() != null ? freshTick.age().toMillis() : null);

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S3_INST_FRGN)
                        .signalScore(round(score))
                        .netBuyAmt(netBuyAmt)
                        .volRatio(round(volRatio))
                        .continuousDays(contMap.get(stkCd))
                        .marketType(market)
                        .entryType("inst_frgn_1min")
                        .targetPct(3.5)
                        .target2Pct(5.0)
                        .stopPct(-2.0)
                        .tp1Price(curPrice > 0 ? round(curPrice * 1.06) : null)
                        .tp2Price(curPrice > 0 ? round(curPrice * 1.10) : null)
                        .slPrice(curPrice > 0 ? round(curPrice * 0.97) : null)
                        .extra(extra)
                        .build());
            }

            List<TradingSignalDto> topCandidates = results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5)
                    .collect(Collectors.toList());
            for (TradingSignalDto signal : topCandidates) {
                var lookup = restFallbackService.fetchInvestorFlowDetailed(market, signal.getStkCd());
                Map<String, Object> extra = signal.getExtra();
                extra.put("strategy_evaluation_owner", "python");
                extra.put("java_enrichment_mode", "live_feature_transport");
                extra.put("s3_investor_flow_source", lookup.status().name());
                lookup.value().ifPresent(flow -> {
                    extra.put("s3_flow_observed_at", flow.observedAt());
                    extra.put("s3_foreign_amount", flow.foreignAmount());
                    extra.put("s3_institution_amount", flow.institutionAmount());
                    extra.put("s3_latest_combined_amount", flow.latestCombinedAmount());
                    extra.put("s3_flow_sample_count", flow.sampleCount());
                    extra.put("s3_flow_combined_slope", flow.combinedSlope());
                    extra.put("s3_flow_foreign_slope", flow.foreignSlope());
                    extra.put("s3_flow_institution_slope", flow.institutionSlope());
                    extra.put("s3_flow_latest_delta", flow.latestDelta());
                    extra.put("s3_flow_recent_reversal", flow.recentReversal());
                    extra.put("s3_flow_recent_reversal_direction", flow.recentReversalDirection());
                });
            }
            return topCandidates;
        } catch (Exception e) {
            log.error("[S3] scanner failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    private double calcVolRatio(Map<Object, Object> tick) {
        double cached = parseDouble(tick, "vol_ratio");
        return cached > 0 ? cached : 1.5;
    }

    private double parseDouble(Map<Object, Object> map, String key) {
        try {
            return Double.parseDouble(map.getOrDefault(key, "0").toString()
                    .replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private long parseLong(String value) {
        try {
            return value == null ? 0 : Long.parseLong(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private int parseInt(String value) {
        try {
            return value == null ? 999 : Integer.parseInt(value.replace(",", ""));
        } catch (Exception e) {
            return 999;
        }
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
