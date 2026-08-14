-- V53__add_s16_to_trading_signals_strategy_check.sql
-- Add S16_ACCUMULATION_SHADOW to the trading_signals.strategy CHECK constraint.
--
-- S16 is a fully registered strategy on the Python side (strategy_meta.py:
-- SWING_STRATEGIES / CLAUDE_THRESHOLDS / STRATEGY_BASE_RR_GATES / STRATEGY_RR_GROUPS,
-- and strategy_runner.py _scan_s16 + MANUAL_RUN_STRATEGIES), but the constraint
-- last rewritten in V38 still only allowed S1..S15. Any S16 signal therefore
-- failed to insert, which is why S16 has produced 0 rows since it shipped.

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
            'S15_MOMENTUM_ALIGN',
            'S16_ACCUMULATION_SHADOW'
        ]::text[]));
