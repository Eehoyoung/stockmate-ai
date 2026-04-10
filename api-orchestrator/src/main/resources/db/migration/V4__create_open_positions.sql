-- V4: open_positions — 실시간 포지션 원장
-- 이 테이블 없이는 이중매수 방지·포지션 수 제한·섹터 익스포저 계산 불가
-- 쓰기 주체: Java SignalService (ENTER 확정 시 INSERT),
--            Java ForceCloseScheduler (TP/SL/FORCE_CLOSE 시 UPDATE)
--            Python overnight_worker (overnight_verdict UPDATE)

CREATE TABLE IF NOT EXISTS open_positions (
    id                  BIGSERIAL PRIMARY KEY,
    signal_id           BIGINT NOT NULL REFERENCES trading_signals(id),
    stk_cd              VARCHAR(20) NOT NULL,
    stk_nm              VARCHAR(100),
    strategy            VARCHAR(30) NOT NULL,
    market              VARCHAR(10),            -- 001=KOSPI, 101=KOSDAQ
    sector              VARCHAR(50),            -- 업종명 (stock_master 참조)

    -- ── 진입 정보 ─────────────────────────────────────────────────────────
    entry_price         NUMERIC(10,0) NOT NULL,
    entry_qty           INTEGER,                -- 수량 (portfolio_config 기반)
    entry_amount        NUMERIC(14,0),          -- 진입 금액 (entry_price × qty)
    entry_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ── TP/SL 기준 ──────────────────────────────────────────────────────
    tp1_price           NUMERIC(10,0),
    tp2_price           NUMERIC(10,0),
    sl_price            NUMERIC(10,0) NOT NULL,
    tp_method           VARCHAR(60),
    sl_method           VARCHAR(60),
    rr_ratio            NUMERIC(5,2),

    -- ── 포지션 상태 ───────────────────────────────────────────────────────
    -- ACTIVE / PARTIAL_TP / OVERNIGHT / CLOSING / CLOSED
    status              VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',

    -- ── 부분 TP 처리 ─────────────────────────────────────────────────────
    tp1_hit_at          TIMESTAMPTZ,
    tp1_exit_qty        INTEGER,               -- TP1 청산 수량
    remaining_qty       INTEGER,               -- 잔여 수량

    -- ── 오버나잇 ────────────────────────────────────────────────────────
    is_overnight        BOOLEAN DEFAULT FALSE,
    overnight_verdict   VARCHAR(20),           -- HOLD / FORCE_CLOSE
    overnight_score     NUMERIC(5,2),

    -- ── 알림 ─────────────────────────────────────────────────────────────
    sl_alert_sent       BOOLEAN DEFAULT FALSE,
    rule_score          NUMERIC(5,2),
    ai_score            NUMERIC(5,2),

    -- ── 청산 완료 ────────────────────────────────────────────────────────
    closed_at           TIMESTAMPTZ,
    exit_type           VARCHAR(20),           -- TP1_HIT/TP2_HIT/SL_HIT/FORCE_CLOSE/MANUAL
    exit_price          NUMERIC(10,0),
    realized_pnl_pct    NUMERIC(7,4),
    realized_pnl_abs    NUMERIC(14,0),
    hold_duration_min   INTEGER
);

-- 활성 포지션 조회 최적화
CREATE UNIQUE INDEX IF NOT EXISTS idx_op_signal_id    ON open_positions(signal_id);
CREATE INDEX IF NOT EXISTS idx_op_stk_status         ON open_positions(stk_cd, status);
CREATE INDEX IF NOT EXISTS idx_op_status_entry       ON open_positions(status, entry_at)
    WHERE status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');
CREATE INDEX IF NOT EXISTS idx_op_strategy_status    ON open_positions(strategy, status);
