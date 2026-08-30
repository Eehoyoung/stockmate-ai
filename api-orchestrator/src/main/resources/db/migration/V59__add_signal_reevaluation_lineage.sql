ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS reevaluation_of_signal_id BIGINT REFERENCES trading_signals(id),
    ADD COLUMN IF NOT EXISTS evaluation_input JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS input_fingerprint VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trading_signal_scan_setup_stock
    ON trading_signals(correlation_id, strategy, stk_cd)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_trading_signal_reevaluation
    ON trading_signals(reevaluation_of_signal_id)
    WHERE reevaluation_of_signal_id IS NOT NULL;

COMMENT ON COLUMN trading_signals.reevaluation_of_signal_id IS
    'Immediately preceding evaluation for the same stock and setup; separate scan runs remain valid history';
