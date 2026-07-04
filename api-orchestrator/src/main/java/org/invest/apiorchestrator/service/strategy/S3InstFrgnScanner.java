package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Component
@RequiredArgsConstructor
public class S3InstFrgnScanner implements StrategyScanner {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;

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

                double volRatio = calcVolRatio(stkCd);
                if (volRatio < 1.5) {
                    continue;
                }

                long netBuyAmt = parseLong(item.getNetBuyAmt());
                double score = netBuyAmt / 1_000_000.0 + volRatio * 5;

                var tick = redisService.getTickData(stkCd);
                double curPrice = tick.isPresent() ? parseDouble(tick.get(), "cur_prc") : 0.0;

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
                        .build());
            }

            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5)
                    .collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S3] scanner failed: {}", e.getMessage());
            return Collections.emptyList();
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
