-- Additive audit contract for source-time quality, decision/order lineage,
-- dual-source market context, and retention-safe one-minute summaries.

ALTER TABLE ws_tick_data_partitioned
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS raw_source_time VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_time_parse_status VARCHAR(24) NOT NULL DEFAULT 'MISSING',
    ADD COLUMN IF NOT EXISTS clock_skew_ms BIGINT;

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS correlation_id UUID,
    ADD COLUMN IF NOT EXISTS release_id VARCHAR(80),
    ADD COLUMN IF NOT EXISTS config_version VARCHAR(80),
    ADD COLUMN IF NOT EXISTS decision_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decision_price NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS decision_bid1 NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS decision_ask1 NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS decision_spread NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS decision_depth JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE trade_outcomes
    ADD COLUMN IF NOT EXISTS correlation_id UUID,
    ADD COLUMN IF NOT EXISTS order_submit_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS broker_ack_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS first_fill_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_fill_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_qty INTEGER,
    ADD COLUMN IF NOT EXISTS broker_order_id VARCHAR(100);

ALTER TABLE market_daily_context
    ADD COLUMN IF NOT EXISTS context_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS primary_source VARCHAR(32) NOT NULL DEFAULT 'ETF_PROXY',
    ADD COLUMN IF NOT EXISTS official_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS proxy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_complete BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_trading_signals_correlation
    ON trading_signals(correlation_id) WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trade_outcomes_correlation
    ON trade_outcomes(correlation_id) WHERE correlation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION refresh_ws_tick_summary_1m(
    p_from TIMESTAMPTZ,
    p_to TIMESTAMPTZ
) RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    affected BIGINT;
BEGIN
    IF p_from IS NULL OR p_to IS NULL OR p_from >= p_to THEN
        RAISE EXCEPTION 'invalid summary range';
    END IF;

    INSERT INTO ws_tick_data_summary (
        bucket_started_at, bucket_minutes, stk_cd, tick_type, sample_count,
        open_prc, high_prc, low_prc, close_prc, avg_flu_rt,
        max_acc_trde_qty, max_acc_trde_prica, avg_cntr_str,
        avg_bid_ask_ratio, must_persist, updated_at
    )
    SELECT
        date_trunc('minute', created_at), 1, stk_cd, tick_type, count(*),
        (array_agg(cur_prc ORDER BY created_at, id) FILTER (WHERE cur_prc IS NOT NULL))[1],
        max(cur_prc), min(cur_prc),
        (array_agg(cur_prc ORDER BY created_at DESC, id DESC) FILTER (WHERE cur_prc IS NOT NULL))[1],
        avg(flu_rt), max(acc_trde_qty), max(acc_trde_prica), avg(cntr_str),
        avg(bid_ask_ratio), bool_or(must_persist), NOW()
    FROM ws_tick_data_partitioned
    WHERE created_at >= p_from AND created_at < p_to
    GROUP BY 1, stk_cd, tick_type
    ON CONFLICT (bucket_started_at, bucket_minutes, stk_cd, tick_type)
    DO UPDATE SET
        sample_count = EXCLUDED.sample_count,
        open_prc = EXCLUDED.open_prc,
        high_prc = EXCLUDED.high_prc,
        low_prc = EXCLUDED.low_prc,
        close_prc = EXCLUDED.close_prc,
        avg_flu_rt = EXCLUDED.avg_flu_rt,
        max_acc_trde_qty = EXCLUDED.max_acc_trde_qty,
        max_acc_trde_prica = EXCLUDED.max_acc_trde_prica,
        avg_cntr_str = EXCLUDED.avg_cntr_str,
        avg_bid_ask_ratio = EXCLUDED.avg_bid_ask_ratio,
        must_persist = EXCLUDED.must_persist,
        updated_at = NOW();
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

COMMENT ON FUNCTION refresh_ws_tick_summary_1m IS
    'Idempotent one-minute summary producer. Retention must remain disabled until coverage and replay checks pass.';
