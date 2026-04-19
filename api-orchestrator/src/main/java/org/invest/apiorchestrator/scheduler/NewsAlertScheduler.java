package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.NewsAnalysis;
import org.invest.apiorchestrator.repository.NewsAnalysisRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * News alert queue consumer.
 *
 * User-facing news delivery is owned by ai-engine scheduled briefs only.
 * This scheduler, when enabled, persists alert metadata for internal tracking
 * and intentionally does not publish Telegram messages.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NewsAlertScheduler {

    private static final String KEY_ALERT_QUEUE = "news_alert_queue";

    private final StringRedisTemplate redis;
    private final NewsAnalysisRepository newsAnalysisRepository;
    private final ObjectMapper objectMapper;

    @Value("${app.news.alert-scheduler-enabled:false}")
    private boolean alertSchedulerEnabled;

    @Scheduled(fixedDelay = 60000, initialDelay = 30000)
    public void checkNewsAlerts() {
        if (!alertSchedulerEnabled) {
            return;
        }

        try {
            String raw = redis.opsForList().rightPop(KEY_ALERT_QUEUE);
            if (raw == null) {
                return;
            }

            @SuppressWarnings("unchecked")
            Map<String, Object> alert = objectMapper.readValue(raw, Map.class);
            String control = String.valueOf(alert.getOrDefault("trading_control", "CONTINUE"));
            String sentiment = String.valueOf(alert.getOrDefault("market_sentiment", "NEUTRAL"));
            String summary = String.valueOf(alert.getOrDefault("summary", ""));
            String confidence = String.valueOf(alert.getOrDefault("confidence", "LOW"));

            persistNewsAnalysis(alert, control, sentiment, confidence, summary);
            log.info("[NewsAlert] persisted only; ai-engine scheduled briefs own user-facing news delivery");
        } catch (Exception e) {
            log.error("[NewsAlert] processing error: {}", e.getMessage());
        }
    }

    private void persistNewsAnalysis(
            Map<String, Object> alert,
            String control,
            String sentiment,
            String confidence,
            String summary
    ) {
        try {
            @SuppressWarnings("unchecked")
            List<String> sectors = (List<String>) alert.getOrDefault("sectors", List.of());
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
            log.warn("[NewsAlert] DB save failed: {}", e.getMessage());
        }
    }
}
