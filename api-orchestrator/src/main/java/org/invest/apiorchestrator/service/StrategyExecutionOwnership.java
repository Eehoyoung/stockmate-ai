package org.invest.apiorchestrator.service;

import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/** Single-owner switch preventing Java and Python from publishing duplicate strategy signals. */
@Component
public class StrategyExecutionOwnership {

    public static final String REDIS_KEY = "ops:strategy_execution_owner";

    public enum Owner { PYTHON, JAVA }

    private final StringRedisTemplate redis;
    private final Owner owner;

    public StrategyExecutionOwnership(
            StringRedisTemplate redis,
            @Value("${STRATEGY_EXECUTION_OWNER:PYTHON}") String configuredOwner) {
        this.redis = redis;
        this.owner = parse(configuredOwner);
    }

    @PostConstruct
    void publishOwner() {
        try {
            redis.opsForValue().set(REDIS_KEY, owner.name());
        } catch (Exception ignored) {
            // Ownership remains locally enforced when Redis is unavailable.
        }
    }

    public Owner owner() {
        return owner;
    }

    public boolean javaOwnsEvaluation() {
        return owner == Owner.JAVA;
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("owner", owner.name());
        result.put("java_signal_publish_enabled", javaOwnsEvaluation());
        result.put("python_signal_publish_enabled", owner == Owner.PYTHON);
        result.put("redis_key", REDIS_KEY);
        return result;
    }

    static Owner parse(String value) {
        String normalized = value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
        return "JAVA".equals(normalized) ? Owner.JAVA : Owner.PYTHON;
    }
}
