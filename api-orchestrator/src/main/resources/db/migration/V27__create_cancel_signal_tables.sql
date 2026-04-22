CREATE TABLE IF NOT EXISTS ai_cancel_signal (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NULL REFERENCES trading_signals(id) ON DELETE SET NULL,
    stk_cd VARCHAR(20) NOT NULL,
    strategy VARCHAR(30) NOT NULL,
    ai_score NUMERIC(5,2),
    confidence VARCHAR(10),
    reason TEXT,
    cancel_reason TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_cancel_signal_signal_id
    ON ai_cancel_signal(signal_id);

CREATE INDEX IF NOT EXISTS idx_ai_cancel_signal_strategy_created_at
    ON ai_cancel_signal(strategy, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_cancel_signal_stk_cd_created_at
    ON ai_cancel_signal(stk_cd, created_at DESC);

CREATE TABLE IF NOT EXISTS rule_cancel_signal (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NULL REFERENCES trading_signals(id) ON DELETE SET NULL,
    stk_cd VARCHAR(20) NOT NULL,
    strategy VARCHAR(30) NOT NULL,
    rule_score NUMERIC(5,2),
    cancel_type VARCHAR(40) NOT NULL,
    reason TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rule_cancel_signal_signal_id
    ON rule_cancel_signal(signal_id);

CREATE INDEX IF NOT EXISTS idx_rule_cancel_signal_strategy_created_at
    ON rule_cancel_signal(strategy, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rule_cancel_signal_stk_cd_created_at
    ON rule_cancel_signal(stk_cd, created_at DESC);
