-- V6: daily_indicators — 기술지표 영속 캐시
-- 전략 스캔 시 동일 종목·동일 날짜 API 재호출 제거 + 백테스팅 데이터 확보
-- 쓰기 주체: Python ai-engine (db_writer.upsert_daily_indicators)
-- UPSERT 패턴: ON CONFLICT (date, stk_cd) DO UPDATE

CREATE TABLE IF NOT EXISTS daily_indicators (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    stk_cd          VARCHAR(20) NOT NULL,

    -- ── OHLCV ─────────────────────────────────────────────────────────
    close_price     NUMERIC(10,0),
    open_price      NUMERIC(10,0),
    high_price      NUMERIC(10,0),
    low_price       NUMERIC(10,0),
    volume          BIGINT,
    volume_ratio    NUMERIC(6,2),       -- 거래량비율 (20일 평균 대비)

    -- ── 이동평균 ──────────────────────────────────────────────────────
    ma5             NUMERIC(10,0),
    ma20            NUMERIC(10,0),
    ma60            NUMERIC(10,0),
    ma120           NUMERIC(10,0),
    vol_ma20        BIGINT,

    -- ── 오실레이터 ────────────────────────────────────────────────────
    rsi14           NUMERIC(5,2),
    stoch_k         NUMERIC(5,2),
    stoch_d         NUMERIC(5,2),

    -- ── 볼린저밴드 / 변동성 ────────────────────────────────────────────
    bb_upper        NUMERIC(10,0),
    bb_mid          NUMERIC(10,0),
    bb_lower        NUMERIC(10,0),
    bb_width_pct    NUMERIC(6,3),       -- (upper-lower)/mid × 100
    pct_b           NUMERIC(6,3),       -- (close-lower)/(upper-lower) × 100

    atr14           NUMERIC(10,2),
    atr_pct         NUMERIC(6,3),       -- ATR / close × 100

    -- ── MACD ──────────────────────────────────────────────────────────
    macd_line       NUMERIC(10,2),
    macd_signal     NUMERIC(10,2),
    macd_hist       NUMERIC(10,2),

    -- ── 추세·패턴 플래그 ───────────────────────────────────────────────
    is_bullish_aligned  BOOLEAN,        -- MA5 > MA20 > MA60
    is_above_ma20       BOOLEAN,
    is_new_high_52w     BOOLEAN,        -- 52주 신고가
    golden_cross_today  BOOLEAN,        -- 오늘 골든크로스 발생

    -- ── 스윙 포인트 (tp_sl_engine 용) ────────────────────────────────
    swing_high_20d  NUMERIC(10,0),
    swing_low_20d   NUMERIC(10,0),
    swing_high_60d  NUMERIC(10,0),
    swing_low_60d   NUMERIC(10,0),

    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (date, stk_cd)
);

CREATE INDEX IF NOT EXISTS idx_di_date_stk   ON daily_indicators(date DESC, stk_cd);
CREATE INDEX IF NOT EXISTS idx_di_stk_date   ON daily_indicators(stk_cd, date DESC);
CREATE INDEX IF NOT EXISTS idx_di_rsi_low    ON daily_indicators(date, rsi14)
    WHERE rsi14 < 30;
CREATE INDEX IF NOT EXISTS idx_di_aligned    ON daily_indicators(date, is_bullish_aligned)
    WHERE is_bullish_aligned = TRUE;
