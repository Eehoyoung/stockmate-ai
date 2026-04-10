-- V15: DB 뷰 4개 생성

-- ── v_active_positions — 활성 포지션 현황 ─────────────────────────────────
CREATE OR REPLACE VIEW v_active_positions AS
SELECT
    op.id,
    op.stk_cd,
    COALESCE(sm.stk_nm, op.stk_nm)     AS stk_nm,
    sm.sector,
    op.strategy,
    op.entry_price,
    op.entry_at,
    op.tp1_price,
    op.sl_price,
    op.rr_ratio,
    op.status,
    op.is_overnight,
    op.rule_score,
    EXTRACT(EPOCH FROM (NOW() - op.entry_at)) / 60 AS hold_min_so_far,
    ts.ai_reason,
    ts.tp_method,
    ts.sl_method
FROM open_positions op
LEFT JOIN stock_master sm ON sm.stk_cd = op.stk_cd
LEFT JOIN trading_signals ts ON ts.id = op.signal_id
WHERE op.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');

-- ── v_strategy_performance_30d — 30일 롤링 전략 성과 ─────────────────────
CREATE OR REPLACE VIEW v_strategy_performance_30d AS
SELECT
    strategy,
    COUNT(*)                                        AS total_signals,
    COUNT(*) FILTER (WHERE action = 'ENTER')        AS enter_count,
    COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT')) AS tp_count,
    COUNT(*) FILTER (WHERE exit_type = 'SL_HIT')   AS sl_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT'))
        / NULLIF(COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT','SL_HIT')), 0)
    , 2)                                            AS win_rate_pct,
    ROUND(AVG(rule_score) FILTER (WHERE rule_score IS NOT NULL), 2) AS avg_rule_score,
    ROUND(AVG(rr_ratio)   FILTER (WHERE rr_ratio   IS NOT NULL), 2) AS avg_rr,
    ROUND(AVG(exit_pnl_pct) FILTER (WHERE exit_pnl_pct IS NOT NULL) * 100, 3) AS avg_pnl_pct,
    ROUND(AVG(hold_duration_min) FILTER (WHERE hold_duration_min IS NOT NULL), 0) AS avg_hold_min
FROM trading_signals
WHERE created_at >= NOW() - INTERVAL '30 days'
  AND action = 'ENTER'
GROUP BY strategy
ORDER BY win_rate_pct DESC NULLS LAST;

-- ── v_score_outcome_correlation — 스코어 컴포넌트 ↔ 결과 상관관계 ─────────
CREATE OR REPLACE VIEW v_score_outcome_correlation AS
SELECT
    ssc.strategy,
    ts.exit_type,
    COUNT(*)                                AS cnt,
    ROUND(AVG(ssc.vol_score),       2)      AS avg_vol_score,
    ROUND(AVG(ssc.momentum_score),  2)      AS avg_momentum_score,
    ROUND(AVG(ssc.technical_score), 2)      AS avg_technical_score,
    ROUND(AVG(ssc.demand_score),    2)      AS avg_demand_score,
    ROUND(AVG(ssc.total_score),     2)      AS avg_total_score,
    ROUND(AVG(ts.exit_pnl_pct) * 100, 3)   AS avg_pnl_pct
FROM signal_score_components ssc
JOIN trading_signals ts ON ts.id = ssc.signal_id
WHERE ts.exit_type IS NOT NULL
  AND ts.created_at >= NOW() - INTERVAL '90 days'
GROUP BY ssc.strategy, ts.exit_type;

-- ── v_portfolio_risk_snapshot — 현재 포트폴리오 리스크 상태 ──────────────
CREATE OR REPLACE VIEW v_portfolio_risk_snapshot AS
SELECT
    pc.total_capital,
    pc.max_position_count,
    pc.max_sector_pct,
    pc.daily_loss_limit_pct,

    COUNT(op.id)                                            AS active_position_count,
    COALESCE(SUM(op.entry_amount), 0)                       AS total_allocated,
    ROUND(100.0 * COALESCE(SUM(op.entry_amount), 0)
          / NULLIF(pc.total_capital, 0), 2)                 AS allocation_pct,
    COUNT(op.id) FILTER (WHERE op.is_overnight = TRUE)      AS overnight_count,

    dp.net_pnl_pct                                          AS today_pnl_pct,
    dp.daily_loss_limit_hit,
    dp.current_drawdown_pct

FROM portfolio_config pc
LEFT JOIN open_positions op ON op.status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT')
LEFT JOIN daily_pnl dp ON dp.date = CURRENT_DATE
GROUP BY pc.total_capital, pc.max_position_count, pc.max_sector_pct,
         pc.daily_loss_limit_pct, dp.net_pnl_pct, dp.daily_loss_limit_hit,
         dp.current_drawdown_pct;
