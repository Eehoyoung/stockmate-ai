-- V13: candidate_pool_history — 후보 풀 일별 이력 (Python candidates_builder UPSERT)

CREATE TABLE IF NOT EXISTS candidate_pool_history (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    strategy        VARCHAR(30) NOT NULL,
    market          VARCHAR(10) NOT NULL,
    stk_cd          VARCHAR(20) NOT NULL,
    stk_nm          VARCHAR(100),

    pool_score      NUMERIC(5,2),
    appear_count    INTEGER DEFAULT 1,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    led_to_signal   BOOLEAN DEFAULT FALSE,
    signal_id       BIGINT REFERENCES trading_signals(id) ON DELETE SET NULL,

    UNIQUE (date, strategy, market, stk_cd)
);

CREATE INDEX IF NOT EXISTS idx_cph_date     ON candidate_pool_history(date DESC);
CREATE INDEX IF NOT EXISTS idx_cph_stk_date ON candidate_pool_history(stk_cd, date DESC);
CREATE INDEX IF NOT EXISTS idx_cph_strategy ON candidate_pool_history(strategy, date DESC);
