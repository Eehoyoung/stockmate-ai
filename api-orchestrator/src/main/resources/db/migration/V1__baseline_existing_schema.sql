-- V1 Baseline — Hibernate ddl-auto:update 가 관리하던 기존 테이블 초기 스키마
-- baseline-on-migrate: true 설정에 의해 기존 DB에서는 이 스크립트가 실행되지 않음.
-- 완전히 새로운 DB (CI/CD, 신규 서버)에서는 이 스크립트가 실행되어 기반 테이블을 생성.

-- ── kiwoom_token ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kiwoom_token (
    id              BIGSERIAL PRIMARY KEY,
    access_token    TEXT NOT NULL,
    token_type      VARCHAR(50),
    expires_at      TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── trading_signals (기본 구조만 — V2에서 컬럼 추가) ───────────────────
CREATE SEQUENCE IF NOT EXISTS trading_signals_seq START 1 INCREMENT 50;

CREATE TABLE IF NOT EXISTS trading_signals (
    id              BIGINT PRIMARY KEY DEFAULT nextval('trading_signals_seq'),
    stk_cd          VARCHAR(20) NOT NULL,
    stk_nm          VARCHAR(40),
    strategy        VARCHAR(30) NOT NULL,
    signal_score    FLOAT8,
    entry_price     FLOAT8,
    target_price    FLOAT8,
    stop_price      FLOAT8,
    tp1_price       FLOAT8,
    tp2_price       FLOAT8,
    sl_price        FLOAT8,
    target_pct      FLOAT8,
    stop_pct        FLOAT8,
    gap_pct         FLOAT8,
    cntr_strength   FLOAT8,
    bid_ratio       FLOAT8,
    vol_ratio       FLOAT8,
    pullback_pct    FLOAT8,
    theme_name      VARCHAR(100),
    entry_type      VARCHAR(30),
    market_type     VARCHAR(10),
    signal_status   VARCHAR(20) DEFAULT 'PENDING',
    extra_info      TEXT,
    created_at      TIMESTAMP,
    executed_at     TIMESTAMP,
    closed_at       TIMESTAMP,
    realized_pnl    FLOAT8
);

CREATE INDEX IF NOT EXISTS idx_signal_stk_cd    ON trading_signals(stk_cd);
CREATE INDEX IF NOT EXISTS idx_signal_strategy  ON trading_signals(strategy);
CREATE INDEX IF NOT EXISTS idx_signal_created_at ON trading_signals(created_at);

-- ── vi_events ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vi_events (
    id              BIGSERIAL PRIMARY KEY,
    stk_cd          VARCHAR(20),
    vi_type         VARCHAR(20),
    trigger_price   FLOAT8,
    reference_price FLOAT8,
    occurred_at     TIMESTAMP DEFAULT NOW()
);

-- ── ws_tick_data ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ws_tick_data (
    id              BIGSERIAL PRIMARY KEY,
    stk_cd          VARCHAR(20),
    cur_prc         FLOAT8,
    flu_rt          FLOAT8,
    cntr_qty        BIGINT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── economic_events ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS economic_events (
    id              BIGSERIAL PRIMARY KEY,
    event_date      DATE,
    title           VARCHAR(200),
    importance      VARCHAR(20),
    country         VARCHAR(10),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── news_analysis ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_analysis (
    id              BIGSERIAL PRIMARY KEY,
    headline        TEXT,
    sentiment       VARCHAR(20),
    sector          VARCHAR(50),
    trading_ctrl    VARCHAR(20),
    analyzed_at     TIMESTAMP DEFAULT NOW()
);
