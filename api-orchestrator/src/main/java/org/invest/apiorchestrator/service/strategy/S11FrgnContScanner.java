package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.stereotype.Component;

import java.time.format.DateTimeFormatter;
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
public class S11FrgnContScanner implements StrategyScanner {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;

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

            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : contResp.getItems()) {
                String stkCd = item.getStkCd();
                double dm1 = parseDoubleSign(item.getDm1());
                double dm2 = parseDoubleSign(item.getDm2());
                double dm3 = parseDoubleSign(item.getDm3());
                if (dm1 <= 0 || dm2 <= 0 || dm3 <= 0) {
                    continue;
                }

                InvestorFlow investorFlow = fetchInvestorFlow(stkCd);
                if (investorFlow.hasData() && investorFlow.foreignAmount < 0 && investorFlow.institutionAmount < 0) {
                    continue;
                }

                double total = parseDoubleSign(item.getTot());
                double limitExhRt = parseDouble(item.getLimitExhRt());
                double volRatio = calcVolRatio(stkCd);
                double cntrStr = redisService.getAvgCntrStrength(stkCd, 5);

                double score = 15.0
                        + Math.min(total / 100_000.0, 20.0)
                        + limitExhRt * 0.5
                        + volRatio * 3.0
                        + Math.max(cntrStr - 100, 0) * 0.2
                        + investorFlow.scoreBonus();

                var tick = redisService.getTickData(stkCd);
                double curPrice = tick.isPresent() ? parseDouble(tick.get(), "cur_prc") : 0.0;
                Map<String, Object> extra = new LinkedHashMap<>();
                if (investorFlow.hasData()) {
                    extra.put("s11_foreign_amount", investorFlow.foreignAmount);
                    extra.put("s11_institution_amount", investorFlow.institutionAmount);
                    extra.put("s11_individual_amount", investorFlow.individualAmount);
                }

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S11_FRGN_CONT)
                        .signalScore(round(score))
                        .continuousDays(3)
                        .volRatio(round(volRatio))
                        .cntrStrength(round(cntrStr))
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
                        .build());
            }

            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5)
                    .collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S11] scanner failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    private InvestorFlow fetchInvestorFlow(String stkCd) {
        try {
            String today = KstClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
            var response = apiService.fetchKa10061(StrategyRequests.InvestorOrgTotalRequest.builder()
                    .stkCd(stkCd)
                    .strtDt(today)
                    .endDt(today)
                    .build());
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return InvestorFlow.empty();
            }
            var item = response.getItems().get(0);
            return new InvestorFlow(
                    parseLong(item.getFrgnrInvsr()),
                    parseLong(item.getOrgn()),
                    parseLong(item.getIndInvsr())
            );
        } catch (Exception ignored) {
            return InvestorFlow.empty();
        }
    }

    private double calcVolRatio(String stkCd) {
        var tickOpt = redisService.getTickData(stkCd);
        if (tickOpt.isEmpty()) {
            return 1.5;
        }
        double cached = parseDouble(tickOpt.get(), "vol_ratio");
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

    private long parseLong(String value) {
        try {
            return value == null ? 0 : Long.parseLong(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private record InvestorFlow(long foreignAmount, long institutionAmount, long individualAmount) {
        static InvestorFlow empty() {
            return new InvestorFlow(0, 0, 0);
        }

        boolean hasData() {
            return foreignAmount != 0 || institutionAmount != 0 || individualAmount != 0;
        }

        double scoreBonus() {
            double flow = Math.max(0, foreignAmount) + Math.max(0, institutionAmount);
            return Math.min(12.0, flow / 10_000.0);
        }
    }
}
