-- V2: trading_signals 에 Python ai-engine 스코어링 결과 컬럼 추가
-- 컬럼 소유권:
--   rule_score ~ scored_at       → Python queue_worker (스코어링 완료 후 UPDATE)
--   *_at_signal                  → Python queue_worker (신호 시점 기술지표 스냅샷)
--   market_flu_rt, news_*        → Python queue_worker (시장 컨텍스트)
--   exit_type ~ exited_at        → Java ForceCloseScheduler (청산 시 UPDATE)

-- ── Python ai-engine 스코어링 결과 ─────────────────────────────────────────
ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS rule_score     NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS ai_score       NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS rr_ratio       NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS action         VARCHAR(20),
    ADD COLUMN IF NOT EXISTS confidence     VARCHAR(10),
    ADD COLUMN IF NOT EXISTS ai_reason      TEXT,
    ADD COLUMN IF NOT EXISTS tp_method      VARCHAR(60),
    ADD COLUMN IF NOT EXISTS sl_method      VARCHAR(60),
    ADD COLUMN IF NOT EXISTS skip_entry     BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS scored_at      TIMESTAMPTZ;

-- ── 신호 시점 기술지표 스냅샷 ──────────────────────────────────────────────
ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS ma5_at_signal   NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS ma20_at_signal  NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS ma60_at_signal  NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS rsi14_at_signal NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS bb_upper_at_sig NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS bb_lower_at_sig NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS atr_at_signal   NUMERIC(10,2);

-- ── 신호 시점 시장 컨텍스트 ───────────────────────────────────────────────
ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS market_flu_rt   NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS news_sentiment  VARCHAR(20),
    ADD COLUMN IF NOT EXISTS news_ctrl       VARCHAR(20);

-- ── 청산 결과 (Java ForceCloseScheduler) ────────────────────────────────
ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS exit_type           VARCHAR(20),
    ADD COLUMN IF NOT EXISTS exit_price          NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS exit_pnl_pct        NUMERIC(7,4),
    ADD COLUMN IF NOT EXISTS exit_pnl_abs        NUMERIC(14,0),
    ADD COLUMN IF NOT EXISTS hold_duration_min   INTEGER,
    ADD COLUMN IF NOT EXISTS exited_at           TIMESTAMPTZ;

-- ── 인덱스 ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_ts_action_created ON trading_signals(action, created_at);
CREATE INDEX IF NOT EXISTS idx_ts_exit_type      ON trading_signals(exit_type) WHERE exit_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ts_stk_action     ON trading_signals(stk_cd, action, created_at);
