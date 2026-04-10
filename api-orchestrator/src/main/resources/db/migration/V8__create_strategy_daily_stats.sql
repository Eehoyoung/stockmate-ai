-- V8: strategy_daily_stats — 전략별 일별 집계 (PerformanceAggregationScheduler)

CREATE TABLE IF NOT EXISTS strategy_daily_stats (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    strategy        VARCHAR(30) NOT NULL,

    -- ── 신호 건수 ──────────────────────────────────────────────────────────
    total_signals       INTEGER DEFAULT 0,
    enter_count         INTEGER DEFAULT 0,
    cancel_count        INTEGER DEFAULT 0,
    skip_entry_count    INTEGER DEFAULT 0,

    -- ── 청산 결과 ──────────────────────────────────────────────────────────
    tp1_hit_count       INTEGER DEFAULT 0,
    tp2_hit_count       INTEGER DEFAULT 0,
    sl_hit_count        INTEGER DEFAULT 0,
    force_close_count   INTEGER DEFAULT 0,
    expired_count       INTEGER DEFAULT 0,
    overnight_count     INTEGER DEFAULT 0,
    win_rate            NUMERIC(5,2),

    -- ── 스코어 통계 ────────────────────────────────────────────────────────
    avg_rule_score      NUMERIC(5,2),
    avg_ai_score        NUMERIC(5,2),
    avg_rr_ratio        NUMERIC(5,2),
    pct_above_threshold NUMERIC(5,2),

    -- ── 성과 통계 ──────────────────────────────────────────────────────────
    avg_pnl_pct         NUMERIC(7,4),
    total_pnl_abs       NUMERIC(14,0),
    avg_hold_min        NUMERIC(7,1),
    best_pnl_pct        NUMERIC(7,4),
    worst_pnl_pct       NUMERIC(7,4),

    threshold_snapshot  NUMERIC(5,2),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (date, strategy)
);

CREATE INDEX IF NOT EXISTS idx_sds_date     ON strategy_daily_stats(date DESC);
CREATE INDEX IF NOT EXISTS idx_sds_strategy ON strategy_daily_stats(strategy, date DESC);
