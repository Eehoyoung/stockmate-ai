-- V7: overnight_evaluations — 오버나잇 평가 이력 (Python overnight_worker 저장)

CREATE TABLE IF NOT EXISTS overnight_evaluations (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT REFERENCES trading_signals(id) ON DELETE SET NULL,
    position_id     BIGINT REFERENCES open_positions(id) ON DELETE SET NULL,
    stk_cd          VARCHAR(20) NOT NULL,
    strategy        VARCHAR(30),

    -- ── Python overnight_worker 결과 ───────────────────────────────────────
    java_overnight_score  NUMERIC(5,2),
    final_score           NUMERIC(5,2),
    verdict               VARCHAR(20),       -- HOLD / FORCE_CLOSE
    confidence            VARCHAR(10),
    reason                TEXT,

    -- ── 평가 시점 지표 스냅샷 ────────────────────────────────────────────
    pnl_pct               NUMERIC(7,4),
    flu_rt                NUMERIC(7,4),
    cntr_strength         NUMERIC(7,2),
    rsi14                 NUMERIC(5,2),
    ma_alignment          VARCHAR(30),
    bid_ratio             NUMERIC(6,3),
    entry_price           NUMERIC(10,0),
    cur_prc_at_eval       NUMERIC(10,0),

    -- ── 컴포넌트별 점수 (JSONB) ──────────────────────────────────────────
    score_components      JSONB,

    -- ── 사후 검증 (익일 09:30 채움) ──────────────────────────────────────
    next_day_open         NUMERIC(10,0),
    next_day_pnl_pct      NUMERIC(7,4),
    verdict_correct       BOOLEAN,

    evaluated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oe_signal_id   ON overnight_evaluations(signal_id);
CREATE INDEX IF NOT EXISTS idx_oe_position_id ON overnight_evaluations(position_id);
CREATE INDEX IF NOT EXISTS idx_oe_stk_cd      ON overnight_evaluations(stk_cd, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_oe_verdict     ON overnight_evaluations(verdict, evaluated_at DESC);
