-- V37__fix_trading_signals_constraints.sql
-- Issue 1 (CRITICAL): trading_signals_strategy_check 에 S7_AUCTION 잔류, S7_ICHIMOKU_BREAKOUT 미포함
--   → constraint drop 후 S7_ICHIMOKU_BREAKOUT 포함하여 재생성
-- Issue 2 (HIGH): trading_signals.sector VARCHAR(50) → VARCHAR(100) 확장
--   → S15_MOMENTUM_ALIGN 신호 insert 시 value too long 오류 해소
--   → sector 컬럼을 참조하는 뷰(open_positions, v_active_positions)를 drop 후 재생성

-- ── Issue 1: strategy CHECK constraint 재생성 ──────────────────────────────
ALTER TABLE trading_signals
    DROP CONSTRAINT IF EXISTS trading_signals_strategy_check;

ALTER TABLE trading_signals
    ADD CONSTRAINT trading_signals_strategy_check
        CHECK (strategy::text = ANY (ARRAY[
            'S1_GAP_OPEN',
            'S2_VI_PULLBACK',
            'S3_INST_FRGN',
            'S4_BIG_CANDLE',
            'S5_PROG_FRGN',
            'S6_THEME_LAGGARD',
            'S7_AUCTION',
            'S7_ICHIMOKU_BREAKOUT',
            'S8_GOLDEN_CROSS',
            'S9_PULLBACK_SWING',
            'S10_NEW_HIGH',
            'S11_FRGN_CONT',
            'S12_CLOSING',
            'S13_BOX_BREAKOUT',
            'S14_OVERSOLD_BOUNCE',
            'S15_MOMENTUM_ALIGN'
        ]::text[]));

-- ── Issue 2: sector 컬럼 VARCHAR(50) → VARCHAR(100) ───────────────────────
-- sector 컬럼을 참조하는 뷰들을 먼저 DROP (의존 순서: open_positions, v_active_positions)
-- v_portfolio_risk_snapshot 은 sector 를 직접 참조하지 않으나 trading_signals 를 참조하므로 함께 처리
DROP VIEW IF EXISTS v_portfolio_risk_snapshot;
DROP VIEW IF EXISTS v_active_positions;
DROP VIEW IF EXISTS open_positions;

-- sector 컬럼 타입 변경
ALTER TABLE trading_signals
    ALTER COLUMN sector TYPE VARCHAR(100);

-- ── 뷰 재생성 ─────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW open_positions AS
SELECT
    COALESCE(legacy_open_position_id, id) AS id,
    id                                    AS signal_id,
    stk_cd,
    stk_nm,
    strategy,
    market_type                           AS market,
    sector,
    entry_price::NUMERIC(10, 0)           AS entry_price,
    entry_qty,
    entry_amount,
    entry_at,
    tp1_price::NUMERIC(10, 0)             AS tp1_price,
    tp2_price::NUMERIC(10, 0)             AS tp2_price,
    sl_price::NUMERIC(10, 0)              AS sl_price,
    tp_method,
    sl_method,
    rr_ratio,
    position_status                       AS status,
    tp1_hit_at,
    tp1_exit_qty,
    remaining_qty,
    is_overnight,
    overnight_verdict,
    overnight_score,
    sl_alert_sent,
    rule_score,
    ai_score,
    peak_price,
    trailing_pct,
    monitor_enabled,
    trailing_activation,
    trailing_basis,
    strategy_version,
    time_stop_type,
    time_stop_minutes,
    time_stop_session
FROM trading_signals ts
WHERE position_status::TEXT = ANY (ARRAY[
    'ACTIVE', 'PARTIAL_TP', 'OVERNIGHT', 'CLOSED'
]::TEXT[]);

CREATE OR REPLACE VIEW v_active_positions AS
SELECT
    ts.id,
    ts.stk_cd,
    COALESCE(sm.stk_nm, ts.stk_nm)     AS stk_nm,
    COALESCE(ts.sector, sm.sector)      AS sector,
    ts.strategy,
    ts.entry_price,
    ts.entry_at,
    ts.tp1_price,
    ts.sl_price,
    ts.rr_ratio,
    ts.position_status                  AS status,
    ts.is_overnight,
    ts.rule_score,
    ts.peak_price,
    ts.trailing_pct,
    ts.monitor_enabled,
    EXTRACT(EPOCH FROM (now() - ts.entry_at)) / 60 AS hold_min_so_far,
    ts.ai_reason,
    ts.tp_method,
    ts.sl_method
FROM trading_signals ts
         LEFT JOIN stock_master sm ON sm.stk_cd::TEXT = ts.stk_cd::TEXT
WHERE ts.position_status::TEXT = ANY (ARRAY[
    'ACTIVE', 'PARTIAL_TP', 'OVERNIGHT'
]::TEXT[]);

CREATE OR REPLACE VIEW v_portfolio_risk_snapshot AS
SELECT
    pc.total_capital,
    pc.max_position_count,
    pc.max_sector_pct,
    pc.daily_loss_limit_pct,
    COUNT(ts.id)                                                                  AS active_position_count,
    COALESCE(SUM(ts.entry_amount), 0)                                             AS total_allocated,
    ROUND(
            (100.0 * COALESCE(SUM(ts.entry_amount), 0)) /
            NULLIF(pc.total_capital, 0),
            2
    )                                                                             AS allocation_pct,
    COUNT(ts.id) FILTER (WHERE ts.is_overnight = TRUE)                            AS overnight_count,
    dp.net_pnl_pct                                                                AS today_pnl_pct,
    dp.daily_loss_limit_hit,
    dp.current_drawdown_pct
FROM portfolio_config pc
         LEFT JOIN trading_signals ts
                   ON ts.position_status::TEXT = ANY (ARRAY[
                       'ACTIVE', 'PARTIAL_TP', 'OVERNIGHT'
                       ]::TEXT[])
         LEFT JOIN daily_pnl dp ON dp.date = CURRENT_DATE
GROUP BY
    pc.total_capital,
    pc.max_position_count,
    pc.max_sector_pct,
    pc.daily_loss_limit_pct,
    dp.net_pnl_pct,
    dp.daily_loss_limit_hit,
    dp.current_drawdown_pct;

DROP TRIGGER IF EXISTS trg_sync_open_positions_view ON open_positions;
CREATE TRIGGER trg_sync_open_positions_view
INSTEAD OF INSERT OR UPDATE OR DELETE ON open_positions
FOR EACH ROW
EXECUTE FUNCTION sync_open_positions_view();
