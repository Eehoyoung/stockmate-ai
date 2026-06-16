CREATE INDEX IF NOT EXISTS idx_rule_cancel_signal_cancel_type_created_at
    ON rule_cancel_signal(cancel_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rule_cancel_signal_strategy_cancel_created_at
    ON rule_cancel_signal(strategy, cancel_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_score_components_strategy_computed_at
    ON signal_score_components(strategy, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_plans_strategy_created_effective_rr
    ON trade_plans(strategy_code, created_at DESC, effective_rr);

CREATE INDEX IF NOT EXISTS idx_cph_date_strategy_market
    ON candidate_pool_history(date DESC, strategy, market);

CREATE INDEX IF NOT EXISTS idx_vi_events_stk_created_at
    ON vi_events(stk_cd, created_at DESC);

CREATE OR REPLACE VIEW v_daily_cancel_summary AS
SELECT
    (r.created_at AT TIME ZONE 'Asia/Seoul')::DATE AS trade_date,
    r.strategy,
    r.cancel_type,
    COUNT(*) AS cancel_count,
    ROUND(AVG(r.rule_score), 2) AS avg_rule_score,
    ROUND(AVG(CASE WHEN (r.raw_payload ->> 'threshold_used') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.raw_payload ->> 'threshold_used')::NUMERIC END), 2) AS avg_threshold_used,
    ROUND(AVG(CASE WHEN (r.raw_payload ->> 'score_margin') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.raw_payload ->> 'score_margin')::NUMERIC END), 2) AS avg_score_margin,
    ROUND(AVG(ts.effective_rr), 3) AS avg_effective_rr
FROM rule_cancel_signal r
LEFT JOIN trading_signals ts ON ts.id = r.signal_id
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW v_signal_cancel_audit AS
SELECT
    r.id AS rule_cancel_id,
    r.signal_id,
    r.created_at,
    r.stk_cd,
    r.strategy,
    r.cancel_type,
    r.rule_score,
    CASE WHEN (r.raw_payload ->> 'threshold_used') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.raw_payload ->> 'threshold_used')::NUMERIC END AS threshold_used,
    CASE WHEN (r.raw_payload ->> 'score_margin') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.raw_payload ->> 'score_margin')::NUMERIC END AS score_margin,
    ts.effective_rr,
    ts.min_rr_ratio,
    ts.rr_ratio,
    r.raw_payload -> 'failed_gates' AS failed_gates,
    r.raw_payload ->> 'stale_source' AS stale_source,
    CASE WHEN (r.raw_payload ->> 'tick_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'tick_age_ms')::BIGINT END AS tick_age_ms,
    CASE WHEN (r.raw_payload ->> 'hoga_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'hoga_age_ms')::BIGINT END AS hoga_age_ms,
    CASE WHEN (r.raw_payload ->> 'strength_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'strength_age_ms')::BIGINT END AS strength_age_ms,
    CASE WHEN (r.raw_payload ->> 'vi_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'vi_age_ms')::BIGINT END AS vi_age_ms,
    r.reason,
    r.raw_payload
FROM rule_cancel_signal r
LEFT JOIN trading_signals ts ON ts.id = r.signal_id;

CREATE OR REPLACE VIEW v_freshness_cancel_audit AS
SELECT
    r.id AS rule_cancel_id,
    r.signal_id,
    r.created_at,
    r.stk_cd,
    r.strategy,
    r.cancel_type,
    r.raw_payload ->> 'freshness_decision' AS freshness_decision,
    r.raw_payload ->> 'freshness_status' AS freshness_status,
    r.raw_payload ->> 'stale_source' AS stale_source,
    r.raw_payload -> 'stale_sources' AS stale_sources,
    CASE WHEN (r.raw_payload ->> 'tick_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'tick_age_ms')::BIGINT END AS tick_age_ms,
    CASE WHEN (r.raw_payload ->> 'hoga_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'hoga_age_ms')::BIGINT END AS hoga_age_ms,
    CASE WHEN (r.raw_payload ->> 'strength_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'strength_age_ms')::BIGINT END AS strength_age_ms,
    CASE WHEN (r.raw_payload ->> 'vi_age_ms') ~ '^[0-9]+$' THEN (r.raw_payload ->> 'vi_age_ms')::BIGINT END AS vi_age_ms,
    r.raw_payload -> 'market_data_sources' AS market_data_sources,
    r.raw_payload -> 'data_refresh_attempted' AS data_refresh_attempted,
    r.reason
FROM rule_cancel_signal r
WHERE r.cancel_type = 'FRESHNESS_STALE'
   OR r.raw_payload ? 'stale_sources';
