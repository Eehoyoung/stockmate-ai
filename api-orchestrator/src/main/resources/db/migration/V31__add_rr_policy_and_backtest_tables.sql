ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS raw_rr NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS single_tp_rr NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS effective_rr NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS min_rr_ratio NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS rr_skip_reason TEXT,
    ADD COLUMN IF NOT EXISTS stop_max_pct NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS tp_policy_version VARCHAR(40),
    ADD COLUMN IF NOT EXISTS sl_policy_version VARCHAR(40),
    ADD COLUMN IF NOT EXISTS exit_policy_version VARCHAR(40),
    ADD COLUMN IF NOT EXISTS allow_overnight BOOLEAN,
    ADD COLUMN IF NOT EXISTS allow_reentry BOOLEAN,
    ADD COLUMN IF NOT EXISTS trailing_stop_price NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS time_stop_deadline_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ts_effective_rr
    ON trading_signals (strategy, created_at, effective_rr);

CREATE TABLE IF NOT EXISTS position_state_events (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,
    event_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    position_status VARCHAR(20),
    peak_price NUMERIC(10,0),
    trailing_stop_price NUMERIC(10,0),
    payload JSONB
);

CREATE INDEX IF NOT EXISTS idx_position_state_events_signal_ts
    ON position_state_events (signal_id, event_ts DESC);

CREATE TABLE IF NOT EXISTS trade_plans (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    strategy_code VARCHAR(30) NOT NULL,
    strategy_version VARCHAR(40),
    plan_name VARCHAR(50) NOT NULL DEFAULT 'primary',
    tp_model VARCHAR(50),
    sl_model VARCHAR(50),
    tp_price NUMERIC(10,0),
    sl_price NUMERIC(10,0),
    tp_pct NUMERIC(7,3),
    sl_pct NUMERIC(7,3),
    planned_rr NUMERIC(6,3),
    effective_rr NUMERIC(6,3),
    time_stop_type VARCHAR(30),
    time_stop_minutes INTEGER,
    time_stop_session VARCHAR(30),
    trailing_rule VARCHAR(50),
    partial_tp_rule VARCHAR(50),
    planned_exit_priority VARCHAR(50),
    variant_rank INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_plans_signal
    ON trade_plans (signal_id, variant_rank);

CREATE TABLE IF NOT EXISTS trade_path_bars (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    plan_id BIGINT REFERENCES trade_plans(id) ON DELETE CASCADE,
    bar_ts TIMESTAMPTZ NOT NULL,
    open_price NUMERIC(10,0),
    high_price NUMERIC(10,0),
    low_price NUMERIC(10,0),
    close_price NUMERIC(10,0),
    volume BIGINT,
    tp_touch_flag BOOLEAN DEFAULT FALSE,
    sl_touch_flag BOOLEAN DEFAULT FALSE,
    first_hit_event VARCHAR(20),
    bars_to_tp INTEGER,
    bars_to_sl INTEGER,
    mfe_rr NUMERIC(6,3),
    mae_rr NUMERIC(6,3),
    max_favorable_price NUMERIC(10,0),
    max_adverse_price NUMERIC(10,0)
);

CREATE INDEX IF NOT EXISTS idx_trade_path_bars_signal_ts
    ON trade_path_bars (signal_id, bar_ts);

CREATE TABLE IF NOT EXISTS trade_outcomes (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    plan_id BIGINT REFERENCES trade_plans(id) ON DELETE CASCADE,
    exit_reason VARCHAR(20) NOT NULL,
    exit_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_price NUMERIC(10,0),
    filled_qty INTEGER,
    realized_rr_gross NUMERIC(6,3),
    realized_rr_net NUMERIC(6,3),
    realized_pnl NUMERIC(14,2),
    tp_hit_before_sl_flag BOOLEAN,
    tp_reached_within_horizon_flag BOOLEAN,
    timeout_flag BOOLEAN DEFAULT FALSE,
    touch_mode VARCHAR(20),
    execution_quality_flag VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_trade_outcomes_signal
    ON trade_outcomes (signal_id, exit_ts DESC);

CREATE TABLE IF NOT EXISTS strategy_bucket_stats (
    id BIGSERIAL PRIMARY KEY,
    strategy_code VARCHAR(30) NOT NULL,
    strategy_version VARCHAR(40),
    bucket_key VARCHAR(120) NOT NULL,
    tp_level VARCHAR(40),
    sl_level VARCHAR(40),
    n_signals INTEGER NOT NULL DEFAULT 0,
    tp_hit_count INTEGER NOT NULL DEFAULT 0,
    sl_hit_count INTEGER NOT NULL DEFAULT 0,
    timeout_count INTEGER NOT NULL DEFAULT 0,
    hit_rate_raw NUMERIC(7,4),
    hit_rate_bayes NUMERIC(7,4),
    avg_realized_rr NUMERIC(6,3),
    median_realized_rr NUMERIC(6,3),
    p10_rr NUMERIC(6,3),
    p90_rr NUMERIC(6,3),
    expectancy_rr NUMERIC(6,3),
    profit_factor NUMERIC(8,3),
    calibration_error NUMERIC(7,4),
    ci_lower NUMERIC(7,4),
    ci_upper NUMERIC(7,4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategy_bucket_stats UNIQUE (strategy_code, strategy_version, bucket_key, tp_level, sl_level)
);
