-- V41: Prepare ws_tick_data retention and shadow analytics schema.
-- This migration does not drop, rename, or rewrite the existing ws_tick_data table.

CREATE SEQUENCE IF NOT EXISTS ws_tick_data_seq INCREMENT BY 200;

ALTER TABLE ws_tick_data
    ADD COLUMN IF NOT EXISTS must_persist BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_tick_must_persist_created
    ON ws_tick_data(must_persist, created_at);

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

CREATE TABLE IF NOT EXISTS ws_tick_data_summary (
    id BIGSERIAL PRIMARY KEY,
    bucket_started_at TIMESTAMPTZ NOT NULL,
    bucket_minutes INTEGER NOT NULL,
    stk_cd VARCHAR(20) NOT NULL,
    tick_type VARCHAR(4),
    sample_count BIGINT NOT NULL DEFAULT 0,
    open_prc FLOAT8,
    high_prc FLOAT8,
    low_prc FLOAT8,
    close_prc FLOAT8,
    avg_flu_rt FLOAT8,
    max_acc_trde_qty BIGINT,
    max_acc_trde_prica BIGINT,
    avg_cntr_str FLOAT8,
    avg_bid_ask_ratio FLOAT8,
    must_persist BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bucket_started_at, bucket_minutes, stk_cd, tick_type)
);

CREATE INDEX IF NOT EXISTS idx_tick_summary_stk_bucket
    ON ws_tick_data_summary(stk_cd, bucket_started_at);

CREATE INDEX IF NOT EXISTS idx_tick_summary_must_persist_bucket
    ON ws_tick_data_summary(must_persist, bucket_started_at);

CREATE TABLE IF NOT EXISTS ws_tick_feature_snapshot (
    id BIGSERIAL PRIMARY KEY,
    stk_cd VARCHAR(20) NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    source_bucket_minutes INTEGER,
    cur_prc FLOAT8,
    flu_rt FLOAT8,
    acc_trde_qty BIGINT,
    acc_trde_prica BIGINT,
    cntr_str FLOAT8,
    bid_ask_ratio FLOAT8,
    feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    must_persist BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (stk_cd, snapshot_at)
);

CREATE INDEX IF NOT EXISTS idx_tick_feature_snapshot_at
    ON ws_tick_feature_snapshot(snapshot_at);

CREATE INDEX IF NOT EXISTS idx_tick_feature_must_persist_snapshot
    ON ws_tick_feature_snapshot(must_persist, snapshot_at);

COMMENT ON TABLE ws_tick_data_partitioned IS 'Shadow partition target for future ws_tick_data migration. Existing ws_tick_data remains unchanged.';
COMMENT ON TABLE ws_tick_data_summary IS 'Aggregated ws tick buckets prepared for retention-safe cleanup.';
COMMENT ON TABLE ws_tick_feature_snapshot IS 'Feature snapshots derived from ws ticks for scoring/audit.';
COMMENT ON COLUMN ws_tick_data.must_persist IS 'Retention guard. Cleanup deletes only rows where this is false and cleanup is explicitly enabled.';
