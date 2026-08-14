package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.TossInvestProperties;
import org.invest.apiorchestrator.dto.res.TossResponses;
import org.invest.apiorchestrator.service.TossMarketIndicatorService;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;

/**
 * 토스증권 Market Indicators 폴링.
 *
 * <p>기존 TradingScheduler.pollMarketIndexFluRt()는 KOSPI200/코스닥150 ETF
 * 프록시(069500/229200)를 Kiwoom ka10001로 조회해 {@code market:kospi_flu_rt}를
 * 채운다 — 실제 지수가 아닌 추적오차가 섞인 대용값이다. 토스 market-indicators는
 * 진짜 KOSPI/KOSDAQ 지수를 제공하므로, 이 스케줄러가 같은 5분 주기의 +20초
 * 오프셋으로 실행되어 같은 canonical 키를 더 정확한 값으로 덮어쓴다.
 *
 * <p>이 오프셋 순서가 곧 폴백 메커니즘이다: 토스 호출이 실패하면 이 메서드는
 * 아무것도 쓰지 않고 리턴하므로, 20초 전 Kiwoom이 써둔 값이 TTL(7분) 동안
 * 그대로 유효하다 — ai-engine 쪽 별도 병합 로직 없이 "토스 우선, Kiwoom 안전망"이
 * 성립한다. {@code market:kospi_flu_rt_source}에 마지막으로 어느 소스가 값을
 * 썼는지 기록해 검증에 사용한다.
 *
 * <p>{@code market:kospi_investor_flow} / {@code market:kosdaq_investor_flow}는
 * Kiwoom에는 없던 시장 전체 투자자별(개인/외국인/기관/기타법인) 순매수 금액이며,
 * strategy_meta.detect_market_regime()의 sideways 구간 보정에 쓰인다
 * (ai-engine 쪽 REGIME_INVESTOR_FLOW_ENABLED 플래그로 즉시 끌 수 있다).
 *
 * <p>{@code toss.enabled=false} (client_id/secret 미설정) 이면 전체 no-op —
 * Kiwoom 기반 장세 판단은 이 스케줄러 존재 여부와 무관하게 항상 동작한다.
 *
 * <p>2026-08-11: 두 폴링 모두 5분 → 1분 주기로 단축하고, 매 호출마다 canonical
 * 스냅샷 키(장세 판단용, 기존 동작 유지)와 함께 {@code market:{prefix}_index_ts} /
 * {@code market:{prefix}_investor_flow_ts} ZSET에 분단위 시계열을 적재한다(score=epoch초,
 * TTL 20h로 다음날 자동 초기화). investor-trading API 자체는 1d/1w/1mo/1y 집계만
 * 지원하지만 당일 레코드는 장 종료 전까지 갱신되는 잠정치이므로, 1분마다 스냅샷을
 * 찍으면 실질적으로 분단위 누적 수급 추이를 얻을 수 있다. TTL 20h는 그대로 두되
 * {@link #cleanupIndexSeries()}가 매일 21:00에 명시적으로 키를 비운다(TTL은 최종 안전망).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TossMarketScheduler {

    private static final Map<String, String> INDEX_SYMBOLS = Map.of("KOSPI", "kospi", "KOSDAQ", "kosdaq");

    private final TossInvestProperties tossProperties;
    private final TossMarketIndicatorService tossMarketIndicatorService;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    /** Kiwoom(TradingScheduler)의 "0 * 9-15" 폴링보다 20초 늦게 실행 — 성공하면
     * 이 값이 canonical 키를 덮어써 사실상 우선순위를 갖고, 실패하면 아무것도
     * 쓰지 않아 Kiwoom 값이 TTL(7분) 동안 그대로 안전망으로 남는다. */
    @Scheduled(cron = "20 * 9-15 * * MON-FRI", zone = "Asia/Seoul")
    public void pollTossRegimeCrossCheck() {
        if (!tossProperties.isEnabled() || KstClock.nowTime().isAfter(LocalTime.of(15, 10))) {
            return;
        }
        try {
            TossResponses.MarketIndicatorPricesResponse prices =
                    tossMarketIndicatorService.getPrices("KOSPI,KOSDAQ");
            if (prices == null || prices.getResult() == null) {
                return;
            }
            String nowIso = Instant.now().toString();
            for (TossResponses.MarketIndicatorPricesResponse.PriceItem item : prices.getResult()) {
                String prefix = INDEX_SYMBOLS.get(item.getSymbol());
                if (prefix == null || item.getLastPrice() == null) {
                    continue;
                }
                BigDecimal prevClose = getOrLoadPrevClose(item.getSymbol(), prefix);
                if (prevClose == null || prevClose.signum() == 0) {
                    continue;
                }
                BigDecimal lastPrice = safeDecimal(item.getLastPrice());
                if (lastPrice == null) {
                    continue;
                }
                double fluRt = lastPrice.subtract(prevClose)
                        .divide(prevClose, 6, java.math.RoundingMode.HALF_UP)
                        .doubleValue() * 100.0;
                String formatted = String.format("%.2f", fluRt);
                // canonical 키 — queue_worker._build_market_ctx / detect_market_regime이
                // 그대로 읽는 키. 실제 지수 값으로 덮어써 정확도를 올린다.
                redis.opsForValue().set("market:" + prefix + "_flu_rt", formatted, Duration.ofMinutes(7));
                // 진단용 원본값 + 소스 태그 (검증 계획에서 사용)
                redis.opsForValue().set("market:" + prefix + "_flu_rt_toss", formatted, Duration.ofMinutes(7));
                redis.opsForValue().set("market:" + prefix + "_flu_rt_source", "toss", Duration.ofMinutes(7));
                recordIndexSeries(prefix, nowIso, fluRt, lastPrice);
            }
            log.debug("[TossMarketIdx] 실지수 등락률로 canonical 키 갱신 완료");
        } catch (Exception e) {
            log.debug("[TossMarketIdx] 폴링 실패 (무시 — Kiwoom 프록시 값이 TTL 동안 안전망으로 유지됨): {}", e.getMessage());
        }
    }

    @Scheduled(cron = "0 * 9-15 * * MON-FRI", zone = "Asia/Seoul")
    public void pollTossInvestorFlow() {
        if (!tossProperties.isEnabled() || KstClock.nowTime().isAfter(LocalTime.of(15, 10))) {
            return;
        }
        for (Map.Entry<String, String> e : INDEX_SYMBOLS.entrySet()) {
            try {
                TossResponses.MarketIndicatorInvestorTradingResponse resp =
                        tossMarketIndicatorService.getInvestorTrading(e.getKey(), "1d", 1);
                if (resp == null || resp.getResult() == null) {
                    continue;
                }
                List<TossResponses.MarketIndicatorInvestorTradingResponse.InvestorTradingRecord> records =
                        resp.getResult().getRecords();
                if (records == null || records.isEmpty()) {
                    continue;
                }
                var record = records.get(0);
                ObjectNode node = objectMapper.createObjectNode();
                node.put("date", record.getDate());
                node.put("updatedAt", record.getUpdatedAt());
                putNet(node, "individual_net", record.getIndividual());
                putNet(node, "foreigner_net", record.getForeigner());
                putNet(node, "institution_net", record.getInstitution());
                putNet(node, "other_corp_net", record.getOtherCorporation());
                String json = objectMapper.writeValueAsString(node);
                redis.opsForValue().set("market:" + e.getValue() + "_investor_flow", json, Duration.ofMinutes(15));
                recordInvestorFlowSeries(e.getValue(), node);
            } catch (Exception ex) {
                log.debug("[TossInvestorFlow] 폴링 실패 [{}] (무시): {}", e.getKey(), ex.getMessage());
            }
        }
        log.debug("[TossInvestorFlow] 시장 수급 갱신 완료");
    }

    /** 시계열 키의 TTL(20h)은 다음날 새벽까지 남아있어 자정 넘어서도 조회가 가능하지만,
     * 당일 장 마감 후에는 더 이상 필요 없으므로 21:00에 명시적으로 비워 Redis를 정리한다.
     * TTL은 그대로 유지 — 이 스케줄러가 실패해도(예: 배포 중 재시작) TTL이 최종 안전망. */
    @Scheduled(cron = "0 0 21 * * MON-FRI", zone = "Asia/Seoul")
    public void cleanupIndexSeries() {
        if (!tossProperties.isEnabled()) {
            return;
        }
        try {
            for (String prefix : INDEX_SYMBOLS.values()) {
                redis.delete("market:" + prefix + "_index_ts");
                redis.delete("market:" + prefix + "_investor_flow_ts");
            }
            log.debug("[TossMarketIdx] 분단위 시계열 키 21시 정리 완료");
        } catch (Exception e) {
            log.debug("[TossMarketIdx] 시계열 키 정리 실패 (TTL 20h가 최종 안전망): {}", e.getMessage());
        }
    }

    /** market:{prefix}_index_ts ZSET에 분단위 스냅샷 추가. score=epoch초, TTL 20h로
     * 다음 거래일 자동 초기화 — 별도 트리밍 로직 없이 일별 리셋된다. */
    private void recordIndexSeries(String prefix, String tsIso, double fluRt, BigDecimal lastPrice) {
        try {
            ObjectNode node = objectMapper.createObjectNode();
            node.put("ts", tsIso);
            node.put("value", lastPrice.doubleValue());
            node.put("fluRt", Math.round(fluRt * 100.0) / 100.0);
            String key = "market:" + prefix + "_index_ts";
            redis.opsForZSet().add(key, objectMapper.writeValueAsString(node), Instant.now().getEpochSecond());
            redis.expire(key, Duration.ofHours(20));
        } catch (Exception ignored) {
            // 시계열 저장 실패는 canonical 키(장세 판단용)에 영향 없음 — 조용히 무시
        }
    }

    /** market:{prefix}_investor_flow_ts ZSET에 분단위 스냅샷 추가. investor-trading API가
     * 1d 집계만 제공하므로, 당일 잠정치를 1분마다 찍어 실질적인 분단위 추이를 만든다. */
    private void recordInvestorFlowSeries(String prefix, ObjectNode snapshotNode) {
        try {
            ObjectNode node = snapshotNode.deepCopy();
            node.put("ts", Instant.now().toString());
            String key = "market:" + prefix + "_investor_flow_ts";
            redis.opsForZSet().add(key, objectMapper.writeValueAsString(node), Instant.now().getEpochSecond());
            redis.expire(key, Duration.ofHours(20));
        } catch (Exception ignored) {
        }
    }

    private void putNet(ObjectNode node, String field,
                         TossResponses.MarketIndicatorInvestorTradingResponse.AmountPair pair) {
        if (pair == null) {
            return;
        }
        BigDecimal buy = safeDecimal(pair.getBuyAmount());
        BigDecimal sell = safeDecimal(pair.getSellAmount());
        if (buy != null && sell != null) {
            node.put(field, buy.subtract(sell));
        }
    }

    private BigDecimal getOrLoadPrevClose(String symbol, String prefix) {
        String key = "market:" + prefix + "_prev_close_toss";
        try {
            String cached = redis.opsForValue().get(key);
            if (cached != null && !cached.isBlank()) {
                return new BigDecimal(cached);
            }
        } catch (Exception ignored) {
            // fall through to fetch
        }
        TossResponses.MarketIndicatorCandlesResponse candles =
                tossMarketIndicatorService.getCandles(symbol, "1d", 2);
        if (candles == null || candles.getResult() == null || candles.getResult().getCandles() == null
                || candles.getResult().getCandles().size() < 2) {
            return null;
        }
        // index 0 = 당일 진행중 봉, index 1 = 전일 완결 봉의 종가
        String prevCloseStr = candles.getResult().getCandles().get(1).getClosePrice();
        BigDecimal prevClose = safeDecimal(prevCloseStr);
        if (prevClose != null) {
            try {
                redis.opsForValue().set(key, prevClose.toPlainString(), Duration.ofHours(20));
            } catch (Exception ignored) {
                // Redis 캐싱 실패는 다음 폴링에서 재조회로 자연 복구
            }
        }
        return prevClose;
    }

    private BigDecimal safeDecimal(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return new BigDecimal(value);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
