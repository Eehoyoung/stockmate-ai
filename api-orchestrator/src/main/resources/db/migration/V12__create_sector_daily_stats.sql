-- V12: sector_daily_stats — 섹터별 일별 성과

CREATE TABLE IF NOT EXISTS sector_daily_stats (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    sector          VARCHAR(50) NOT NULL,

    -- ── 섹터 수급 ──────────────────────────────────────────────────────────
    frgn_net_buy    NUMERIC(14,0),
    inst_net_buy    NUMERIC(14,0),
    avg_change_pct  NUMERIC(6,3),
    top_stock_cd    VARCHAR(20),
    top_stock_pct   NUMERIC(6,3),

    -- ── 신호 성과 ──────────────────────────────────────────────────────────
    signal_count    INTEGER DEFAULT 0,
    enter_count     INTEGER DEFAULT 0,
    avg_rule_score  NUMERIC(5,2),
    tp_count        INTEGER DEFAULT 0,
    sl_count        INTEGER DEFAULT 0,
    sector_win_rate NUMERIC(5,2),
    avg_sector_pnl  NUMERIC(7,4),

    news_recommended BOOLEAN DEFAULT FALSE,

    UNIQUE (date, sector)
);

CREATE INDEX IF NOT EXISTS idx_sector_stats_date ON sector_daily_stats(date DESC);
