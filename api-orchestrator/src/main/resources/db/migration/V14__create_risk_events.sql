-- V14: risk_events — 리스크 한도 위반 로그

CREATE TABLE IF NOT EXISTS risk_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(30) NOT NULL,
    -- DAILY_LOSS_LIMIT / MAX_POSITION_EXCEEDED / SECTOR_LIMIT / DRAWDOWN_LIMIT
    -- NEWS_PAUSE / DUPLICATE_SIGNAL_BLOCKED / RR_BELOW_MIN

    stk_cd          VARCHAR(20),
    strategy        VARCHAR(30),
    signal_id       BIGINT REFERENCES trading_signals(id) ON DELETE SET NULL,

    threshold_value NUMERIC(10,2),
    actual_value    NUMERIC(10,2),
    description     TEXT,
    action_taken    VARCHAR(100),

    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_re_type_date ON risk_events(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_re_date      ON risk_events(occurred_at DESC);
