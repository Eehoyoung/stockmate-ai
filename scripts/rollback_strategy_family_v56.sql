-- MANUAL, DESTRUCTIVE rollback for V56 lineage metadata only.
-- Normal rollback is feature flags OFF; use this only after exporting the data.
-- Run V56 rollback before V55 rollback when physically removing all family columns.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM trading_signals
        WHERE rule_score_version IS NOT NULL
          AND rule_score_version NOT IN ('family_score_v1_2026_08_16', 'legacy_pre_family')
    ) THEN
        RAISE EXCEPTION 'rollback refused: unknown rule score version exists';
    END IF;
    IF EXISTS (
        SELECT 1 FROM trading_signals
        WHERE prompt_version IS NOT NULL
          AND prompt_version NOT IN ('family_prompt_v1_2026_08_16', 'legacy_pre_family')
    ) THEN
        RAISE EXCEPTION 'rollback refused: unknown prompt version exists';
    END IF;
END $$;

DROP INDEX IF EXISTS idx_ts_family_setup_versions;

ALTER TABLE trading_signals
    DROP COLUMN IF EXISTS fallback_reason,
    DROP COLUMN IF EXISTS source_age_ms,
    DROP COLUMN IF EXISTS source_timestamp,
    DROP COLUMN IF EXISTS data_source,
    DROP COLUMN IF EXISTS prompt_version,
    DROP COLUMN IF EXISTS rule_score_version,
    DROP COLUMN IF EXISTS setup_version,
    DROP COLUMN IF EXISTS confirmed_by_family_ids;

-- Flyway history is intentionally untouched. Restore the predeploy DB archive
-- for a complete point-in-time downgrade.
COMMIT;
