# Strategy Thresholds

Canonical source: `ai-engine/strategy_meta.py`.

Do not maintain separate Claude/rule threshold tables in `scorer.py`, `stockScore.py`, tests, or docs. Import `get_threshold()` or `get_claude_threshold()` instead.

| Strategy | Threshold |
| --- | ---: |
| S1_GAP_OPEN | 55 |
| S2_VI_PULLBACK | 65 |
| S3_INST_FRGN | 60 |
| S4_BIG_CANDLE | 65 |
| S5_PROG_FRGN | 65 |
| S6_THEME_LAGGARD | 60 |
| S7_ICHIMOKU_BREAKOUT | 62 |
| S8_GOLDEN_CROSS | 50 |
| S9_PULLBACK_SWING | 45 |
| S10_NEW_HIGH | 48 |
| S11_FRGN_CONT | 58 |
| S12_CLOSING | 60 |
| S13_BOX_BREAKOUT | 55 |
| S14_OVERSOLD_BOUNCE | 50 |
| S15_MOMENTUM_ALIGN | 65 |
