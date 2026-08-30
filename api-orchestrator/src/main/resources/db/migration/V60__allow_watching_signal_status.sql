ALTER TABLE trading_signals
    DROP CONSTRAINT IF EXISTS trading_signals_signal_status_check;

ALTER TABLE trading_signals
    ADD CONSTRAINT trading_signals_signal_status_check
    CHECK (signal_status IN (
        'PENDING', 'WATCHING', 'SENT', 'EXECUTED', 'WIN', 'LOSS',
        'EXPIRED', 'CANCELLED', 'OVERNIGHT_HOLD'
    ));
