package org.invest.apiorchestrator.service;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class StrategyExecutionOwnershipTests {

    @Test
    void defaultsUnknownOwnerToPythonAndPublishesIt() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);

        StrategyExecutionOwnership ownership = new StrategyExecutionOwnership(redis, "mistyped");
        ownership.publishOwner();

        assertEquals(StrategyExecutionOwnership.Owner.PYTHON, ownership.owner());
        assertFalse(ownership.javaOwnsEvaluation());
        assertEquals("PYTHON", ownership.snapshot().get("owner"));
        assertEquals(false, ownership.snapshot().get("java_signal_publish_enabled"));
        assertEquals(true, ownership.snapshot().get("python_signal_publish_enabled"));
        verify(values).set(StrategyExecutionOwnership.REDIS_KEY, "PYTHON");
    }

    @Test
    void javaOwnerEnablesOnlyJavaPublisher() {
        StrategyExecutionOwnership ownership = new StrategyExecutionOwnership(null, " java ");

        assertEquals(StrategyExecutionOwnership.Owner.JAVA, ownership.owner());
        assertTrue(ownership.javaOwnsEvaluation());
        assertEquals(true, ownership.snapshot().get("java_signal_publish_enabled"));
        assertEquals(false, ownership.snapshot().get("python_signal_publish_enabled"));
    }
}
