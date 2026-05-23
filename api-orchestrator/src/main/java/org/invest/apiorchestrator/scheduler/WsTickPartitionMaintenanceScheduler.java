package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class WsTickPartitionMaintenanceScheduler {

    private final JdbcTemplate jdbcTemplate;

    @Value("${maintenance.ws-tick-partitions.enabled:true}")
    private boolean partitionCreationEnabled;

    @Value("${maintenance.ws-tick-partitions.days-ahead:14}")
    private int partitionDaysAhead;

    @Value("${maintenance.ws-tick-legacy-backfill.enabled:false}")
    private boolean legacyBackfillEnabled;

    @Value("${maintenance.ws-tick-legacy-backfill.batch-size:100000}")
    private int legacyBackfillBatchSize;

    @Value("${maintenance.ws-tick-legacy-backfill.cutoff-hours:1}")
    private int legacyBackfillCutoffHours;

    @Value("${maintenance.ws-tick-legacy-backfill.delete-after-copy:false}")
    private boolean legacyDeleteAfterCopy;

    @Value("${maintenance.ws-tick-retention.enabled:false}")
    private boolean retentionEnabled;

    @Value("${maintenance.ws-tick-retention.retain-days:3}")
    private int retentionDays;

    @Value("${maintenance.ws-tick-retention.dry-run:true}")
    private boolean retentionDryRun;

    @Scheduled(cron = "${maintenance.ws-tick-partitions.cron:0 10 6 * * *}", zone = "Asia/Seoul")
    public void createUpcomingPartitions() {
        if (!partitionCreationEnabled) {
            log.debug("[WsTickMaintenance] partition creation skipped: disabled");
            return;
        }

        try {
            Integer created = jdbcTemplate.queryForObject(
                    "SELECT ws_tick_data_create_daily_partitions(NULL, ?)",
                    Integer.class,
                    Math.max(partitionDaysAhead, 0)
            );
            log.info("[WsTickMaintenance] partition precreate complete created={} daysAhead={}",
                    created, partitionDaysAhead);
        } catch (Exception e) {
            log.error("[WsTickMaintenance] partition precreate failed: {}", e.getMessage(), e);
        }
    }

    @Scheduled(cron = "${maintenance.ws-tick-legacy-backfill.cron:0 */10 0-6,16-23 * * *}", zone = "Asia/Seoul")
    public void backfillLegacyWsTickData() {
        if (!legacyBackfillEnabled) {
            log.debug("[WsTickMaintenance] legacy backfill skipped: disabled");
            return;
        }

        try {
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                    """
                    SELECT *
                      FROM ws_tick_data_backfill_legacy_batch(
                          ?,
                          NOW() - (? * INTERVAL '1 hour'),
                          ?
                      )
                    """,
                    Math.max(legacyBackfillBatchSize, 1),
                    Math.max(legacyBackfillCutoffHours, 0),
                    legacyDeleteAfterCopy
            );
            Map<String, Object> row = rows.isEmpty() ? Map.of() : rows.get(0);
            log.info("[WsTickMaintenance] legacy backfill batch result {}", row);

            if (legacyDeleteAfterCopy) {
                List<Map<String, Object>> deletedRows = jdbcTemplate.queryForList(
                        """
                        SELECT *
                          FROM ws_tick_data_delete_copied_legacy_batch(
                              ?,
                              NOW() - (? * INTERVAL '1 hour')
                          )
                        """,
                        Math.max(legacyBackfillBatchSize, 1),
                        Math.max(legacyBackfillCutoffHours, 0)
                );
                log.info("[WsTickMaintenance] copied legacy cleanup result {}",
                        deletedRows.isEmpty() ? Map.of() : deletedRows.get(0));
            }
        } catch (Exception e) {
            log.error("[WsTickMaintenance] legacy backfill failed: {}", e.getMessage(), e);
        }
    }

    @Scheduled(cron = "${maintenance.ws-tick-retention.cron:0 50 23 * * *}", zone = "Asia/Seoul")
    public void applyPartitionRetention() {
        if (!retentionEnabled) {
            log.debug("[WsTickMaintenance] partition retention skipped: disabled");
            return;
        }

        try {
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                    "SELECT * FROM ws_tick_data_retention_policy(?, ?)",
                    Math.max(retentionDays, 0),
                    retentionDryRun
            );
            log.info("[WsTickMaintenance] partition retention result dryRun={} rows={}",
                    retentionDryRun, rows);
        } catch (Exception e) {
            log.error("[WsTickMaintenance] partition retention failed: {}", e.getMessage(), e);
        }
    }
}
