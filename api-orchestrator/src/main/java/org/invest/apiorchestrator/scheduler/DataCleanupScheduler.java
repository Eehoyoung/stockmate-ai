package org.invest.apiorchestrator.scheduler;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.util.KstClock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataCleanupScheduler {

    private final JdbcTemplate jdbcTemplate;

    @Value("${cleanup.ws-tick-data.legacy-truncate-enabled:false}")
    private boolean legacyTickTruncateEnabled;

    @Value("${cleanup.ws-tick-data.partition-retention-enabled:false}")
    private boolean partitionRetentionEnabled;

    @Value("${cleanup.ws-tick-data.partition-retention-dry-run:true}")
    private boolean partitionRetentionDryRun;

    @Value("${cleanup.ws-tick-data.hard-drop-old-partitions-enabled:false}")
    private boolean hardDropOldTickPartitionsEnabled;

    @Value("${cleanup.ws-tick-data.retain-days:3}")
    private int tickRetainDays;

    @Value("${cleanup.vi-events.retain-days:3}")
    private int viEventRetainDays;

    @Value("${cleanup.candidate-pool-history.retain-days:7}")
    private int candidatePoolRetainDays;

    @Value("${cleanup.daily-indicators.retain-days:30}")
    private int dailyIndicatorRetainDays;

    @Value("${cleanup.ai-cancel-signal.retain-days:30}")
    private int aiCancelSignalRetainDays;

    @Value("${cleanup.rule-cancel-signal.retain-days:30}")
    private int ruleCancelSignalRetainDays;

    @Value("${cleanup.signal-data-freshness-log.retain-days:3}")
    private int signalDataFreshnessLogRetainDays;

    @Value("${cleanup.overnight-evaluations.retain-days:90}")
    private int overnightEvaluationRetainDays;

    @Value("${cleanup.kiwoom-tokens.inactive-retain-days:7}")
    private int inactiveTokenRetainDays;

    @Value("${cleanup.log-files.enabled:true}")
    private boolean logFileCleanupEnabled;

    @Value("${cleanup.log-files.directory:/app/logs}")
    private String logDirectory;

    @Value("${cleanup.log-files.retain-days:2}")
    private int logRetainDays;

    @Value("${cleanup.ws-tick-data.summary-enabled:true}")
    private boolean tickSummaryEnabled;

    @Value("${cleanup.ws-tick-data.retention-owner:api-orchestrator}")
    private String tickRetentionOwner;

    @Value("${cleanup.ws-tick-data.external-retention-enabled:false}")
    private boolean externalTickRetentionEnabled;

    @PostConstruct
    void validateRetentionOwnership() {
        if (legacyTickTruncateEnabled && partitionRetentionEnabled) {
            throw new IllegalStateException("legacy truncate and partition retention cannot both be enabled");
        }
        if (hardDropOldTickPartitionsEnabled && !partitionRetentionEnabled) {
            throw new IllegalStateException("hard-drop requires partition retention to be enabled");
        }
        if (partitionRetentionEnabled && externalTickRetentionEnabled) {
            throw new IllegalStateException("multiple ws tick retention owners are enabled");
        }
        if (partitionRetentionEnabled && !"api-orchestrator".equalsIgnoreCase(tickRetentionOwner)) {
            throw new IllegalStateException("api-orchestrator retention enabled with a different owner");
        }
        if (partitionRetentionEnabled && !partitionRetentionDryRun && !tickSummaryEnabled) {
            throw new IllegalStateException("destructive retention requires the summary producer");
        }
        log.info("[DataCleanup] retention config owner={} partitionEnabled={} externalEnabled={} dryRun={} summaryEnabled={}",
                tickRetentionOwner, partitionRetentionEnabled, externalTickRetentionEnabled,
                partitionRetentionDryRun, tickSummaryEnabled);
    }

    @Scheduled(cron = "${cleanup.ws-tick-data.summary-cron:20 */5 * * * *}", zone = "Asia/Seoul")
    public void refreshTickSummary() {
        if (!tickSummaryEnabled) return;
        OffsetDateTime end = KstClock.nowOffset().withSecond(0).withNano(0);
        OffsetDateTime start = end.minusMinutes(15);
        try {
            Long affected = jdbcTemplate.queryForObject(
                    "SELECT refresh_ws_tick_summary_1m(?, ?)", Long.class, start, end);
            log.info("[TickSummary] refreshed from={} to={} rows={}", start, end, affected);
        } catch (Exception e) {
            log.error("[TickSummary] refresh failed from={} to={}: {}", start, end, e.getMessage(), e);
        }
    }

    @Scheduled(cron = "${cleanup.cron:0 0 21 * * *}", zone = "Asia/Seoul")
    public void cleanupOldData() {
        log.info("[DataCleanup] started");
        cleanupLegacyTickData();
        cleanupPartitionedTickData();
        cleanupViEvents();
        cleanupCandidatePoolHistory();
        cleanupDailyIndicators();
        cleanupAiCancelSignal();
        cleanupRuleCancelSignal();
        cleanupSignalDataFreshnessLog();
        cleanupOvernightEvaluations();
        cleanupInactiveKiwoomTokens();
        cleanupLogFiles();
        log.info("[DataCleanup] completed");
    }

    private void cleanupLegacyTickData() {
        if (!legacyTickTruncateEnabled) {
            log.info("[DataCleanup] legacy ws_tick_data truncate skipped");
            return;
        }
        try {
            jdbcTemplate.execute("TRUNCATE TABLE ws_tick_data");
            log.info("[DataCleanup] legacy ws_tick_data truncated");
        } catch (Exception e) {
            log.error("[DataCleanup] legacy ws_tick_data truncate failed: {}", e.getMessage(), e);
        }
    }

    private void cleanupPartitionedTickData() {
        if (!partitionRetentionEnabled) {
            log.info("[DataCleanup] partitioned ws tick retention skipped");
            return;
        }
        try {
            String retentionFunction = hardDropOldTickPartitionsEnabled
                    ? "ws_tick_data_hard_retention_policy"
                    : "ws_tick_data_retention_policy";
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                    "SELECT * FROM " + retentionFunction + "(?, ?)",
                    Math.max(tickRetainDays, 0),
                    partitionRetentionDryRun
            );
            log.info("[DataCleanup] partitioned ws tick retention hardDrop={} dryRun={} rows={}",
                    hardDropOldTickPartitionsEnabled, partitionRetentionDryRun, rows);
        } catch (Exception e) {
            log.error("[DataCleanup] partitioned ws tick retention failed: {}", e.getMessage(), e);
        }
    }

    private void cleanupViEvents() {
        deleteByInterval("vi_events", "created_at", viEventRetainDays);
    }

    private void cleanupCandidatePoolHistory() {
        deleteByInterval("candidate_pool_history", "last_seen", candidatePoolRetainDays);
    }

    private void cleanupDailyIndicators() {
        deleteByInterval("daily_indicators", "computed_at", dailyIndicatorRetainDays);
    }

    private void cleanupAiCancelSignal() {
        deleteByInterval("ai_cancel_signal", "created_at", aiCancelSignalRetainDays);
    }

    private void cleanupRuleCancelSignal() {
        deleteByInterval("rule_cancel_signal", "created_at", ruleCancelSignalRetainDays);
    }

    /** 스코어링 시점 데이터 신선도 감사 로그 – 기본 3일 보관 후 삭제(운영 감사용, 장기 보관 불필요). */
    private void cleanupSignalDataFreshnessLog() {
        deleteByInterval("signal_data_freshness_log", "created_at", signalDataFreshnessLogRetainDays);
    }

    private void cleanupOvernightEvaluations() {
        OffsetDateTime cutoff = KstClock.nowOffset().minusDays(Math.max(overnightEvaluationRetainDays, 0));
        try {
            int deleted = jdbcTemplate.update(
                    "DELETE FROM overnight_evaluations WHERE evaluated_at < ?",
                    cutoff
            );
            log.info("[DataCleanup] overnight_evaluations deleted={} cutoff={}", deleted, cutoff);
        } catch (Exception e) {
            log.error("[DataCleanup] overnight_evaluations cleanup failed: {}", e.getMessage(), e);
        }
    }

    private void cleanupInactiveKiwoomTokens() {
        var cutoff = KstClock.now().minusDays(Math.max(inactiveTokenRetainDays, 0));
        try {
            int deleted = jdbcTemplate.update(
                    "DELETE FROM kiwoom_tokens WHERE is_active = FALSE AND updated_at < ?",
                    cutoff
            );
            log.info("[DataCleanup] inactive kiwoom_tokens deleted={} cutoff={}", deleted, cutoff);
        } catch (Exception e) {
            log.error("[DataCleanup] kiwoom_tokens cleanup failed: {}", e.getMessage(), e);
        }
    }

    private void deleteByInterval(String tableName, String columnName, int retainDays) {
        int safeRetainDays = Math.max(retainDays, 0);
        String sql = String.format(
                "DELETE FROM %s WHERE %s < NOW() - (? * INTERVAL '1 day')",
                tableName,
                columnName
        );
        try {
            int deleted = jdbcTemplate.update(sql, safeRetainDays);
            log.info("[DataCleanup] {} deleted={} retainDays={}", tableName, deleted, safeRetainDays);
        } catch (Exception e) {
            log.error("[DataCleanup] {} cleanup failed: {}", tableName, e.getMessage(), e);
        }
    }

    private void cleanupLogFiles() {
        if (!logFileCleanupEnabled) {
            log.info("[DataCleanup] log file cleanup skipped");
            return;
        }

        Path root = Path.of(logDirectory).toAbsolutePath().normalize();
        OffsetDateTime cutoff = KstClock.nowOffset().minusDays(Math.max(logRetainDays, 0));
        Instant cutoffInstant = cutoff.toInstant();
        long deletedFiles = 0;
        long deletedBytes = 0;

        if (!Files.isDirectory(root)) {
            log.info("[DataCleanup] log directory missing path={}", root);
            return;
        }

        try (Stream<Path> paths = Files.walk(root)) {
            for (Path path : paths.filter(Files::isRegularFile).toList()) {
                if (!isCleanupTarget(path)) {
                    continue;
                }
                try {
                    Instant lastModified = Files.getLastModifiedTime(path).toInstant();
                    if (lastModified.isAfter(cutoffInstant)) {
                        continue;
                    }
                    long size = Files.size(path);
                    Files.deleteIfExists(path);
                    deletedFiles++;
                    deletedBytes += size;
                } catch (IOException e) {
                    log.warn("[DataCleanup] log file delete failed path={} cause={}", path, e.getMessage());
                }
            }
            log.info("[DataCleanup] log files deleted={} bytes={} cutoff={}", deletedFiles, deletedBytes, cutoff);
        } catch (IOException e) {
            log.error("[DataCleanup] log file cleanup failed root={} cause={}", root, e.getMessage(), e);
        }
    }

    private boolean isCleanupTarget(Path path) {
        String name = path.getFileName().toString().toLowerCase();
        return name.endsWith(".log")
                || name.endsWith(".out")
                || name.endsWith(".err")
                || name.endsWith(".pid");
    }
}
