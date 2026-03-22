package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.List;

/**
 * 뉴스 기반 매매 제어 서비스.
 * Python news_scheduler 가 Redis 에 저장한 분석 결과를 읽어 전략 실행 여부를 결정한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NewsControlService {

    public enum TradingControl { CONTINUE, CAUTIOUS, PAUSE }

    private static final String KEY_CONTROL   = "news:trading_control";
    private static final String KEY_SECTORS   = "news:sector_recommend";
    private static final String KEY_SENTIMENT = "news:market_sentiment";
    private static final String KEY_PRE_EVENT = "calendar:pre_event";

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    @Value("${news.trading-control-enabled:true}")
    private boolean tradingControlEnabled;

    @Value("${news.sector-filter-enabled:true}")
    private boolean sectorFilterEnabled;

    /**
     * 현재 매매 제어 상태 반환.
     * Redis 키가 없거나 비활성화된 경우 CONTINUE 반환.
     */
    public TradingControl getTradingControl() {
        if (!tradingControlEnabled) {
            return TradingControl.CONTINUE;
        }
        try {
            String value = redis.opsForValue().get(KEY_CONTROL);
            TradingControl control;
            if (value == null) {
                control = TradingControl.CONTINUE;
            } else {
                try {
                    control = TradingControl.valueOf(value.trim().toUpperCase());
                } catch (IllegalArgumentException e) {
                    log.warn("[NewsControl] 알 수 없는 trading_control 값 – CONTINUE 기본 적용");
                    control = TradingControl.CONTINUE;
                }
            }
            // Feature 2: 경제 이벤트 임박 시 CONTINUE → CAUTIOUS 격상
            if (control == TradingControl.CONTINUE) {
                String preEvent = redis.opsForValue().get(KEY_PRE_EVENT);
                if ("true".equals(preEvent)) {
                    log.debug("[NewsControl] calendar:pre_event 감지 → CAUTIOUS 격상");
                    control = TradingControl.CAUTIOUS;
                }
            }
            return control;
        } catch (Exception e) {
            log.warn("[NewsControl] Redis 읽기 오류: {} – CONTINUE 기본 적용", e.getMessage());
            return TradingControl.CONTINUE;
        }
    }

    /**
     * 추천 섹터 목록 반환.
     * 섹터 필터 비활성화 또는 Redis 키 없으면 빈 목록 반환.
     */
    public List<String> getRecommendedSectors() {
        if (!sectorFilterEnabled) {
            return Collections.emptyList();
        }
        try {
            String json = redis.opsForValue().get(KEY_SECTORS);
            if (json == null || json.isBlank() || json.equals("[]")) {
                return Collections.emptyList();
            }
            return objectMapper.readValue(json, new TypeReference<List<String>>() {});
        } catch (Exception e) {
            log.warn("[NewsControl] 추천 섹터 읽기 오류: {} – 빈 목록 반환", e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * 시장 심리 반환 (BULLISH / NEUTRAL / BEARISH).
     */
    public String getMarketSentiment() {
        try {
            String value = redis.opsForValue().get(KEY_SENTIMENT);
            return value != null ? value.trim() : "NEUTRAL";
        } catch (Exception e) {
            return "NEUTRAL";
        }
    }

    /**
     * 현재 매매 중단(PAUSE) 상태인지 확인.
     */
    public boolean isPaused() {
        return getTradingControl() == TradingControl.PAUSE;
    }

    /**
     * 현재 신중 매매(CAUTIOUS) 이상 상태인지 확인.
     */
    public boolean isCautious() {
        TradingControl ctrl = getTradingControl();
        return ctrl == TradingControl.CAUTIOUS || ctrl == TradingControl.PAUSE;
    }

    /**
     * CAUTIOUS 모드일 때 전략별 최대 신호 수 제한.
     * @param defaultMax 기본 최대 신호 수
     * @return CAUTIOUS 시 절반, PAUSE 시 0, CONTINUE 시 defaultMax
     */
    public int getMaxSignals(int defaultMax) {
        return switch (getTradingControl()) {
            case PAUSE    -> 0;
            case CAUTIOUS -> Math.max(1, defaultMax / 2);
            default       -> defaultMax;
        };
    }
}
