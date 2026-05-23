-- V45: Activate real partition support for ws_tick_data event writes.
--
-- Online-safety policy:
--   * Do not rename/drop/rewrite the legacy ws_tick_data heap table.
--   * Keep the V41 partition target and default partition so writers never fail
--     only because a daily partition is missing.
--   * Retention is exposed as an opt-in dry-run-first function. This migration
--     installs the path/policy but does not delete historical data.

CREATE SEQUENCE IF NOT EXISTS ws_tick_data_seq INCREMENT BY 200;

CREATE TABLE IF NOT EXISTS ws_tick_data_partitioned (
    id BIGINT NOT NULL DEFAULT nextval('ws_tick_data_seq'),
    stk_cd VARCHAR(20) NOT NULL,
    cur_prc FLOAT8,
    pred_pre FLOAT8,
    flu_rt FLOAT8,
    acc_trde_qty BIGINT,
    acc_trde_prica BIGINT,
    cntr_str FLOAT8,
    total_bid_qty BIGINT,
    total_ask_qty BIGINT,
    bid_ask_ratio FLOAT8,
    tick_type VARCHAR(4),
    must_persist BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS ws_tick_data_partitioned_default
    PARTITION OF ws_tick_data_partitioned DEFAULT;

CREATE INDEX IF NOT EXISTS idx_tick_part_stk_cd_created
    ON ws_tick_data_partitioned(stk_cd, created_at);

CREATE INDEX IF NOT EXISTS idx_tick_part_type_created
    ON ws_tick_data_partitioned(tick_type, created_at);

CREATE INDEX IF NOT EXISTS idx_tick_part_must_persist_created
    ON ws_tick_data_partitioned(must_persist, created_at);

CREATE OR REPLACE FUNCTION ws_tick_data_create_daily_partitions(
    start_on DATE DEFAULT NULL,
    days_ahead INTEGER DEFAULT 14
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    base_day DATE := COALESCE(start_on, ((NOW() AT TIME ZONE 'Asia/Seoul')::DATE - 2));
    end_day DATE := ((NOW() AT TIME ZONE 'Asia/Seoul')::DATE + GREATEST(days_ahead, 0));
    part_day DATE;
    part_name TEXT;
    lower_bound TIMESTAMPTZ;
    upper_bound TIMESTAMPTZ;
    created_count INTEGER := 0;
BEGIN
    IF base_day > end_day THEN
        RAISE EXCEPTION 'start_on (%) must be on or before computed end day (%)', base_day, end_day;
    END IF;

    FOR part_day IN
        SELECT generate_series(base_day, end_day, INTERVAL '1 day')::DATE
    LOOP
        part_name := format('ws_tick_data_p_%s', to_char(part_day, 'YYYYMMDD'));
        lower_bound := part_day::TIMESTAMP AT TIME ZONE 'Asia/Seoul';
        upper_bound := (part_day + 1)::TIMESTAMP AT TIME ZONE 'Asia/Seoul';

        IF to_regclass('public.' || part_name) IS NULL THEN
            BEGIN
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF public.ws_tick_data_partitioned FOR VALUES FROM (%L) TO (%L)',
                    part_name,
                    lower_bound,
                    upper_bound
                );
                created_count := created_count + 1;
            EXCEPTION
                WHEN check_violation OR exclusion_violation THEN
                    RAISE NOTICE
                        'Skipped creating partition %. Move matching rows out of ws_tick_data_partitioned_default first.',
                        part_name;
                WHEN duplicate_table THEN
                    NULL;
            END;
        END IF;
    END LOOP;

    RETURN created_count;
END;
$$;

CREATE OR REPLACE FUNCTION ws_tick_data_retention_policy(
    retain_days INTEGER DEFAULT 3,
    dry_run BOOLEAN DEFAULT TRUE
)
RETURNS TABLE(action TEXT, object_name TEXT, affected_rows BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff_day DATE := ((NOW() AT TIME ZONE 'Asia/Seoul')::DATE - GREATEST(retain_days, 0));
    cutoff_at TIMESTAMPTZ := cutoff_day::TIMESTAMP AT TIME ZONE 'Asia/Seoul';
    part RECORD;
    part_day DATE;
    has_guarded_rows BOOLEAN;
    row_count BIGINT;
BEGIN
    FOR part IN
        SELECT c.oid::REGCLASS AS relation_name, c.relname
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE p.oid = 'public.ws_tick_data_partitioned'::REGCLASS
          AND n.nspname = 'public'
          AND c.relname ~ '^ws_tick_data_p_[0-9]{8}$'
        ORDER BY c.relname
    LOOP
        part_day := to_date(substring(part.relname FROM '([0-9]{8})$'), 'YYYYMMDD');
        IF part_day >= cutoff_day THEN
            CONTINUE;
        END IF;

        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s WHERE must_persist LIMIT 1)', part.relation_name)
            INTO has_guarded_rows;

        IF dry_run THEN
            IF has_guarded_rows THEN
                action := 'would_delete_unpersisted_from_guarded_partition';
            ELSE
                action := 'would_drop_partition';
            END IF;
            object_name := part.relation_name::TEXT;
            affected_rows := NULL;
            RETURN NEXT;
        ELSIF has_guarded_rows THEN
            EXECUTE format(
                'DELETE FROM %s WHERE must_persist = FALSE AND created_at < %L',
                part.relation_name,
                cutoff_at
            );
            GET DIAGNOSTICS row_count = ROW_COUNT;
            action := 'deleted_unpersisted_from_guarded_partition';
            object_name := part.relation_name::TEXT;
            affected_rows := row_count;
            RETURN NEXT;
        ELSE
            EXECUTE format('DROP TABLE %s', part.relation_name);
            action := 'dropped_partition';
            object_name := part.relation_name::TEXT;
            affected_rows := 0;
            RETURN NEXT;
        END IF;
    END LOOP;

    IF to_regclass('public.ws_tick_data_partitioned_default') IS NOT NULL THEN
        IF dry_run THEN
            EXECUTE
                'SELECT COUNT(*) FROM public.ws_tick_data_partitioned_default WHERE must_persist = FALSE AND created_at < $1'
                USING cutoff_at
                INTO row_count;
            action := 'would_delete_from_default_partition';
            object_name := 'public.ws_tick_data_partitioned_default';
            affected_rows := row_count;
            RETURN NEXT;
        ELSE
            DELETE FROM public.ws_tick_data_partitioned_default
            WHERE must_persist = FALSE
              AND created_at < cutoff_at;
            GET DIAGNOSTICS row_count = ROW_COUNT;
            action := 'deleted_from_default_partition';
            object_name := 'public.ws_tick_data_partitioned_default';
            affected_rows := row_count;
            RETURN NEXT;
        END IF;
    END IF;
END;
$$;

-- Pre-create a small rolling window. If a default partition already contains
-- overlapping rows, the helper logs a notice and leaves the default partition as
-- the safe catch-all rather than blocking deployment.
SELECT ws_tick_data_create_daily_partitions(NULL, 14);

COMMENT ON TABLE ws_tick_data_partitioned IS
    'Primary websocket tick event write target. Daily RANGE partitions are created by ws_tick_data_create_daily_partitions.';
COMMENT ON FUNCTION ws_tick_data_create_daily_partitions(DATE, INTEGER) IS
    'Creates KST daily ws_tick_data_partitioned partitions from start_on (or KST today - 2) through KST today + days_ahead.';
COMMENT ON FUNCTION ws_tick_data_retention_policy(INTEGER, BOOLEAN) IS
    'Dry-run-first retention helper. With dry_run=false, drops old unguarded daily partitions, deletes non-persistent rows from guarded/default partitions, and preserves must_persist=true rows.';
