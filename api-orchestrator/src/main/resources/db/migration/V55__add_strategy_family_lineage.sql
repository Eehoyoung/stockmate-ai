-- Additive 16-setup -> 7-family lineage.  The legacy strategy column remains
-- the immutable setup id throughout compatibility/shadow operation.

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS strategy_family VARCHAR(3),
    ADD COLUMN IF NOT EXISTS strategy_family_name VARCHAR(40),
    ADD COLUMN IF NOT EXISTS primary_setup_id VARCHAR(40),
    ADD COLUMN IF NOT EXISTS matched_setup_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS family_policy_version VARCHAR(40),
    ADD COLUMN IF NOT EXISTS blocking_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS degraded_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS final_score NUMERIC(5,2);

ALTER TABLE trading_signals
    ADD CONSTRAINT trading_signals_strategy_family_check
        CHECK (strategy_family IS NULL OR strategy_family IN (
            'G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'G07'
        ));

UPDATE trading_signals
SET strategy_family = CASE strategy::text
        WHEN 'S1_GAP_OPEN' THEN 'G01'
        WHEN 'S2_VI_PULLBACK' THEN 'G01'
        WHEN 'S12_CLOSING' THEN 'G01'
        WHEN 'S3_INST_FRGN' THEN 'G02'
        WHEN 'S5_PROG_FRGN' THEN 'G02'
        WHEN 'S11_FRGN_CONT' THEN 'G02'
        WHEN 'S16_ACCUMULATION_SHADOW' THEN 'G03'
        WHEN 'S8_GOLDEN_CROSS' THEN 'G04'
        WHEN 'S9_PULLBACK_SWING' THEN 'G04'
        WHEN 'S15_MOMENTUM_ALIGN' THEN 'G04'
        WHEN 'S7_ICHIMOKU_BREAKOUT' THEN 'G05'
        WHEN 'S10_NEW_HIGH' THEN 'G05'
        WHEN 'S13_BOX_BREAKOUT' THEN 'G05'
        WHEN 'S4_BIG_CANDLE' THEN 'G06'
        WHEN 'S6_THEME_LAGGARD' THEN 'G06'
        WHEN 'S14_OVERSOLD_BOUNCE' THEN 'G07'
    END,
    strategy_family_name = CASE strategy::text
        WHEN 'S1_GAP_OPEN' THEN 'SESSION_EVENT'
        WHEN 'S2_VI_PULLBACK' THEN 'SESSION_EVENT'
        WHEN 'S12_CLOSING' THEN 'SESSION_EVENT'
        WHEN 'S3_INST_FRGN' THEN 'FLOW_TREND'
        WHEN 'S5_PROG_FRGN' THEN 'FLOW_TREND'
        WHEN 'S11_FRGN_CONT' THEN 'FLOW_TREND'
        WHEN 'S16_ACCUMULATION_SHADOW' THEN 'ACCUMULATION_CONFIRM'
        WHEN 'S8_GOLDEN_CROSS' THEN 'TREND_PHASE'
        WHEN 'S9_PULLBACK_SWING' THEN 'TREND_PHASE'
        WHEN 'S15_MOMENTUM_ALIGN' THEN 'TREND_PHASE'
        WHEN 'S7_ICHIMOKU_BREAKOUT' THEN 'STRUCTURAL_BREAKOUT'
        WHEN 'S10_NEW_HIGH' THEN 'STRUCTURAL_BREAKOUT'
        WHEN 'S13_BOX_BREAKOUT' THEN 'STRUCTURAL_BREAKOUT'
        WHEN 'S4_BIG_CANDLE' THEN 'INTRADAY_THEME_MOMENTUM'
        WHEN 'S6_THEME_LAGGARD' THEN 'INTRADAY_THEME_MOMENTUM'
        WHEN 'S14_OVERSOLD_BOUNCE' THEN 'REVERSAL_BOUNCE'
    END,
    primary_setup_id = strategy::text,
    matched_setup_ids = jsonb_build_array(strategy::text),
    family_policy_version = 'family_v1_2026_08_16'
WHERE strategy_family IS NULL;

CREATE INDEX IF NOT EXISTS idx_ts_family_created
    ON trading_signals(strategy_family, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ts_primary_setup_created
    ON trading_signals(primary_setup_id, created_at DESC);

COMMENT ON COLUMN trading_signals.strategy_family IS
    'Additive G01-G07 operation/risk family; never replaces legacy strategy setup id';
COMMENT ON COLUMN trading_signals.primary_setup_id IS
    'Immutable setup owning the trade plan; normally equal to legacy strategy during migration';
COMMENT ON COLUMN trading_signals.matched_setup_ids IS
    'All setup confirmations retained for attribution; never a quantity multiplier';
