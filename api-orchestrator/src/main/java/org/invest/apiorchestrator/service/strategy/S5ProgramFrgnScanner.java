package org.invest.apiorchestrator.service.strategy;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
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
import java.util.Set;
import java.util.stream.Stream;
import java.util.stream.Collectors;

@Slf4j
@Component
@RequiredArgsConstructor
public class S5ProgramFrgnScanner implements StrategyScanner {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S5_PROG_FRGN;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        String market = context.market();
        log.info("[S5] program/frgn scanner started market={}", market);
        try {
            var progResp = apiService.post(
                    "ka90003", "/api/dostk/stkinfo",
                    StrategyRequests.ProgramNetBuyRequest.builder().mrktTp(toProgramMarket(market)).build(),
                    KiwoomApiResponses.ProgramNetBuyResponse.class);

            var frgnResp = apiService.post(
                    "ka90009", "/api/dostk/rkinfo",
                    StrategyRequests.FrgnInstUpperRequest.builder().mrktTp(market).build(),
                    KiwoomApiResponses.FrgnInstUpperResponse.class);

            if (progResp.getItems() == null || frgnResp.getItems() == null) {
                return Collections.emptyList();
            }

            Set<String> frgnSet = frgnResp.getItems().stream()
                    .flatMap(item -> Stream.of(item.getForNetprpsStkCd(), item.getOrgnNetprpsStkCd()))
                    .filter(code -> code != null && !code.isBlank())
                    .collect(Collectors.toSet());

            ProgramMarketFlow marketFlow = fetchMarketProgramFlow(market);
            List<TradingSignalDto> results = new ArrayList<>();
            for (var item : progResp.getItems()) {
                String stkCd = item.getStkCd();
                if (!frgnSet.contains(stkCd)) {
                    continue;
                }

                long netBuyAmt = parseLong(item.getNetBuyAmt());
                double score = netBuyAmt / 1_000_000.0;
                StockProgramFlow stockFlow = fetchStockProgramFlow(stkCd);
                if (stockFlow.hasData() && stockFlow.netAmount < 0) {
                    continue;
                }
                score += marketFlow.scoreBonus();
                score += stockFlow.scoreBonus();

                var freshTick = redisService.getFreshTick(
                        stkCd, RedisMarketDataService.ENTRY_TICK_POLICY);
                if (!freshTick.usable() || freshTick.value() == null) {
                    continue;
                }
                double curPrice = parseDouble(freshTick.value(), "cur_prc");
                if (curPrice <= 0) {
                    continue;
                }
                Map<String, Object> extra = new LinkedHashMap<>();
                extra.put("tick_freshness_state", freshTick.state().name());
                extra.put("tick_freshness_source", freshTick.source());
                extra.put("tick_freshness_age_ms", freshTick.age() != null ? freshTick.age().toMillis() : null);
                if (marketFlow.hasData()) {
                    extra.put("program_market_net_amount", marketFlow.netAmount);
                    extra.put("program_market_net_qty", marketFlow.netQty);
                }
                if (stockFlow.hasData()) {
                    extra.put("program_stock_net_amount", stockFlow.netAmount);
                    extra.put("program_stock_net_qty", stockFlow.netQty);
                }

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(item.getStkNm())
                        .strategy(TradingSignal.StrategyType.S5_PROG_FRGN)
                        .signalScore(round(score))
                        .netBuyAmt(netBuyAmt)
                        .marketType(market)
                        .entryType("program_frgn_1min")
                        .targetPct(6.0)
                        .target2Pct(9.0)
                        .stopPct(-3.0)
                        .tp1Price(curPrice > 0 ? round(curPrice * 1.06) : null)
                        .tp2Price(curPrice > 0 ? round(curPrice * 1.09) : null)
                        .slPrice(curPrice > 0 ? round(curPrice * 0.97) : null)
                        .extra(extra)
                        .build());
            }

            return results.stream()
                    .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                    .limit(5)
                    .collect(Collectors.toList());
        } catch (Exception e) {
            log.error("[S5] scanner failed: {}", e.getMessage());
            return Collections.emptyList();
        }
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

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private ProgramMarketFlow fetchMarketProgramFlow(String market) {
        try {
            var response = apiService.fetchKa90005(StrategyRequests.ProgramTrendRequest.builder()
                    .date(KstClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd")))
                    .mrktTp(toProgramMarket(market))
                    .build());
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return ProgramMarketFlow.empty();
            }
            var latest = response.getItems().get(0);
            return new ProgramMarketFlow(
                    parseLong(latest.getAllNetprps()),
                    parseLong(latest.getDfrtTrdeNetprpsQty())
            );
        } catch (Exception ignored) {
            return ProgramMarketFlow.empty();
        }
    }

    private StockProgramFlow fetchStockProgramFlow(String stkCd) {
        try {
            var response = apiService.fetchKa90008(StrategyRequests.StockProgramTrendRequest.builder()
                    .stkCd(stkCd)
                    .date(KstClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd")))
                    .build());
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return StockProgramFlow.empty();
            }
            var latest = response.getItems().get(0);
            return new StockProgramFlow(
                    parseLong(latest.getDfrtTrdeNetprps()),
                    parseLong(latest.getDfrtTrdeNetprpsQty())
            );
        } catch (Exception ignored) {
            return StockProgramFlow.empty();
        }
    }

    private String toProgramMarket(String market) {
        return switch (String.valueOf(market)) {
            case "001" -> "P00101";
            case "101" -> "P10102";
            default -> "P00101";
        };
    }

    private record ProgramMarketFlow(long netAmount, long netQty) {
        static ProgramMarketFlow empty() {
            return new ProgramMarketFlow(0, 0);
        }

        boolean hasData() {
            return netAmount != 0 || netQty != 0;
        }

        double scoreBonus() {
            return netAmount > 0 ? Math.min(8.0, netAmount / 10_000_000.0) : 0.0;
        }
    }

    private record StockProgramFlow(long netAmount, long netQty) {
        static StockProgramFlow empty() {
            return new StockProgramFlow(0, 0);
        }

        boolean hasData() {
            return netAmount != 0 || netQty != 0;
        }

        double scoreBonus() {
            double amountBonus = netAmount > 0 ? Math.min(10.0, netAmount / 1_000_000.0) : 0.0;
            double qtyBonus = netQty > 0 ? Math.min(5.0, netQty / 10_000.0) : 0.0;
            return amountBonus + qtyBonus;
        }
    }
}
