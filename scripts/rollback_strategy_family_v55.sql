-- MANUAL, DESTRUCTIVE rollback for V55 metadata only.
-- Do not execute while family routing is enabled or before exporting the eight
-- columns below.  Normal operational rollback requires only setting
-- ENABLE_STRATEGY_FAMILY_LINEAGE=false and returning to the baseline branch.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM trading_signals
        WHERE strategy_family IS NOT NULL
          AND family_policy_version IS DISTINCT FROM 'family_v1_2026_08_16'
    ) THEN
        RAISE EXCEPTION 'rollback refused: unknown family policy data exists';
    END IF;
END $$;

DROP INDEX IF EXISTS idx_ts_primary_setup_created;
DROP INDEX IF EXISTS idx_ts_family_created;

ALTER TABLE trading_signals
    DROP CONSTRAINT IF EXISTS trading_signals_strategy_family_check,
    DROP COLUMN IF EXISTS final_score,
    DROP COLUMN IF EXISTS degraded_reasons,
    DROP COLUMN IF EXISTS blocking_reasons,
    DROP COLUMN IF EXISTS family_policy_version,
    DROP COLUMN IF EXISTS matched_setup_ids,
    DROP COLUMN IF EXISTS primary_setup_id,
    DROP COLUMN IF EXISTS strategy_family_name,
    DROP COLUMN IF EXISTS strategy_family;

-- Flyway history is intentionally not mutated here.  If a full downgrade is
-- required, restore the pre-migration database backup instead of editing the
-- schema history by hand.
COMMIT;
