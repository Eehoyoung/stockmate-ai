package org.invest.apiorchestrator.service.strategy;

import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Component
public class S13BoxBreakoutScanner extends DailyStrategySupport implements StrategyScanner {

    public S13BoxBreakoutScanner(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        super(apiService, redisService, stockMasterRepository);
    }

    @Override
    public TradingSignal.StrategyType type() {
        return TradingSignal.StrategyType.S13_BOX_BREAKOUT;
    }

    @Override
    public List<TradingSignalDto> scan(StrategyScanContext context) {
        List<TradingSignalDto> results = new ArrayList<>();
        for (String stkCd : context.candidates()) {
            try {
                DailySeries series = fetchDailySeries(stkCd, 22);
                if (series == null || series.closes()[0] <= 0) {
                    continue;
                }
                double[] highs = series.highs();
                double[] lows = series.lows();
                double[] closes = series.closes();
                double[] vols = series.vols();

                double boxHigh = 0;
                for (int i = 1; i <= 20 && i < series.size(); i++) {
                    boxHigh = Math.max(boxHigh, highs[i]);
                }
                if (boxHigh <= 0 || closes[0] <= boxHigh * 1.002) {
                    continue;
                }

                double fluRt = closes[1] > 0 ? (closes[0] - closes[1]) / closes[1] * 100 : 0;
                if (fluRt < 1.0 || fluRt > 15.0) {
                    continue;
                }

                double volMa20 = maAvg(vols, 1, 20);
                double volRatio = volMa20 > 0 ? vols[0] / volMa20 : 1.0;
                if (volRatio < 2.0) {
                    continue;
                }

                double bandwidth = calcBollingerBandwidth(closes, 20);
                boolean squeeze = bandwidth > 0 && bandwidth < 6.0;
                double mfi = calcMfiLatest(highs, lows, closes, vols, 14);
                boolean mfiConfirmed = mfi > 55;
                double strength = redisService.getAvgCntrStrength(stkCd, 5);
                SectorFlow sectorFlow = fetchSectorFlow(stkCd);
                MarketBreadth marketBreadth = fetchMarketBreadthForStock(stkCd);

                double score = fluRt * 2 + volRatio * 3
                        + (squeeze ? 15 : 0)
                        + (mfiConfirmed ? 10 : 0)
                        + Math.max(strength - 100, 0) * 0.2
                        + sectorFlow.scoreBonus()
                        + marketBreadth.scoreBonus();

                double boxLow = lows[1];
                for (int i = 2; i <= 10 && i < series.size(); i++) {
                    boxLow = Math.min(boxLow, lows[i]);
                }
                double boxHeight = Math.max(boxHigh - boxLow, closes[0] * 0.03);
                double tp1 = round(closes[0] + boxHeight);
                double tp2 = round(closes[0] + boxHeight * 2.0);
                double sl = round(boxHigh * 0.99);
                double stopPct = round((sl - closes[0]) / closes[0] * 100);

                Map<String, Object> extra = new LinkedHashMap<>();
                if (sectorFlow.present()) {
                    extra.put("sector_code", sectorFlow.sectorCode());
                    extra.put("sector_name", sectorFlow.sectorName());
                    extra.put("sector_foreign_net", sectorFlow.foreignNet());
                    extra.put("sector_institution_net", sectorFlow.institutionNet());
                    extra.put("sector_flu_rt", sectorFlow.fluRt());
                    extra.put("sector_score_bonus", round(sectorFlow.scoreBonus()));
                }
                if (marketBreadth.present()) {
                    extra.put("market_breadth_code", marketBreadth.marketCode());
                    extra.put("market_breadth_name", marketBreadth.marketName());
                    extra.put("market_breadth_flu_rt", marketBreadth.fluRt());
                    extra.put("market_breadth_rising", marketBreadth.rising());
                    extra.put("market_breadth_falling", marketBreadth.falling());
                    extra.put("market_breadth_score_bonus", round(marketBreadth.scoreBonus()));
                }

                results.add(TradingSignalDto.builder()
                        .stkCd(stkCd)
                        .stkNm(resolveStkNm(stkCd))
                        .strategy(type())
                        .signalScore(round(score))
                        .entryPrice(closes[0])
                        .gapPct(round(fluRt))
                        .volRatio(round(volRatio))
                        .cntrStrength(round(strength))
                        .entryType("box_breakout_daily")
                        .holdingDays("3~7 trading days")
                        .targetPct(round((tp1 - closes[0]) / closes[0] * 100))
                        .target2Pct(round((tp2 - closes[0]) / closes[0] * 100))
                        .stopPct(stopPct)
                        .tp1Price(tp1)
                        .tp2Price(tp2)
                        .slPrice(sl)
                        .extra(extra)
                        .build());
            } catch (Exception e) {
                log.debug("[S13] {} processing failed: {}", stkCd, e.getMessage());
            }
        }
        return results.stream()
                .sorted(Comparator.comparingDouble(TradingSignalDto::getSignalScore).reversed())
                .limit(5)
                .collect(Collectors.toList());
    }
}
