package org.invest.apiorchestrator.scheduler;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

@ExtendWith(MockitoExtension.class)
class DataCleanupSchedulerTests {

    @Mock
    private JdbcTemplate jdbcTemplate;

    private DataCleanupScheduler scheduler;

    @BeforeEach
    void setUp() {
        scheduler = new DataCleanupScheduler(jdbcTemplate);
        ReflectionTestUtils.setField(scheduler, "partitionRetentionEnabled", true);
        ReflectionTestUtils.setField(scheduler, "partitionRetentionDryRun", false);
        ReflectionTestUtils.setField(scheduler, "tickRetainDays", 3);
    }

    @Test
    void usesHardDropRetentionForLocalStorageCleanup() {
        ReflectionTestUtils.setField(scheduler, "hardDropOldTickPartitionsEnabled", true);
        when(jdbcTemplate.queryForList(
                "SELECT * FROM ws_tick_data_hard_retention_policy(?, ?)", 3, false
        )).thenReturn(List.of());

        ReflectionTestUtils.invokeMethod(scheduler, "cleanupPartitionedTickData");

        verify(jdbcTemplate).queryForList(
                "SELECT * FROM ws_tick_data_hard_retention_policy(?, ?)", 3, false
        );
    }

    @Test
    void canFallBackToGuardedRetention() {
        ReflectionTestUtils.setField(scheduler, "hardDropOldTickPartitionsEnabled", false);
        when(jdbcTemplate.queryForList(
                "SELECT * FROM ws_tick_data_retention_policy(?, ?)", 3, false
        )).thenReturn(List.of());

        ReflectionTestUtils.invokeMethod(scheduler, "cleanupPartitionedTickData");

        verify(jdbcTemplate).queryForList(
                "SELECT * FROM ws_tick_data_retention_policy(?, ?)", 3, false
        );
    }

    @Test
    void cleansUpSignalDataFreshnessLogWithThreeDayDefaultRetention() {
        ReflectionTestUtils.setField(scheduler, "signalDataFreshnessLogRetainDays", 3);
        when(jdbcTemplate.update(
                "DELETE FROM signal_data_freshness_log WHERE created_at < NOW() - (? * INTERVAL '1 day')", 3
        )).thenReturn(0);

        ReflectionTestUtils.invokeMethod(scheduler, "cleanupSignalDataFreshnessLog");

        verify(jdbcTemplate).update(
                "DELETE FROM signal_data_freshness_log WHERE created_at < NOW() - (? * INTERVAL '1 day')", 3
        );
    }

    @Test
    void rejectsMultipleRetentionOwners() {
        ReflectionTestUtils.setField(scheduler, "legacyTickTruncateEnabled", false);
        ReflectionTestUtils.setField(scheduler, "externalTickRetentionEnabled", true);
        ReflectionTestUtils.setField(scheduler, "tickRetentionOwner", "api-orchestrator");
        ReflectionTestUtils.setField(scheduler, "tickSummaryEnabled", true);

        assertThrows(IllegalStateException.class, scheduler::validateRetentionOwnership);
    }

    @Test
    void acceptsFrozenRetentionConfiguration() {
        ReflectionTestUtils.setField(scheduler, "legacyTickTruncateEnabled", false);
        ReflectionTestUtils.setField(scheduler, "partitionRetentionEnabled", false);
        ReflectionTestUtils.setField(scheduler, "hardDropOldTickPartitionsEnabled", false);
        ReflectionTestUtils.setField(scheduler, "externalTickRetentionEnabled", false);
        ReflectionTestUtils.setField(scheduler, "tickRetentionOwner", "api-orchestrator");
        ReflectionTestUtils.setField(scheduler, "tickSummaryEnabled", true);

        assertDoesNotThrow(scheduler::validateRetentionOwnership);
    }
}
