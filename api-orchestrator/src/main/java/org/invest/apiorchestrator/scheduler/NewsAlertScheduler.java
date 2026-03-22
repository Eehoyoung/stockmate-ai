package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.NewsAnalysis;
import org.invest.apiorchestrator.repository.NewsAnalysisRepository;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 뉴스 분석 결과 변경 감지 스케쥴러.
 * Redis news_alert_queue 를 1분마다 폴링하여 trading_control 변경 시
 * telegram_queue 에 NEWS_ALERT 메시지를 발행한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NewsAlertScheduler {

    private static final String KEY_ALERT_QUEUE = "news_alert_queue";

    private final StringRedisTemplate redis;
    private final RedisMarketDataService redisMarketDataService;
    private final NewsAnalysisRepository newsAnalysisRepository;
    private final ObjectMapper objectMapper;

    /** 1분마다 news_alert_queue 폴링 */
    @Scheduled(fixedDelay = 60000, initialDelay = 30000)
    public void checkNewsAlerts() {
        try {
            String raw = redis.opsForList().rightPop(KEY_ALERT_QUEUE);
            if (raw == null) return;

            @SuppressWarnings("unchecked")
            Map<String, Object> alert = objectMapper.readValue(raw, Map.class);
            String control    = String.valueOf(alert.getOrDefault("trading_control", "CONTINUE"));
            String prevCtrl   = String.valueOf(alert.getOrDefault("prev_control",    "CONTINUE"));
            String sentiment  = String.valueOf(alert.getOrDefault("market_sentiment","NEUTRAL"));
            String summary    = String.valueOf(alert.getOrDefault("summary",         ""));
            String confidence = String.valueOf(alert.getOrDefault("confidence",      "LOW"));

            log.info("[NewsAlert] 매매 제어 변경 감지: {} → {} sentiment={}", prevCtrl, control, sentiment);

            // DB 저장
            persistNewsAnalysis(alert, control, sentiment, confidence, summary);

            // 텔레그램 알림 발행 (ai_scored_queue → telegram-bot 직접 전달)
            String telegramMsg = buildTelegramMessage(alert, control, prevCtrl, sentiment, summary);
            redisMarketDataService.pushScoredQueue(telegramMsg);

            log.info("[NewsAlert] 텔레그램 알림 발행 완료");

        } catch (Exception e) {
            log.error("[NewsAlert] 처리 오류: {}", e.getMessage());
        }
    }

    private void persistNewsAnalysis(Map<String, Object> alert,
                                     String control, String sentiment,
                                     String confidence, String summary) {
        try {
            @SuppressWarnings("unchecked")
            List<String> sectors     = (List<String>) alert.getOrDefault("sectors",      List.of());
            @SuppressWarnings("unchecked")
            List<String> riskFactors = (List<String>) alert.getOrDefault("risk_factors", List.of());

            NewsAnalysis entity = NewsAnalysis.builder()
                    .analyzedAt(LocalDateTime.now())
                    .tradingCtrl(control)
                    .sentiment(sentiment)
                    .sectors(objectMapper.writeValueAsString(sectors))
                    .riskFactors(objectMapper.writeValueAsString(riskFactors))
                    .summary(summary)
                    .confidence(confidence)
                    .build();
            newsAnalysisRepository.save(entity);
        } catch (Exception e) {
            log.warn("[NewsAlert] DB 저장 실패: {}", e.getMessage());
        }
    }

    private String buildTelegramMessage(Map<String, Object> alert,
                                        String control, String prevCtrl,
                                        String sentiment, String summary) {
        try {
            String emoji = switch (control) {
                case "PAUSE"    -> "🚨";
                case "CAUTIOUS" -> "⚠️";
                default         -> "✅";
            };
            String controlLabel = switch (control) {
                case "PAUSE"    -> "매매 중단";
                case "CAUTIOUS" -> "신중 매매";
                default         -> "정상 매매";
            };
            String sentimentLabel = switch (sentiment) {
                case "BULLISH"  -> "강세";
                case "BEARISH"  -> "약세";
                default         -> "중립";
            };

            @SuppressWarnings("unchecked")
            List<String> sectors     = (List<String>) alert.getOrDefault("sectors",      List.of());
            @SuppressWarnings("unchecked")
            List<String> riskFactors = (List<String>) alert.getOrDefault("risk_factors", List.of());

            StringBuilder sb = new StringBuilder();
            sb.append(emoji).append(" [뉴스 기반 매매 제어 변경]\n");
            sb.append("상태: ").append(prevCtrl).append(" → ").append(controlLabel).append("\n");
            sb.append("시장심리: ").append(sentimentLabel).append("\n");
            if (!sectors.isEmpty()) {
                sb.append("추천섹터: ").append(String.join(", ", sectors)).append("\n");
            }
            if (!riskFactors.isEmpty()) {
                sb.append("리스크: ").append(String.join(" / ", riskFactors)).append("\n");
            }
            if (!summary.isBlank()) {
                sb.append("요약: ").append(summary);
            }

            Map<String, Object> msg = Map.of(
                    "type",            "NEWS_ALERT",
                    "trading_control", control,
                    "market_sentiment", sentiment,
                    "sectors",         sectors,
                    "summary",         summary,
                    "message",         sb.toString()
            );
            return objectMapper.writeValueAsString(msg);
        } catch (Exception e) {
            return "{\"type\":\"NEWS_ALERT\",\"trading_control\":\"" + control + "\"}";
        }
    }
}
