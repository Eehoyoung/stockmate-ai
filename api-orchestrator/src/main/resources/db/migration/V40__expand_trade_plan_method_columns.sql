-- V40: trade_plans TP/SL model columns must match trading_signals.tp_method/sl_method.
-- Python ai-engine stores descriptive TP/SL method strings in trade_plans as well as
-- trading_signals. The original VARCHAR(50) limit caused full signal insert rollbacks.

ALTER TABLE trade_plans
    ALTER COLUMN tp_model TYPE VARCHAR(200);

ALTER TABLE trade_plans
    ALTER COLUMN sl_model TYPE VARCHAR(200);

ALTER TABLE trade_plans
    ALTER COLUMN trailing_rule TYPE VARCHAR(200);

ALTER TABLE trade_plans
    ALTER COLUMN partial_tp_rule TYPE VARCHAR(100);

ALTER TABLE trade_plans
    ALTER COLUMN planned_exit_priority TYPE VARCHAR(100);
