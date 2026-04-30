-- V39__expand_tp_sl_method_to_varchar200.sql
-- WARN-2: trading_signals.tp_method / sl_method 컬럼을 VARCHAR(200)으로 확장
--   - TP/SL 방법론 문자열이 길어질 경우 value too long 오류 방지
--   - ai-engine/db_writer.py insert_python_signal() 에서 [:200] truncation 과 병행 적용
--   - tp_method / sl_method 를 참조하는 뷰(open_positions, v_active_positions,
--     v_portfolio_risk_snapshot)를 DROP 후 컬럼 변경, 이후 뷰 재생성

-- ── 1. 뷰 DROP (의존 순서 역방향) ────────────────────────────────────────────
DROP VIEW IF EXISTS v_portfolio_risk_snapshot;
DROP VIEW IF EXISTS v_active_positions;
DROP VIEW IF EXISTS open_positions;

-- ── 2. 컬럼 타입 변경 ─────────────────────────────────────────────────────────
ALTER TABLE trading_signals
    ALTER COLUMN tp_method TYPE VARCHAR(200);

ALTER TABLE trading_signals
    ALTER COLUMN sl_method TYPE VARCHAR(200);

-- ── 3. 뷰 재생성 (V37 정의 그대로) ──────────────────────────────────────────

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
