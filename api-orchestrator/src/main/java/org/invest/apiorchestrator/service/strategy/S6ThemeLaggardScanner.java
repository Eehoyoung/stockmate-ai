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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Component
@RequiredArgsConstructor
public class S6ThemeLaggardScanner implements StrategyScanner {

    private final KiwoomApiService apiService;
    private final RedisMarketDataService redisService;

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S6_THEME_LAGGARD;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        log.info("[S6] theme laggard scanner started");
        List<TradingSignalDto> results = new ArrayList<>();
        try {
            MarketBreadth marketBreadth = fetchMarketBreadth(context.market());
            var themeResp = apiService.post(
                    "ka90001", "/api/dostk/thme",
                    StrategyRequests.ThemeGroupRequest.builder().build(),
                    KiwoomApiResponses.ThemeGroupResponse.class);

            if (themeResp.getItems() == null) {
                return Collections.emptyList();
            }

            List<KiwoomApiResponses.ThemeGroupResponse.ThemeGroupItem> topThemes = themeResp.getItems()
                    .stream()
                    .limit(5)
                    .collect(Collectors.toList());

            for (var theme : topThemes) {
                double themeFluRt = parseDoubleStr(theme.getFluRt());
                if (themeFluRt < 2.0) {
                    continue;
                }

                var stockResp = apiService.post(
                        "ka90002", "/api/dostk/thme",
                        StrategyRequests.ThemeStockRequest.builder().themaGrpCd(theme.getThemaGrpCd()).build(),
                        KiwoomApiResponses.ThemeStockResponse.class);

                if (stockResp.getItems() == null) {
                    continue;
                }

                List<Double> fluRates = stockResp.getItems().stream()
                        .map(s -> parseDoubleStr(s.getFluRt()))
                        .collect(Collectors.toList());

                if (fluRates.isEmpty()) {
                    continue;
                }
                fluRates.sort(Double::compareTo);
                double p70 = fluRates.get((int) (fluRates.size() * 0.7));

                for (var stock : stockResp.getItems()) {
                    double stockFluRt = parseDoubleStr(stock.getFluRt());
                    if (stockFluRt < 0.5 || stockFluRt >= p70 || stockFluRt >= 5.0) {
                        continue;
                    }

                    double strength = redisService.getAvgCntrStrength(stock.getStkCd(), 3);
                    if (redisService.hasStrengthData(stock.getStkCd()) && strength < 120.0) {
                        continue;
                    }

                    double score = strength * 0.3 + (themeFluRt - stockFluRt) * 2 + marketBreadth.scoreBonus();
                    double target = Math.min(themeFluRt * 0.6, 5.0);

                    var tick = redisService.getTickData(stock.getStkCd());
                    double curPrice = tick.isPresent() ? parseDouble(tick.get(), "cur_prc") : 0.0;
                    double t1Pct = Math.max(Math.min(themeFluRt * 0.5, 8.0), 6.0);
                    double t2Pct = Math.max(Math.min(themeFluRt * 0.7, 11.0), 9.0);
                    Map<String, Object> extra = new LinkedHashMap<>();
                    if (marketBreadth.present()) {
                        extra.put("market_breadth_code", marketBreadth.marketCode());
                        extra.put("market_breadth_name", marketBreadth.marketName());
                        extra.put("market_breadth_flu_rt", marketBreadth.fluRt());
                        extra.put("market_breadth_rising", marketBreadth.rising());
                        extra.put("market_breadth_falling", marketBreadth.falling());
                        extra.put("market_breadth_score_bonus", round(marketBreadth.scoreBonus()));
                    }

                    results.add(TradingSignalDto.builder()
                            .stkCd(stock.getStkCd())
                            .stkNm(stock.getStkNm())
                            .strategy(TradingSignal.StrategyType.S6_THEME_LAGGARD)
                            .signalScore(round(score))
                            .themeName(theme.getThemaNm())
                            .gapPct(round(stockFluRt))
                            .cntrStrength(round(strength))
                            .entryType("theme_laggard_1min")
                            .targetPct(round(target))
                            .target2Pct(round(target * 1.5))
                            .stopPct(-2.0)
                            .tp1Price(curPrice > 0 ? round(curPrice * (1.0 + t1Pct / 100.0)) : null)
                            .tp2Price(curPrice > 0 ? round(curPrice * (1.0 + t2Pct / 100.0)) : null)
                            .slPrice(curPrice > 0 ? round(curPrice * 0.97) : null)
                            .extra(extra)
                            .build());
                }
            }
        } catch (Exception e) {
            log.error("[S6] scanner failed: {}", e.getMessage());
        }
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5)
                .collect(Collectors.toList());
    }

    private double parseDouble(Map<Object, Object> map, String key) {
        try {
            return Double.parseDouble(map.getOrDefault(key, "0").toString()
                    .replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private double parseDoubleStr(String value) {
        try {
            return value == null ? 0 : Double.parseDouble(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    private MarketBreadth fetchMarketBreadth(String market) {
        try {
            String code = normalizeMarket(market);
            if (code.isEmpty()) {
                return MarketBreadth.empty();
            }
            var response = apiService.fetchKa20003(StrategyRequests.AllSectorIndexRequest.builder()
                    .indsCd(code)
                    .build());
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return MarketBreadth.empty();
            }
            var item = response.getItems().stream()
                    .filter(i -> code.equals(i.getStkCd()))
                    .findFirst()
                    .orElse(response.getItems().get(0));
            double fluRt = parseDoubleStr(item.getFluRt());
            double rising = parseDoubleStr(item.getRising());
            double falling = parseDoubleStr(item.getFall());
            double breadth = rising - falling;
            double bonus = (fluRt > 0 ? Math.min(3.0, fluRt * 0.4) : Math.max(-3.0, fluRt * 0.3))
                    + (breadth > 0 ? Math.min(3.0, breadth / 50.0) : Math.max(-3.0, breadth / 50.0));
            return new MarketBreadth(item.getStkCd(), item.getStkNm(), fluRt, rising, falling, bonus);
        } catch (Exception ignored) {
            return MarketBreadth.empty();
        }
    }

    private String normalizeMarket(String value) {
        if (value == null) {
            return "";
        }
        String text = value.trim().toUpperCase();
        if (text.equals("001") || text.contains("KOSPI") || text.contains("코스피")) {
            return "001";
        }
        if (text.equals("101") || text.contains("KOSDAQ") || text.contains("코스닥")) {
            return "101";
        }
        return text;
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private record MarketBreadth(
            String marketCode,
            String marketName,
            double fluRt,
            double rising,
            double falling,
            double scoreBonus
    ) {
        static MarketBreadth empty() {
            return new MarketBreadth(null, null, 0, 0, 0, 0);
        }

        boolean present() {
            return marketCode != null || marketName != null;
        }
    }
}
