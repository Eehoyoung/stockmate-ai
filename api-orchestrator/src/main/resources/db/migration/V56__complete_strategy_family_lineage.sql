-- Complete the versioned/source lineage contract without replacing legacy S setup ids.

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS confirmed_by_family_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS setup_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS rule_score_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS data_source JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_timestamp JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_age_ms JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS fallback_reason JSONB NOT NULL DEFAULT '[]'::jsonb;

UPDATE trading_signals
SET setup_version = COALESCE(setup_version, strategy_version, 'legacy_pre_family'),
    rule_score_version = COALESCE(rule_score_version, 'legacy_pre_family'),
    prompt_version = COALESCE(prompt_version, 'legacy_pre_family')
WHERE setup_version IS NULL
   OR rule_score_version IS NULL
   OR prompt_version IS NULL;

CREATE INDEX IF NOT EXISTS idx_ts_family_setup_versions
    ON trading_signals(strategy_family, setup_version, rule_score_version, created_at DESC);

COMMENT ON COLUMN trading_signals.confirmed_by_family_ids IS
    'Independent confirming G families; never a quantity multiplier';
COMMENT ON COLUMN trading_signals.data_source IS
    'Per-field authoritative source snapshot; Kiwoom and Toss values are never averaged';
COMMENT ON COLUMN trading_signals.source_timestamp IS
    'Per-field source observed/updated timestamp snapshot';
COMMENT ON COLUMN trading_signals.source_age_ms IS
    'Per-field source age in milliseconds; TTL existence is not freshness';
COMMENT ON COLUMN trading_signals.fallback_reason IS
    'Fallback/degraded reasons retained for decision audit';
