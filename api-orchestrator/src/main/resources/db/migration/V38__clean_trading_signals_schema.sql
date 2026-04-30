-- V38__clean_trading_signals_schema.sql
-- Remove the legacy S7_AUCTION value from trading_signals.strategy CHECK constraint.

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
