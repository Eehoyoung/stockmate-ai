package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.StockMaster;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.invest.apiorchestrator.util.KstClock;

import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

abstract class DailyStrategySupport {

    protected final KiwoomApiService apiService;
    protected final RedisMarketDataService redisService;
    protected final StockMasterRepository stockMasterRepository;

    protected DailyStrategySupport(
            KiwoomApiService apiService,
            RedisMarketDataService redisService,
            StockMasterRepository stockMasterRepository
    ) {
        this.apiService = apiService;
        this.redisService = redisService;
        this.stockMasterRepository = stockMasterRepository;
    }

    protected DailySeries fetchDailySeries(String stkCd, int minSize) {
        var resp = apiService.fetchKa10081(stkCd);
        if (resp == null || resp.getCandles() == null || resp.getCandles().size() < minSize) {
            return null;
        }
        var raw = resp.getCandles();
        int n = raw.size();
        double[] highs = new double[n];
        double[] lows = new double[n];
        double[] closes = new double[n];
        double[] vols = new double[n];
        for (int i = 0; i < n; i++) {
            double close = parseDoubleStr(raw.get(i).getCurPrc());
            highs[i] = parseDoubleStr(raw.get(i).getHighPric());
            lows[i] = parseDoubleStr(raw.get(i).getLowPric());
            closes[i] = close;
            vols[i] = parseLongStr(raw.get(i).getTrdeQty());
            if (highs[i] <= 0) {
                highs[i] = close;
            }
            if (lows[i] <= 0) {
                lows[i] = close;
            }
        }
        return new DailySeries(raw, highs, lows, closes, vols);
    }

    protected String resolveStkNm(String stkCd) {
        try {
            var tickOpt = redisService.getTickData(stkCd);
            if (tickOpt.isPresent()) {
                Object nm = tickOpt.get().get("stk_nm");
                if (nm != null && !nm.toString().trim().isEmpty()) {
                    return nm.toString().trim();
                }
            }
        } catch (Exception ignored) {
        }
        try {
            var response = apiService.fetchKa10001(stkCd);
            if (response != null && response.getStkNm() != null && !response.getStkNm().trim().isEmpty()) {
                return response.getStkNm().trim();
            }
        } catch (Exception ignored) {
        }
        try {
            return stockMasterRepository.findByStkCd(stkCd)
                    .map(m -> m.getStkNm() != null ? m.getStkNm().trim() : "")
                    .orElse("");
        } catch (Exception ignored) {
        }
        return "";
    }

    protected RedisMarketDataService.FreshData<Double> entryStrength(String stkCd, int count) {
        return redisService.getFreshStrength(
                stkCd, count, RedisMarketDataService.ENTRY_STRENGTH_POLICY);
    }

    protected double neutralStrength(RedisMarketDataService.FreshData<Double> data) {
        return data.usable() && data.value() != null ? data.value() : 100.0;
    }

    protected void addFreshnessExtra(Map<String, Object> extra, String kind,
                                     RedisMarketDataService.FreshData<?> data) {
        extra.put(kind + "_freshness_state", data.state().name());
        extra.put(kind + "_freshness_source", data.source());
        extra.put(kind + "_freshness_age_ms", data.age() != null ? data.age().toMillis() : null);
    }

    protected SectorFlow fetchSectorFlow(String stkCd) {
        try {
            Optional<StockMaster> masterOpt = stockMasterRepository.findByStkCd(stkCd);
            if (masterOpt.isEmpty()) {
                return SectorFlow.empty();
            }
            StockMaster master = masterOpt.get();
            String market = normalizeMarket(master.getMarket());
            String sectorName = normalizeText(master.getSector() != null ? master.getSector() : master.getIndustry());
            if (market.isEmpty()) {
                return SectorFlow.empty();
            }
            var response = apiService.fetchKa10051(StrategyRequests.SectorInvestorNetBuyRequest.builder()
                    .mrktTp(market)
                    .baseDt(KstClock.today().format(DateTimeFormatter.BASIC_ISO_DATE))
                    .build());
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return SectorFlow.empty();
            }
            String explicitSectorCode = normalizeSectorCode(master.getSector());
            var best = response.getItems().stream()
                    .filter(item -> !explicitSectorCode.isEmpty() && explicitSectorCode.equals(item.getIndsCd()))
                    .findFirst()
                    .orElse(null);
            if (best == null) {
                best = response.getItems().stream()
                    .filter(item -> matchesSector(sectorName, normalizeText(item.getIndsNm())))
                    .findFirst()
                    .orElse(null);
            }
            if (best == null) {
                return SectorFlow.empty();
            }
            double foreign = parseDoubleSign(best.getForNetprps());
            double institution = parseDoubleSign(best.getOrgnNetprps());
            double fluRt = parseDoubleStr(best.getFluRt());
            double bonus = Math.min(8.0, Math.max(0.0, foreign + institution) / 1_000.0)
                    + (fluRt > 0 ? Math.min(4.0, fluRt * 0.5) : Math.max(-4.0, fluRt * 0.3));
            return new SectorFlow(best.getIndsCd(), best.getIndsNm(), foreign, institution, fluRt, bonus);
        } catch (Exception ignored) {
            return SectorFlow.empty();
        }
    }

    protected MarketBreadth fetchMarketBreadthForStock(String stkCd) {
        try {
            Optional<StockMaster> masterOpt = stockMasterRepository.findByStkCd(stkCd);
            if (masterOpt.isEmpty()) {
                return MarketBreadth.empty();
            }
            String market = normalizeMarket(masterOpt.get().getMarket());
            if (market.isEmpty()) {
                return MarketBreadth.empty();
            }
            var response = apiService.fetchKa20003(StrategyRequests.AllSectorIndexRequest.builder()
                    .indsCd(market)
                    .build());
            if (response == null || response.getItems() == null || response.getItems().isEmpty()) {
                return MarketBreadth.empty();
            }
            var marketItem = response.getItems().stream()
                    .filter(item -> market.equals(item.getStkCd()))
                    .findFirst()
                    .orElse(response.getItems().get(0));
            double fluRt = parseDoubleStr(marketItem.getFluRt());
            double rising = parseDoubleStr(marketItem.getRising());
            double falling = parseDoubleStr(marketItem.getFall());
            double breadth = rising - falling;
            double bonus = (fluRt > 0 ? Math.min(3.0, fluRt * 0.4) : Math.max(-3.0, fluRt * 0.3))
                    + (breadth > 0 ? Math.min(3.0, breadth / 50.0) : Math.max(-3.0, breadth / 50.0));
            return new MarketBreadth(marketItem.getStkCd(), marketItem.getStkNm(), fluRt, rising, falling, bonus);
        } catch (Exception ignored) {
            return MarketBreadth.empty();
        }
    }

    private boolean matchesSector(String masterSector, String apiSector) {
        if (masterSector.isEmpty() || apiSector.isEmpty()) {
            return false;
        }
        return apiSector.contains(masterSector) || masterSector.contains(apiSector);
    }

    private String normalizeSectorCode(String value) {
        if (value == null) {
            return "";
        }
        String text = value.trim().toUpperCase(Locale.ROOT);
        return text.matches("\\d{3}(_[A-Z]+)?") ? text : "";
    }

    protected String normalizeMarket(String value) {
        String text = value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
        if (text.equals("001") || text.contains("KOSPI") || text.contains("코스피")) {
            return "001";
        }
        if (text.equals("101") || text.contains("KOSDAQ") || text.contains("코스닥")) {
            return "101";
        }
        return text;
    }

    private String normalizeText(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("업종", "")
                .replace("지수", "")
                .replace(" ", "")
                .trim();
    }

    protected double parseDouble(Map<Object, Object> map, String key) {
        try {
            return Double.parseDouble(map.getOrDefault(key, "0").toString()
                    .replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    protected double parseDoubleStr(String value) {
        try {
            return value == null ? 0 : Double.parseDouble(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    protected double parseDoubleSign(String value) {
        try {
            return value == null ? 0 : Double.parseDouble(value.replace(",", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    protected long parseLongStr(String value) {
        try {
            return value == null ? 0 : Long.parseLong(value.replace(",", "").replace("+", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    protected double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    protected static double maAvg(double[] arr, int offset, int period) {
        if (arr.length < offset + period) {
            return 0;
        }
        double sum = 0;
        for (int i = offset; i < offset + period; i++) {
            sum += arr[i];
        }
        return sum / period;
    }

    protected static double[] calcRsi(double[] closes, int period) {
        int n = closes.length;
        if (n < period + 2) {
            return new double[0];
        }
        double[] c = new double[n];
        for (int i = 0; i < n; i++) {
            c[i] = closes[n - 1 - i];
        }
        double avgGain = 0;
        double avgLoss = 0;
        for (int i = 1; i <= period; i++) {
            double diff = c[i] - c[i - 1];
            if (diff > 0) {
                avgGain += diff;
            } else {
                avgLoss -= diff;
            }
        }
        avgGain /= period;
        avgLoss /= period;
        int resultLen = n - period;
        double[] result = new double[resultLen];
        result[0] = avgLoss == 0 ? 100 : 100 - 100.0 / (1 + avgGain / avgLoss);
        for (int i = 1; i < resultLen; i++) {
            double diff = c[period + i] - c[period + i - 1];
            avgGain = (avgGain * (period - 1) + Math.max(diff, 0)) / period;
            avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period;
            result[i] = avgLoss == 0 ? 100 : 100 - 100.0 / (1 + avgGain / avgLoss);
        }
        double[] out = new double[resultLen];
        for (int i = 0; i < resultLen; i++) {
            out[i] = result[resultLen - 1 - i];
        }
        return out;
    }

    protected static double[][] calcMacd(double[] closes, int fast, int slow, int signal) {
        double[] fastOf = calcEmaOf(closes, fast);
        double[] slowOf = calcEmaOf(closes, slow);
        int macdLen = slowOf.length;
        if (macdLen == 0) {
            return new double[][]{new double[0], new double[0], new double[0]};
        }
        int offset = fastOf.length - macdLen;
        double[] macdOf = new double[macdLen];
        for (int i = 0; i < macdLen; i++) {
            macdOf[i] = fastOf[i + offset] - slowOf[i];
        }
        if (macdLen < signal) {
            return new double[][]{new double[0], new double[0], new double[0]};
        }
        double alpha = 2.0 / (signal + 1);
        double sma = 0;
        for (int i = 0; i < signal; i++) {
            sma += macdOf[i];
        }
        sma /= signal;
        int sigLen = macdLen - signal + 1;
        double[] sigOf = new double[sigLen];
        sigOf[0] = sma;
        for (int i = 1; i < sigLen; i++) {
            sigOf[i] = macdOf[signal - 1 + i] * alpha + sigOf[i - 1] * (1 - alpha);
        }
        double[] histOf = new double[sigLen];
        int macdOffset = macdLen - sigLen;
        for (int i = 0; i < sigLen; i++) {
            histOf[i] = macdOf[i + macdOffset] - sigOf[i];
        }
        double[] macd = new double[sigLen];
        double[] sig = new double[sigLen];
        double[] hist = new double[sigLen];
        for (int i = 0; i < sigLen; i++) {
            macd[i] = macdOf[macdOffset + sigLen - 1 - i];
            sig[i] = sigOf[sigLen - 1 - i];
            hist[i] = histOf[sigLen - 1 - i];
        }
        return new double[][]{macd, sig, hist};
    }

    private static double[] calcEmaOf(double[] closesNewestFirst, int period) {
        int n = closesNewestFirst.length;
        if (n < period) {
            return new double[0];
        }
        double[] closes = new double[n];
        for (int i = 0; i < n; i++) {
            closes[i] = closesNewestFirst[n - 1 - i];
        }
        double alpha = 2.0 / (period + 1);
        double sma = 0;
        for (int i = 0; i < period; i++) {
            sma += closes[i];
        }
        sma /= period;
        int len = n - period + 1;
        double[] ema = new double[len];
        ema[0] = sma;
        for (int i = 1; i < len; i++) {
            ema[i] = closes[period - 1 + i] * alpha + ema[i - 1] * (1 - alpha);
        }
        return ema;
    }

    protected static double calcBollingerBandwidth(double[] closes, int period) {
        if (closes.length < period) {
            return -1;
        }
        double mean = maAvg(closes, 0, period);
        double variance = 0;
        for (int i = 0; i < period; i++) {
            variance += Math.pow(closes[i] - mean, 2);
        }
        double std = Math.sqrt(variance / period);
        return mean > 0 ? (std * 4 / mean) * 100 : -1;
    }

    protected static double calcBollingerUpper(double[] closes, int period) {
        if (closes.length < period) {
            return 0;
        }
        double mean = maAvg(closes, 0, period);
        double variance = 0;
        for (int i = 0; i < period; i++) {
            variance += Math.pow(closes[i] - mean, 2);
        }
        return mean + 2 * Math.sqrt(variance / period);
    }

    protected static double calcBollingerPctB(double[] closes, int period) {
        if (closes.length < period) {
            return -1;
        }
        double mean = maAvg(closes, 0, period);
        double variance = 0;
        for (int i = 0; i < period; i++) {
            variance += Math.pow(closes[i] - mean, 2);
        }
        double std = Math.sqrt(variance / period);
        double upper = mean + 2 * std;
        double lower = mean - 2 * std;
        return upper > lower ? (closes[0] - lower) / (upper - lower) : -1;
    }

    protected static double[] calcAtr(double[] highs, double[] lows, double[] closes, int period) {
        int n = Math.min(highs.length, Math.min(lows.length, closes.length));
        if (n < period + 1) {
            return new double[0];
        }
        double[] trOf = new double[n - 1];
        for (int i = 0; i < n - 1; i++) {
            double high = highs[n - 1 - i];
            double low = lows[n - 1 - i];
            if (i == 0) {
                trOf[0] = high - low;
                continue;
            }
            double prevClose = closes[n - 1 - (i - 1)];
            trOf[i] = Math.max(high - low, Math.max(Math.abs(high - prevClose), Math.abs(low - prevClose)));
        }
        double atr0 = 0;
        for (int i = 0; i < period; i++) {
            atr0 += trOf[i];
        }
        atr0 /= period;
        int len = n - period;
        double[] atrOf = new double[len];
        atrOf[0] = atr0;
        for (int i = 1; i < len; i++) {
            atrOf[i] = (atrOf[i - 1] * (period - 1) + trOf[period - 1 + i]) / period;
        }
        double[] out = new double[len];
        for (int i = 0; i < len; i++) {
            out[i] = atrOf[len - 1 - i];
        }
        return out;
    }

    protected static double[][] calcSlowStoch(double[] highs, double[] lows, double[] closes,
                                              int kPeriod, int dPeriod, int slowing) {
        int n = Math.min(highs.length, Math.min(lows.length, closes.length));
        if (n < kPeriod + slowing + dPeriod) {
            return new double[][]{new double[0], new double[0]};
        }
        int rawLen = n - kPeriod + 1;
        double[] rawK = new double[rawLen];
        for (int i = 0; i < rawLen; i++) {
            int newestIndex = n - 1 - i;
            double high = 0;
            double low = Double.MAX_VALUE;
            for (int j = 0; j < kPeriod; j++) {
                int idx = newestIndex - j;
                if (idx < 0) {
                    break;
                }
                high = Math.max(high, highs[idx]);
                low = Math.min(low, lows[idx]);
            }
            rawK[i] = high > low ? (closes[newestIndex] - low) / (high - low) * 100 : 50;
        }
        int slowLen = rawLen - slowing + 1;
        if (slowLen <= 0) {
            return new double[][]{new double[0], new double[0]};
        }
        double[] slowKOf = new double[slowLen];
        for (int i = 0; i < slowLen; i++) {
            double sum = 0;
            for (int j = 0; j < slowing; j++) {
                sum += rawK[i + j];
            }
            slowKOf[i] = sum / slowing;
        }
        int dLen = slowLen - dPeriod + 1;
        if (dLen <= 0) {
            return new double[][]{new double[0], new double[0]};
        }
        double[] slowDOf = new double[dLen];
        for (int i = 0; i < dLen; i++) {
            double sum = 0;
            for (int j = 0; j < dPeriod; j++) {
                sum += slowKOf[i + j];
            }
            slowDOf[i] = sum / dPeriod;
        }
        int outLen = dLen;
        int kOffset = slowLen - outLen;
        double[] k = new double[outLen];
        double[] d = new double[outLen];
        for (int i = 0; i < outLen; i++) {
            k[i] = slowKOf[kOffset + outLen - 1 - i];
            d[i] = slowDOf[outLen - 1 - i];
        }
        return new double[][]{k, d};
    }

    protected static double[] calcWilliamsR(double[] highs, double[] lows, double[] closes, int period) {
        int n = Math.min(highs.length, Math.min(lows.length, closes.length));
        if (n < period) {
            return new double[0];
        }
        int outLen = n - period + 1;
        double[] out = new double[outLen];
        for (int i = 0; i < outLen; i++) {
            double high = 0;
            double low = Double.MAX_VALUE;
            for (int j = 0; j < period; j++) {
                high = Math.max(high, highs[i + j]);
                low = Math.min(low, lows[i + j]);
            }
            out[i] = high > low ? (high - closes[i]) / (high - low) * -100 : -50;
        }
        return out;
    }

    protected static double calcMfiLatest(double[] highs, double[] lows, double[] closes, double[] vols, int period) {
        return calcMfiAt(highs, lows, closes, vols, period, 0);
    }

    protected static double calcMfiAt(double[] highs, double[] lows, double[] closes,
                                      double[] vols, int period, int offset) {
        int n = Math.min(highs.length, Math.min(lows.length, Math.min(closes.length, vols.length)));
        if (n < offset + period + 1) {
            return 0;
        }
        double posFlow = 0;
        double negFlow = 0;
        for (int i = offset; i < offset + period; i++) {
            double typical = (highs[i] + lows[i] + closes[i]) / 3.0;
            double previousTypical = (highs[i + 1] + lows[i + 1] + closes[i + 1]) / 3.0;
            double moneyFlow = typical * vols[i];
            if (typical > previousTypical) {
                posFlow += moneyFlow;
            } else {
                negFlow += moneyFlow;
            }
        }
        return negFlow == 0 ? 100 : 100 - 100.0 / (1 + posFlow / negFlow);
    }

    protected record DailySeries(
            List<KiwoomApiResponses.DailyCandleResponse.DailyCandleItem> raw,
            double[] highs,
            double[] lows,
            double[] closes,
            double[] vols
    ) {
        int size() {
            return closes.length;
        }
    }

    protected record SectorFlow(
            String sectorCode,
            String sectorName,
            double foreignNet,
            double institutionNet,
            double fluRt,
            double scoreBonus
    ) {
        static SectorFlow empty() {
            return new SectorFlow(null, null, 0, 0, 0, 0);
        }

        boolean present() {
            return sectorCode != null || sectorName != null;
        }
    }

    protected record MarketBreadth(
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
