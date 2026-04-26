package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.DailyIndicators;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.domain.ViEvent;
import org.invest.apiorchestrator.domain.WsTickData;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.DailyIndicatorsRepository;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.repository.ViEventRepository;
import org.invest.apiorchestrator.repository.WsTickDataRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.util.KstClock;
import org.invest.apiorchestrator.util.MarketTimeUtil;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataPersistenceScheduler {

    private final StringRedisTemplate redis;
    private final WsTickDataRepository wsTickDataRepository;
    private final ViEventRepository viEventRepository;
    private final DailyIndicatorsRepository dailyIndicatorsRepository;
    private final TradingSignalRepository tradingSignalRepository;
    private final StockMasterRepository stockMasterRepository;
    private final KiwoomApiService kiwoomApiService;

    @Scheduled(fixedDelay = 60_000, initialDelay = 120_000)
    @Transactional
    public void persistWsSnapshots() {
        if (!MarketTimeUtil.isTradingActive()) {
            return;
        }
        if (isEventWriterActive()) {
            return;
        }
        Set<String> codes = collectTrackedCodes();
        if (codes.isEmpty()) {
            return;
        }

        List<WsTickData> batch = new ArrayList<>();
        for (String stkCd : codes) {
            Map<Object, Object> tick = redis.opsForHash().entries("ws:tick:" + stkCd);
            if (!tick.isEmpty()) {
                batch.add(WsTickData.builder()
                        .stkCd(stkCd)
                        .curPrc(_d(tick.get("cur_prc")))
                        .predPre(_d(tick.get("pred_pre")))
                        .fluRt(_d(tick.get("flu_rt")))
                        .accTrdeQty(_l(tick.get("acc_trde_qty")))
                        .accTrdePrica(_l(tick.get("acc_trde_prica")))
                        .cntrStr(_d(tick.get("cntr_str")))
                        .tickType("0B")
                        .build());
            }

            Map<Object, Object> hoga = redis.opsForHash().entries("ws:hoga:" + stkCd);
            if (!hoga.isEmpty()) {
                Long totalBid = _l(hoga.get("total_buy_bid_req"));
                Long totalAsk = _l(hoga.get("total_sel_bid_req"));
                batch.add(WsTickData.builder()
                        .stkCd(stkCd)
                        .totalBidQty(totalBid)
                        .totalAskQty(totalAsk)
                        .bidAskRatio(ratio(totalBid, totalAsk))
                        .tickType("0D")
                        .build());
            }

            Map<Object, Object> expected = redis.opsForHash().entries("ws:expected:" + stkCd);
            if (!expected.isEmpty()) {
                batch.add(WsTickData.builder()
                        .stkCd(stkCd)
                        .curPrc(_d(expected.get("exp_cntr_pric")))
                        .predPre(_d(expected.get("exp_pred_pre")))
                        .fluRt(_d(expected.get("exp_flu_rt")))
                        .accTrdeQty(_l(expected.get("exp_cntr_qty")))
                        .tickType("0H")
                        .build());
            }
        }

        if (!batch.isEmpty()) {
            wsTickDataRepository.saveAll(batch);
            log.info("[Persist] ws_tick_data snapshot saved: {} rows", batch.size());
        }
    }

    @Scheduled(fixedDelay = 60_000, initialDelay = 90_000)
    @Transactional
    public void persistViSnapshots() {
        if (!MarketTimeUtil.isTradingActive()) {
            return;
        }
        if (isEventWriterActive()) {
            return;
        }
        Set<String> keys = redis.keys("vi:*");
        if (keys == null || keys.isEmpty()) {
            return;
        }

        int saved = 0;
        for (String key : keys) {
            String stkCd = key.substring("vi:".length());
            if (stkCd.isBlank()) {
                continue;
            }
            Map<Object, Object> vi = redis.opsForHash().entries(key);
            if (vi.isEmpty()) {
                continue;
            }

            String viStatus = "released".equals(String.valueOf(vi.get("status"))) ? "2" : "1";
            String viType = Optional.ofNullable(vi.get("vi_type")).map(Object::toString).orElse("");
            Double viPrice = _d(vi.get("vi_price"));
            String fingerprint = viStatus + "|" + viType + "|" + (viPrice != null ? viPrice : "");
            String markerKey = "db:vi:last:" + stkCd;
            String prev = redis.opsForValue().get(markerKey);
            if (fingerprint.equals(prev)) {
                continue;
            }

            String stkNm = redis.opsForValue().get("stk_nm:" + stkCd);
            if (stkNm == null || stkNm.isBlank()) {
                stkNm = stockMasterRepository.findByStkCd(stkCd).map(sm -> sm.getStkNm()).orElse(null);
            }

            ViEvent entity = ViEvent.builder()
                    .stkCd(stkCd)
                    .stkNm(stkNm)
                    .viType(viType)
                    .viStatus(viStatus)
                    .viPrice(viPrice)
                    .accVolume(_l(vi.get("vi_volume")))
                    .marketType(Optional.ofNullable(vi.get("mrkt_cls")).map(Object::toString).orElse(null))
                    .releasedAt("2".equals(viStatus) ? KstClock.now() : null)
                    .build();
            try {
                viEventRepository.save(entity);
            } catch (DataIntegrityViolationException e) {
                log.warn("[Persist] vi_events save skipped stkCd={} viStatus={} viType={} viPrice={} cause={}",
                        stkCd, viStatus, viType, viPrice,
                        e.getMostSpecificCause() != null ? e.getMostSpecificCause().getMessage() : e.getMessage());
                continue;
            }
            redis.opsForValue().set(markerKey, fingerprint, Duration.ofHours(12));
            saved++;
        }

        if (saved > 0) {
            log.info("[Persist] vi_events saved: {}", saved);
        }
    }

    @Scheduled(cron = "0 20 9,13 * * MON-FRI", zone = "Asia/Seoul")
    @Transactional
    public void persistDailyIndicators() {
        Set<String> codes = collectIndicatorCodes();
        if (codes.isEmpty()) {
            log.info("[Persist] daily_indicators skipped: no target codes");
            return;
        }

        LocalDate today = KstClock.today();
        int saved = 0;
        for (String stkCd : codes) {
            try {
                KiwoomApiResponses.DailyCandleResponse resp = kiwoomApiService.fetchKa10081(stkCd);
                if (resp == null || !resp.isSuccess() || resp.getCandles() == null || resp.getCandles().size() < 20) {
                    continue;
                }
                DailyIndicators computed = buildDailyIndicators(today, stkCd, resp.getCandles());
                DailyIndicators entity = dailyIndicatorsRepository.findByDateAndStkCd(today, stkCd)
                        .map(existing -> withExistingId(existing.getId(), computed))
                        .orElse(computed);
                dailyIndicatorsRepository.save(entity);
                saved++;
            } catch (Exception e) {
                log.debug("[Persist] daily_indicators failed [{}]: {}", stkCd, e.getMessage());
            }
        }
        log.info("[Persist] daily_indicators saved: {}", saved);
    }

    private Set<String> collectTrackedCodes() {
        Set<String> codes = new LinkedHashSet<>();
        addAll(codes, redis.opsForSet().members("candidates:watchlist"));
        addAll(codes, redis.opsForSet().members("candidates:watchlist:priority"));
        return codes;
    }

    private Set<String> collectIndicatorCodes() {
        Set<String> codes = new LinkedHashSet<>();
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);

        addAll(codes, redis.opsForSet().members("candidates:watchlist"));
        addAll(codes, redis.opsForSet().members("candidates:watchlist:priority"));

        tradingSignalRepository.findTodaySignals(startOfDay).stream()
                .map(TradingSignal::getStkCd)
                .filter(v -> v != null && !v.isBlank())
                .forEach(codes::add);

        tradingSignalRepository.findAllActivePositions().stream()
                .map(TradingSignal::getStkCd)
                .filter(v -> v != null && !v.isBlank())
                .forEach(codes::add);

        stockMasterRepository.findByIsActiveTrue().stream()
                .map(sm -> sm.getStkCd())
                .forEach(codes::add);
        return codes;
    }

    private boolean isEventWriterActive() {
        return "1".equals(redis.opsForValue().get("ws:db_writer:event_mode"));
    }

    private DailyIndicators buildDailyIndicators(LocalDate date, String stkCd,
                                                 List<KiwoomApiResponses.DailyCandleResponse.DailyCandleItem> candles) {
        List<Double> closes = new ArrayList<>();
        List<Double> highs = new ArrayList<>();
        List<Double> lows = new ArrayList<>();
        List<Long> volumes = new ArrayList<>();
        for (KiwoomApiResponses.DailyCandleResponse.DailyCandleItem candle : candles) {
            closes.add(_d(candle.getCurPrc(), 0.0));
            highs.add(_d(candle.getHighPric(), 0.0));
            lows.add(_d(candle.getLowPric(), 0.0));
            volumes.add(_l(candle.getTrdeQty(), 0L));
        }

        double close = closes.get(0);
        double open = _d(candles.get(0).getOpenPric(), close);
        double high = highs.get(0);
        double low = lows.get(0);
        long volume = volumes.get(0);

        Double ma5 = avg(closes, 5);
        Double ma20 = avg(closes, 20);
        Double ma60 = avg(closes, 60);
        Double ma120 = avg(closes, 120);
        Double volMa20 = avgLong(volumes, 20);
        Double volumeRatio = volMa20 != null && volMa20 > 0 ? volume / volMa20 : null;

        Double rsi14 = calcRsi(closes, 14);
        Double[] stoch = calcStochastic(closes, highs, lows, 14);
        Double[] boll = calcBollinger(closes, 20);
        Double atr14 = calcAtr(closes, highs, lows, 14);
        Double atrPct = (atr14 != null && close > 0) ? atr14 / close * 100.0 : null;
        Double[] macd = calcMacd(closes);

        Double swingHigh20 = max(highs, 20);
        Double swingLow20 = min(lows, 20);
        Double swingHigh60 = max(highs, 60);
        Double swingLow60 = min(lows, 60);
        boolean aboveMa20 = ma20 != null && close >= ma20;
        boolean newHigh52w = max(highs, Math.min(250, highs.size())) != null
                && close >= max(highs, Math.min(250, highs.size()));
        boolean goldenCross = ma5 != null && ma20 != null && closes.size() >= 21
                && ma5 >= ma20
                && avg(closes.subList(1, closes.size()), 5) != null
                && avg(closes.subList(1, closes.size()), 20) != null
                && avg(closes.subList(1, closes.size()), 5) < avg(closes.subList(1, closes.size()), 20);

        return DailyIndicators.builder()
                .date(date)
                .stkCd(stkCd)
                .closePrice(bd(close))
                .openPrice(bd(open))
                .highPrice(bd(high))
                .lowPrice(bd(low))
                .volume(volume)
                .volumeRatio(bd(volumeRatio, 2))
                .ma5(bd(ma5))
                .ma20(bd(ma20))
                .ma60(bd(ma60))
                .ma120(bd(ma120))
                .volMa20(volMa20 != null ? Math.round(volMa20) : null)
                .rsi14(bd(rsi14, 2))
                .stochK(bd(stoch[0], 2))
                .stochD(bd(stoch[1], 2))
                .bbUpper(bd(boll[0]))
                .bbMid(bd(boll[1]))
                .bbLower(bd(boll[2]))
                .bbWidthPct(bd(boll[3], 3))
                .pctB(bd(boll[4], 3))
                .atr14(bd(atr14, 2))
                .atrPct(bd(atrPct, 3))
                .macdLine(bd(macd[0], 2))
                .macdSignal(bd(macd[1], 2))
                .macdHist(bd(macd[2], 2))
                .isBullishAligned(ma5 != null && ma20 != null && ma60 != null && ma5 >= ma20 && ma20 >= ma60)
                .isAboveMa20(aboveMa20)
                .isNewHigh52w(newHigh52w)
                .goldenCrossToday(goldenCross)
                .swingHigh20d(bd(swingHigh20))
                .swingLow20d(bd(swingLow20))
                .swingHigh60d(bd(swingHigh60))
                .swingLow60d(bd(swingLow60))
                .build();
    }

    private DailyIndicators withExistingId(Long id, DailyIndicators entity) {
        return DailyIndicators.builder()
                .id(id)
                .date(entity.getDate())
                .stkCd(entity.getStkCd())
                .closePrice(entity.getClosePrice())
                .openPrice(entity.getOpenPrice())
                .highPrice(entity.getHighPrice())
                .lowPrice(entity.getLowPrice())
                .volume(entity.getVolume())
                .volumeRatio(entity.getVolumeRatio())
                .ma5(entity.getMa5())
                .ma20(entity.getMa20())
                .ma60(entity.getMa60())
                .ma120(entity.getMa120())
                .volMa20(entity.getVolMa20())
                .rsi14(entity.getRsi14())
                .stochK(entity.getStochK())
                .stochD(entity.getStochD())
                .bbUpper(entity.getBbUpper())
                .bbMid(entity.getBbMid())
                .bbLower(entity.getBbLower())
                .bbWidthPct(entity.getBbWidthPct())
                .pctB(entity.getPctB())
                .atr14(entity.getAtr14())
                .atrPct(entity.getAtrPct())
                .macdLine(entity.getMacdLine())
                .macdSignal(entity.getMacdSignal())
                .macdHist(entity.getMacdHist())
                .isBullishAligned(entity.getIsBullishAligned())
                .isAboveMa20(entity.getIsAboveMa20())
                .isNewHigh52w(entity.getIsNewHigh52w())
                .goldenCrossToday(entity.getGoldenCrossToday())
                .swingHigh20d(entity.getSwingHigh20d())
                .swingLow20d(entity.getSwingLow20d())
                .swingHigh60d(entity.getSwingHigh60d())
                .swingLow60d(entity.getSwingLow60d())
                .computedAt(entity.getComputedAt())
                .build();
    }

    private static void addAll(Set<String> target, Collection<String> source) {
        if (source == null) {
            return;
        }
        source.stream().filter(v -> v != null && !v.isBlank()).forEach(target::add);
    }

    private static Double ratio(Long bid, Long ask) {
        if (bid == null || ask == null || ask <= 0) {
            return null;
        }
        return (double) bid / ask;
    }

    private static BigDecimal bd(Double value) {
        return bd(value, 0);
    }

    private static BigDecimal bd(Double value, int scale) {
        if (value == null) {
            return null;
        }
        return BigDecimal.valueOf(value).setScale(scale, RoundingMode.HALF_UP);
    }

    private static Double avg(List<Double> values, int period) {
        if (values.size() < period) {
            return null;
        }
        return values.subList(0, period).stream().mapToDouble(Double::doubleValue).average().orElse(Double.NaN);
    }

    private static Double avgLong(List<Long> values, int period) {
        if (values.size() < period) {
            return null;
        }
        return values.subList(0, period).stream().mapToLong(Long::longValue).average().orElse(Double.NaN);
    }

    private static Double max(List<Double> values, int period) {
        if (values.isEmpty()) {
            return null;
        }
        return values.subList(0, Math.min(period, values.size())).stream().mapToDouble(Double::doubleValue).max().orElse(Double.NaN);
    }

    private static Double min(List<Double> values, int period) {
        if (values.isEmpty()) {
            return null;
        }
        return values.subList(0, Math.min(period, values.size())).stream().mapToDouble(Double::doubleValue).min().orElse(Double.NaN);
    }

    private static Double calcRsi(List<Double> closes, int period) {
        if (closes.size() <= period) {
            return null;
        }
        double gain = 0.0;
        double loss = 0.0;
        for (int i = 0; i < period; i++) {
            double diff = closes.get(i) - closes.get(i + 1);
            if (diff > 0) gain += diff;
            else loss -= diff;
        }
        if (loss == 0) {
            return 100.0;
        }
        double rs = (gain / period) / (loss / period);
        return 100.0 - (100.0 / (1.0 + rs));
    }

    private static Double[] calcStochastic(List<Double> closes, List<Double> highs, List<Double> lows, int period) {
        if (closes.size() < period) {
            return new Double[]{null, null};
        }
        double highest = max(highs, period);
        double lowest = min(lows, period);
        if (highest <= lowest) {
            return new Double[]{null, null};
        }
        double k = (closes.get(0) - lowest) / (highest - lowest) * 100.0;
        return new Double[]{k, k};
    }

    private static Double[] calcBollinger(List<Double> closes, int period) {
        if (closes.size() < period) {
            return new Double[]{null, null, null, null, null};
        }
        List<Double> sample = closes.subList(0, period);
        double mean = sample.stream().mapToDouble(Double::doubleValue).average().orElse(0.0);
        double variance = sample.stream().mapToDouble(v -> Math.pow(v - mean, 2)).sum() / period;
        double std = Math.sqrt(variance);
        double upper = mean + 2 * std;
        double lower = mean - 2 * std;
        double widthPct = mean != 0 ? ((upper - lower) / mean) * 100.0 : 0.0;
        double pctB = upper > lower ? (closes.get(0) - lower) / (upper - lower) : 0.0;
        return new Double[]{upper, mean, lower, widthPct, pctB};
    }

    private static Double calcAtr(List<Double> closes, List<Double> highs, List<Double> lows, int period) {
        if (closes.size() <= period) {
            return null;
        }
        double sum = 0.0;
        for (int i = 0; i < period; i++) {
            double high = highs.get(i);
            double low = lows.get(i);
            double prevClose = closes.get(i + 1);
            double tr = Math.max(high - low, Math.max(Math.abs(high - prevClose), Math.abs(low - prevClose)));
            sum += tr;
        }
        return sum / period;
    }

    private static Double[] calcMacd(List<Double> closes) {
        if (closes.size() < 35) {
            return new Double[]{null, null, null};
        }
        List<Double> chronological = new ArrayList<>(closes);
        java.util.Collections.reverse(chronological);
        double ema12 = chronological.get(0);
        double ema26 = chronological.get(0);
        List<Double> macdSeries = new ArrayList<>();
        double alpha12 = 2.0 / 13.0;
        double alpha26 = 2.0 / 27.0;
        for (double close : chronological) {
            ema12 = (close - ema12) * alpha12 + ema12;
            ema26 = (close - ema26) * alpha26 + ema26;
            macdSeries.add(ema12 - ema26);
        }
        double signal = macdSeries.get(0);
        double alpha9 = 2.0 / 10.0;
        for (double macd : macdSeries) {
            signal = (macd - signal) * alpha9 + signal;
        }
        double macdNow = macdSeries.get(macdSeries.size() - 1);
        double hist = macdNow - signal;
        return new Double[]{macdNow, signal, hist};
    }

    private static Double _d(Object value) {
        return _d(value, null);
    }

    private static Double _d(Object value, Double fallback) {
        try {
            if (value == null) {
                return fallback;
            }
            String raw = value.toString().replace(",", "").replace("+", "").trim();
            if (raw.isBlank()) {
                return fallback;
            }
            return Math.abs(Double.parseDouble(raw));
        } catch (Exception e) {
            return fallback;
        }
    }

    private static Long _l(Object value) {
        return _l(value, null);
    }

    private static Long _l(Object value, Long fallback) {
        try {
            if (value == null) {
                return fallback;
            }
            String raw = value.toString().replace(",", "").replace("+", "").trim();
            if (raw.isBlank()) {
                return fallback;
            }
            return Math.abs(Long.parseLong(raw));
        } catch (Exception e) {
            return fallback;
        }
    }
}
