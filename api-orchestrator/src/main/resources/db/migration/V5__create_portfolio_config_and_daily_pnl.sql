-- V5: portfolio_config (단일 행 설정) + daily_pnl (일별 손익 집계)

-- ── portfolio_config ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_config (
    id                      INTEGER PRIMARY KEY DEFAULT 1,
    CHECK (id = 1),         -- 단일 행 강제 (싱글턴 설정 테이블)

    -- 자본 설정
    total_capital           NUMERIC(16,0) NOT NULL DEFAULT 10000000,
    max_position_pct        NUMERIC(5,2)  NOT NULL DEFAULT 10.0,
    max_position_count      INTEGER       NOT NULL DEFAULT 5,
    max_sector_pct          NUMERIC(5,2)  NOT NULL DEFAULT 30.0,

    -- 리스크 설정
    daily_loss_limit_pct    NUMERIC(5,2)  NOT NULL DEFAULT 3.0,
    daily_loss_limit_abs    NUMERIC(14,0),
    max_drawdown_pct        NUMERIC(5,2)  NOT NULL DEFAULT 10.0,
    sl_mandatory            BOOLEAN       NOT NULL DEFAULT TRUE,
    min_rr_ratio            NUMERIC(5,2)  NOT NULL DEFAULT 1.0,

    -- 전략 활성화 목록 (JSONB 배열)
    enabled_strategies      JSONB NOT NULL DEFAULT
        '["S1_GAP_OPEN","S7_AUCTION","S8_GOLDEN_CROSS","S9_PULLBACK_SWING",
          "S10_NEW_HIGH","S11_FRGN_CONT","S12_CLOSING","S13_BOX_BREAKOUT",
          "S14_OVERSOLD_BOUNCE","S15_MOMENTUM_ALIGN"]',

    -- 포지션 사이징 방식: FIXED_PCT / KELLY / VOLATILITY
    sizing_method           VARCHAR(20)   NOT NULL DEFAULT 'FIXED_PCT',

    updated_at              TIMESTAMPTZ   DEFAULT NOW(),
    updated_by              VARCHAR(50)
);

-- 기본 설정 행 삽입 (없을 때만) — NOT NULL 컬럼에 명시적 값 지정
INSERT INTO portfolio_config (
    id, total_capital, max_position_pct, max_position_count, max_sector_pct,
    daily_loss_limit_pct, max_drawdown_pct, sl_mandatory, min_rr_ratio,
    sizing_method, enabled_strategies, updated_at
) VALUES (
    1, 10000000, 10.0, 5, 30.0,
    3.0, 10.0, TRUE, 1.0,
    'FIXED_PCT',
    '["S1_GAP_OPEN","S7_AUCTION","S8_GOLDEN_CROSS","S9_PULLBACK_SWING","S10_NEW_HIGH","S11_FRGN_CONT","S12_CLOSING","S13_BOX_BREAKOUT","S14_OVERSOLD_BOUNCE","S15_MOMENTUM_ALIGN"]',
    NOW()
) ON CONFLICT (id) DO NOTHING;

-- ── daily_pnl ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_pnl (
    id                      BIGSERIAL PRIMARY KEY,
    date                    DATE NOT NULL UNIQUE,

    -- 당일 신호 통계
    total_signals           INTEGER DEFAULT 0,
    enter_count             INTEGER DEFAULT 0,
    cancel_count            INTEGER DEFAULT 0,

    -- 당일 청산 결과
    closed_count            INTEGER DEFAULT 0,
    tp_hit_count            INTEGER DEFAULT 0,
    sl_hit_count            INTEGER DEFAULT 0,
    force_close_count       INTEGER DEFAULT 0,
    win_rate                NUMERIC(5,2),

    -- 손익
    gross_pnl_abs           NUMERIC(14,0),
    net_pnl_abs             NUMERIC(14,0),
    gross_pnl_pct           NUMERIC(7,4),
    net_pnl_pct             NUMERIC(7,4),
    avg_pnl_per_trade       NUMERIC(7,4),

    -- 리스크 지표
    max_intraday_loss_pct   NUMERIC(7,4),
    daily_loss_limit_hit    BOOLEAN DEFAULT FALSE,

    -- 누적
    cumulative_pnl_abs      NUMERIC(16,0),
    cumulative_pnl_pct      NUMERIC(7,4),
    peak_capital            NUMERIC(16,0),
    current_drawdown_pct    NUMERIC(7,4),

    -- 시장 컨텍스트
    kospi_change_pct        NUMERIC(6,3),
    kosdaq_change_pct       NUMERIC(6,3),
    market_sentiment        VARCHAR(20),

    aggregated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(date DESC);
