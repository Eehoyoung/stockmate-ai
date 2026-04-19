UPDATE portfolio_config
SET enabled_strategies = REPLACE(enabled_strategies::text, 'S7_AUCTION', 'S7_ICHIMOKU_BREAKOUT')::jsonb
WHERE enabled_strategies::text LIKE '%S7_AUCTION%';

UPDATE strategy_param_history
SET strategy = 'S7_ICHIMOKU_BREAKOUT'
WHERE strategy = 'S7_AUCTION';
