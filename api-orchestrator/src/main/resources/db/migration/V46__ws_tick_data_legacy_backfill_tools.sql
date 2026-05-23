-- V46: Online tools for migrating legacy ws_tick_data heap rows into
-- ws_tick_data_partitioned.
--
-- This migration installs idempotent helper functions only. It does not copy or
-- delete historical rows during migration startup.

ALTER TABLE ws_tick_data_partitioned
    ADD COLUMN IF NOT EXISTS legacy_ws_tick_data_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_tick_part_legacy_ws_tick_data_id
    ON ws_tick_data_partitioned(legacy_ws_tick_data_id)
    WHERE legacy_ws_tick_data_id IS NOT NULL;

CREATE OR REPLACE FUNCTION ws_tick_data_legacy_backfill_status()
RETURNS TABLE(metric TEXT, value BIGINT)
LANGUAGE sql
AS $$
    SELECT 'legacy_total_rows', COUNT(*)::BIGINT
      FROM ws_tick_data
    UNION ALL
    SELECT 'partition_rows_from_legacy', COUNT(*)::BIGINT
      FROM ws_tick_data_partitioned
     WHERE legacy_ws_tick_data_id IS NOT NULL
    UNION ALL
    SELECT 'legacy_remaining_unmigrated', COUNT(*)::BIGINT
      FROM ws_tick_data w
     WHERE NOT EXISTS (
           SELECT 1
             FROM ws_tick_data_partitioned p
            WHERE p.legacy_ws_tick_data_id = w.id
     );
$$;

CREATE OR REPLACE FUNCTION ws_tick_data_backfill_legacy_batch(
    batch_size INTEGER DEFAULT 100000,
    before_at TIMESTAMPTZ DEFAULT NOW(),
    delete_after_copy BOOLEAN DEFAULT FALSE
)
RETURNS TABLE(
    selected_rows BIGINT,
    inserted_rows BIGINT,
    deleted_rows BIGINT,
    min_legacy_id BIGINT,
    max_legacy_id BIGINT,
    min_created_at TIMESTAMPTZ,
    max_created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
AS $$
DECLARE
    copied_count BIGINT := 0;
    removed_count BIGINT := 0;
    first_day DATE;
BEGIN
    IF batch_size IS NULL OR batch_size <= 0 THEN
        RAISE EXCEPTION 'batch_size must be positive';
    END IF;

    DROP TABLE IF EXISTS pg_temp.tmp_ws_tick_data_legacy_batch;

    CREATE TEMP TABLE tmp_ws_tick_data_legacy_batch ON COMMIT DROP AS
    SELECT w.*
      FROM ws_tick_data w
     WHERE w.created_at < before_at
       AND NOT EXISTS (
             SELECT 1
               FROM ws_tick_data_partitioned p
              WHERE p.legacy_ws_tick_data_id = w.id
       )
     ORDER BY w.id
     LIMIT batch_size;

    SELECT COUNT(*)::BIGINT,
           MIN(id),
           MAX(id),
           MIN(created_at),
           MAX(created_at),
           MIN((created_at AT TIME ZONE 'Asia/Seoul')::DATE)
      INTO selected_rows,
           min_legacy_id,
           max_legacy_id,
           min_created_at,
           max_created_at,
           first_day
      FROM tmp_ws_tick_data_legacy_batch;

    IF selected_rows = 0 THEN
        inserted_rows := 0;
        deleted_rows := 0;
        RETURN NEXT;
        RETURN;
    END IF;

    PERFORM ws_tick_data_create_daily_partitions(first_day, 14);

    INSERT INTO ws_tick_data_partitioned (
        legacy_ws_tick_data_id,
        stk_cd,
        cur_prc,
        pred_pre,
        flu_rt,
        acc_trde_qty,
        acc_trde_prica,
        cntr_str,
        total_bid_qty,
        total_ask_qty,
        bid_ask_ratio,
        tick_type,
        must_persist,
        source_created_at,
        created_at
    )
    SELECT t.id,
           t.stk_cd,
           t.cur_prc,
           t.pred_pre,
           t.flu_rt,
           t.acc_trde_qty,
           t.acc_trde_prica,
           t.cntr_str,
           t.total_bid_qty,
           t.total_ask_qty,
           t.bid_ask_ratio,
           t.tick_type,
           COALESCE(t.must_persist, FALSE),
           t.created_at,
           t.created_at
      FROM tmp_ws_tick_data_legacy_batch t
     WHERE NOT EXISTS (
           SELECT 1
             FROM ws_tick_data_partitioned p
            WHERE p.legacy_ws_tick_data_id = t.id
     );

    GET DIAGNOSTICS copied_count = ROW_COUNT;

    IF delete_after_copy THEN
        DELETE FROM ws_tick_data w
        USING tmp_ws_tick_data_legacy_batch t
        WHERE w.id = t.id
          AND EXISTS (
                SELECT 1
                  FROM ws_tick_data_partitioned p
                 WHERE p.legacy_ws_tick_data_id = w.id
          );
        GET DIAGNOSTICS removed_count = ROW_COUNT;
    END IF;

    inserted_rows := copied_count;
    deleted_rows := removed_count;
    RETURN NEXT;
END;
$$;

COMMENT ON COLUMN ws_tick_data_partitioned.legacy_ws_tick_data_id IS
    'Original ws_tick_data.id when copied from the legacy heap table. Used for idempotent online backfill.';
COMMENT ON FUNCTION ws_tick_data_legacy_backfill_status() IS
    'Returns coarse legacy heap to partition migration counts. The remaining count can be expensive on large tables.';
COMMENT ON FUNCTION ws_tick_data_backfill_legacy_batch(INTEGER, TIMESTAMPTZ, BOOLEAN) IS
    'Copies one idempotent batch from legacy ws_tick_data to ws_tick_data_partitioned. Set delete_after_copy=true only after validating copied rows.';

CREATE OR REPLACE FUNCTION ws_tick_data_delete_copied_legacy_batch(
    batch_size INTEGER DEFAULT 100000,
    before_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS TABLE(
    selected_rows BIGINT,
    deleted_rows BIGINT,
    min_legacy_id BIGINT,
    max_legacy_id BIGINT,
    min_created_at TIMESTAMPTZ,
    max_created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
AS $$
DECLARE
    removed_count BIGINT := 0;
BEGIN
    IF batch_size IS NULL OR batch_size <= 0 THEN
        RAISE EXCEPTION 'batch_size must be positive';
    END IF;

    DROP TABLE IF EXISTS pg_temp.tmp_ws_tick_data_delete_copied;

    CREATE TEMP TABLE tmp_ws_tick_data_delete_copied ON COMMIT DROP AS
    SELECT w.id, w.created_at
      FROM ws_tick_data w
     WHERE w.created_at < before_at
       AND EXISTS (
             SELECT 1
               FROM ws_tick_data_partitioned p
              WHERE p.legacy_ws_tick_data_id = w.id
       )
     ORDER BY w.id
     LIMIT batch_size;

    SELECT COUNT(*)::BIGINT,
           MIN(id),
           MAX(id),
           MIN(created_at),
           MAX(created_at)
      INTO selected_rows,
           min_legacy_id,
           max_legacy_id,
           min_created_at,
           max_created_at
      FROM tmp_ws_tick_data_delete_copied;

    IF selected_rows = 0 THEN
        deleted_rows := 0;
        RETURN NEXT;
        RETURN;
    END IF;

    DELETE FROM ws_tick_data w
    USING tmp_ws_tick_data_delete_copied t
    WHERE w.id = t.id;

    GET DIAGNOSTICS removed_count = ROW_COUNT;
    deleted_rows := removed_count;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION ws_tick_data_delete_copied_legacy_batch(INTEGER, TIMESTAMPTZ) IS
    'Deletes one batch from legacy ws_tick_data only when the row is already present in ws_tick_data_partitioned by legacy_ws_tick_data_id.';
