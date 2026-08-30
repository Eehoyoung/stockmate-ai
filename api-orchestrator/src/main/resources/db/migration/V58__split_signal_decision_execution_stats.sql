ALTER TABLE daily_pnl
    ADD COLUMN IF NOT EXISTS decision_enter_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS watch_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_expired_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE strategy_daily_stats
    ADD COLUMN IF NOT EXISTS decision_enter_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS watch_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_expired_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN daily_pnl.enter_count IS '실제 체결 증거(executed_at 및 entry_qty)가 있는 신호 수';
COMMENT ON COLUMN daily_pnl.decision_enter_count IS '최종 execution_decision=ENTER 신호 수';
COMMENT ON COLUMN daily_pnl.signal_expired_count IS 'trading_signals.signal_status=EXPIRED 신호 수';
