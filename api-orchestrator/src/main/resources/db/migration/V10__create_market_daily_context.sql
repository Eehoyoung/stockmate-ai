-- V10: market_daily_context — 시장 전체 컨텍스트 (MarketContextScheduler 08:30)

CREATE TABLE IF NOT EXISTS market_daily_context (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,

    -- ── 지수 ───────────────────────────────────────────────────────────────
    kospi_open      NUMERIC(8,2),
    kospi_close     NUMERIC(8,2),
    kospi_change_pct NUMERIC(6,3),
    kospi_volume    BIGINT,

    kosdaq_open     NUMERIC(8,2),
    kosdaq_close    NUMERIC(8,2),
    kosdaq_change_pct NUMERIC(6,3),
    kosdaq_volume   BIGINT,

    -- ── 시장 분위기 ────────────────────────────────────────────────────────
    advancing_stocks    INTEGER,
    declining_stocks    INTEGER,
    unchanged_stocks    INTEGER,
    advance_decline_ratio NUMERIC(6,3),

    -- ── 외국인·기관 수급 ───────────────────────────────────────────────────
    frgn_net_buy_kospi  NUMERIC(14,0),
    inst_net_buy_kospi  NUMERIC(14,0),
    frgn_net_buy_kosdaq NUMERIC(14,0),
    inst_net_buy_kosdaq NUMERIC(14,0),

    -- ── 시장 전반 상태 ─────────────────────────────────────────────────────
    news_sentiment       VARCHAR(20),
    news_trading_ctrl    VARCHAR(20),
    vix_equivalent       NUMERIC(6,2),
    economic_event_today BOOLEAN DEFAULT FALSE,
    economic_event_nm    VARCHAR(200),

    -- ── 당일 성과 요약 (장 종료 후 채움) ─────────────────────────────────
    total_signals_today    INTEGER,
    signal_win_rate_today  NUMERIC(5,2),
    avg_pnl_pct_today      NUMERIC(7,4),

    recorded_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mdc_date ON market_daily_context(date DESC);
