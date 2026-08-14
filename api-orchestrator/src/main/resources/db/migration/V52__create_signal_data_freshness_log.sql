CREATE TABLE IF NOT EXISTS signal_data_freshness_log (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NULL REFERENCES trading_signals(id) ON DELETE SET NULL,
    stk_cd VARCHAR(20) NOT NULL,
    strategy VARCHAR(30) NOT NULL,
    action VARCHAR(20),
    freshness_status VARCHAR(20),
    tick_state VARCHAR(20),
    tick_source VARCHAR(20),
    tick_age_ms INTEGER,
    hoga_state VARCHAR(20),
    hoga_source VARCHAR(20),
    hoga_age_ms INTEGER,
    strength_state VARCHAR(20),
    strength_source VARCHAR(20),
    strength_age_ms INTEGER,
    vi_state VARCHAR(20),
    vi_source VARCHAR(20),
    vi_age_ms INTEGER,
    rest_fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    rest_fallback_fields JSONB,
    rest_failure_classes JSONB,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_data_freshness_log_signal_id
    ON signal_data_freshness_log(signal_id);

CREATE INDEX IF NOT EXISTS idx_signal_data_freshness_log_strategy_created_at
    ON signal_data_freshness_log(strategy, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_data_freshness_log_stk_cd_created_at
    ON signal_data_freshness_log(stk_cd, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_data_freshness_log_created_at
    ON signal_data_freshness_log(created_at);
