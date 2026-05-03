-- V42: Shadow trading ledger for simulated trade path reporting.
-- One row is kept per ENTER signal so later reports can analyze entry quality,
-- excursion, exit reason, latency, and data quality without parsing logs.

CREATE TABLE IF NOT EXISTS shadow_trades (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    strategy VARCHAR(30) NOT NULL,
    stk_cd VARCHAR(20),
    stk_nm VARCHAR(100),
    entry_price NUMERIC(10,0) NOT NULL,
    tp1_price NUMERIC(10,0),
    tp2_price NUMERIC(10,0),
    sl_price NUMERIC(10,0),
    signal_time TIMESTAMPTZ NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    max_favorable_excursion NUMERIC(8,4) NOT NULL DEFAULT 0,
    max_adverse_excursion NUMERIC(8,4) NOT NULL DEFAULT 0,
    max_favorable_price NUMERIC(10,0),
    max_adverse_price NUMERIC(10,0),
    last_price NUMERIC(10,0),
    result VARCHAR(20),
    realized_pnl_simulated NUMERIC(8,4),
    exit_reason VARCHAR(40),
    latency_ms INTEGER,
    data_quality VARCHAR(20),
    data_quality_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_shadow_trades_signal UNIQUE (signal_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_trades_strategy_time
    ON shadow_trades(strategy, signal_time DESC);

CREATE INDEX IF NOT EXISTS idx_shadow_trades_status_updated
    ON shadow_trades(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_shadow_trades_result_time
    ON shadow_trades(result, signal_time DESC);

COMMENT ON TABLE shadow_trades IS 'Per-signal shadow trading ledger for simulated entry, path excursion, exit, latency, and data quality reporting.';
COMMENT ON COLUMN shadow_trades.max_favorable_excursion IS 'Best unrealized move from entry, stored as percentage points.';
COMMENT ON COLUMN shadow_trades.max_adverse_excursion IS 'Worst unrealized move from entry, stored as percentage points; normally zero or negative.';
COMMENT ON COLUMN shadow_trades.realized_pnl_simulated IS 'Simulated realized PnL percentage at shadow close.';
