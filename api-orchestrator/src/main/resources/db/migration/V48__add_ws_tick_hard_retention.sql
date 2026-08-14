-- Local-runtime storage policy: raw websocket ticks are disposable after the
-- configured retention window. Derived signals, positions, and performance
-- tables are independent and are not touched by this function.
CREATE OR REPLACE FUNCTION ws_tick_data_hard_retention_policy(
    retain_days INTEGER DEFAULT 3,
    dry_run BOOLEAN DEFAULT TRUE
)
RETURNS TABLE(
    action TEXT,
    object_name TEXT,
    partition_day DATE,
    reclaimed_bytes BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff_day DATE := ((NOW() AT TIME ZONE 'Asia/Seoul')::DATE - GREATEST(retain_days, 0));
    cutoff_at TIMESTAMPTZ := cutoff_day::TIMESTAMP AT TIME ZONE 'Asia/Seoul';
    part RECORD;
    part_day DATE;
    part_bytes BIGINT;
    deleted_rows BIGINT;
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

        part_bytes := pg_total_relation_size(part.relation_name);
        IF dry_run THEN
            action := 'would_drop_partition';
        ELSE
            EXECUTE format('DROP TABLE %s', part.relation_name);
            action := 'dropped_partition';
        END IF;
        object_name := part.relation_name::TEXT;
        partition_day := part_day;
        reclaimed_bytes := part_bytes;
        RETURN NEXT;
    END LOOP;

    IF to_regclass('public.ws_tick_data_partitioned_default') IS NOT NULL THEN
        IF dry_run THEN
            EXECUTE
                'SELECT COUNT(*) FROM public.ws_tick_data_partitioned_default WHERE created_at < $1'
                USING cutoff_at
                INTO deleted_rows;
            action := 'would_delete_from_default_partition';
        ELSE
            DELETE FROM public.ws_tick_data_partitioned_default
             WHERE created_at < cutoff_at;
            GET DIAGNOSTICS deleted_rows = ROW_COUNT;
            action := 'deleted_from_default_partition';
        END IF;
        object_name := 'public.ws_tick_data_partitioned_default';
        partition_day := NULL;
        reclaimed_bytes := 0;
        RETURN NEXT;
    END IF;
END;
$$;

COMMENT ON FUNCTION ws_tick_data_hard_retention_policy(INTEGER, BOOLEAN) IS
    'Drops complete daily raw-tick partitions older than the KST retention window, including must_persist rows. Use only when derived trading records are the retention source of truth.';
