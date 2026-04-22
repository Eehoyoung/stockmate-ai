-- V30: trading_signals를 신호 이력 + 활성 포지션 단일 원장으로 확장
-- 운영 런타임은 더 이상 open_positions를 참조하지 않는다.
-- 기존 open_positions 데이터는 trading_signals로 역이관한다.

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS legacy_open_position_id BIGINT,
    ADD COLUMN IF NOT EXISTS position_status      VARCHAR(20),
    ADD COLUMN IF NOT EXISTS sector               VARCHAR(50),
    ADD COLUMN IF NOT EXISTS entry_qty            INTEGER,
    ADD COLUMN IF NOT EXISTS entry_amount         NUMERIC(14,0),
    ADD COLUMN IF NOT EXISTS entry_at             TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tp1_hit_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tp1_exit_qty         INTEGER,
    ADD COLUMN IF NOT EXISTS remaining_qty        INTEGER,
    ADD COLUMN IF NOT EXISTS peak_price           NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS trailing_pct         NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS trailing_activation  NUMERIC(10,0),
    ADD COLUMN IF NOT EXISTS trailing_basis       VARCHAR(40),
    ADD COLUMN IF NOT EXISTS strategy_version     VARCHAR(40),
    ADD COLUMN IF NOT EXISTS time_stop_type       VARCHAR(30),
    ADD COLUMN IF NOT EXISTS time_stop_minutes    INTEGER,
    ADD COLUMN IF NOT EXISTS time_stop_session    VARCHAR(30),
    ADD COLUMN IF NOT EXISTS monitor_enabled      BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_overnight         BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS overnight_verdict    VARCHAR(20),
    ADD COLUMN IF NOT EXISTS overnight_score      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS sl_alert_sent        BOOLEAN DEFAULT FALSE;

UPDATE trading_signals ts
SET
    legacy_open_position_id = op.id,
    position_status     = op.status,
    sector              = COALESCE(ts.sector, op.sector),
    entry_qty           = COALESCE(ts.entry_qty, op.entry_qty),
    entry_amount        = COALESCE(ts.entry_amount, op.entry_amount),
    entry_at            = COALESCE(ts.entry_at, op.entry_at),
    tp1_hit_at          = COALESCE(ts.tp1_hit_at, op.tp1_hit_at),
    tp1_exit_qty        = COALESCE(ts.tp1_exit_qty, op.tp1_exit_qty),
    remaining_qty       = COALESCE(ts.remaining_qty, op.remaining_qty),
    peak_price          = COALESCE(ts.peak_price, op.peak_price),
    trailing_pct        = COALESCE(ts.trailing_pct, op.trailing_pct),
    trailing_activation = COALESCE(ts.trailing_activation, op.trailing_activation),
    trailing_basis      = COALESCE(ts.trailing_basis, op.trailing_basis),
    strategy_version    = COALESCE(ts.strategy_version, op.strategy_version),
    time_stop_type      = COALESCE(ts.time_stop_type, op.time_stop_type),
    time_stop_minutes   = COALESCE(ts.time_stop_minutes, op.time_stop_minutes),
    time_stop_session   = COALESCE(ts.time_stop_session, op.time_stop_session),
    monitor_enabled     = COALESCE(ts.monitor_enabled, op.monitor_enabled),
    is_overnight        = COALESCE(ts.is_overnight, op.is_overnight),
    overnight_verdict   = COALESCE(ts.overnight_verdict, op.overnight_verdict),
    overnight_score     = COALESCE(ts.overnight_score, op.overnight_score),
    sl_alert_sent       = COALESCE(ts.sl_alert_sent, op.sl_alert_sent)
FROM open_positions op
WHERE op.signal_id = ts.id;

UPDATE trading_signals
SET entry_at = COALESCE(entry_at, executed_at::timestamptz, created_at::timestamptz)
WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
  AND entry_at IS NULL;

UPDATE trading_signals
SET monitor_enabled = TRUE
WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
  AND monitor_enabled IS NULL;

UPDATE trading_signals
SET position_status = 'CLOSED'
WHERE position_status IS NULL
  AND action = 'ENTER'
  AND (
      exit_type IS NOT NULL
      OR signal_status IN ('WIN', 'LOSS', 'EXPIRED')
  );

CREATE INDEX IF NOT EXISTS idx_ts_position_status
    ON trading_signals(position_status)
    WHERE position_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ts_active_stk
    ON trading_signals(stk_cd, position_status)
    WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');

CREATE INDEX IF NOT EXISTS idx_ts_active_entry
    ON trading_signals(position_status, entry_at)
    WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');

ALTER TABLE trading_signals
    DROP CONSTRAINT IF EXISTS chk_ts_position_status;

ALTER TABLE trading_signals
    ADD CONSTRAINT chk_ts_position_status
        CHECK (
            position_status IS NULL OR
            position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT', 'CLOSED')
        );

DROP VIEW IF EXISTS v_active_positions;
DROP VIEW IF EXISTS v_portfolio_risk_snapshot;

CREATE OR REPLACE VIEW v_active_positions AS
SELECT
    ts.id,
    ts.stk_cd,
    COALESCE(sm.stk_nm, ts.stk_nm) AS stk_nm,
    COALESCE(ts.sector, sm.sector) AS sector,
    ts.strategy,
    ts.entry_price,
    ts.entry_at,
    ts.tp1_price,
    ts.sl_price,
    ts.rr_ratio,
    ts.position_status AS status,
    ts.is_overnight,
    ts.rule_score,
    ts.peak_price,
    ts.trailing_pct,
    ts.monitor_enabled,
    EXTRACT(EPOCH FROM (NOW() - ts.entry_at)) / 60 AS hold_min_so_far,
    ts.ai_reason,
    ts.tp_method,
    ts.sl_method
FROM trading_signals ts
LEFT JOIN stock_master sm ON sm.stk_cd = ts.stk_cd
WHERE ts.position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');

CREATE OR REPLACE VIEW v_portfolio_risk_snapshot AS
SELECT
    pc.total_capital,
    pc.max_position_count,
    pc.max_sector_pct,
    pc.daily_loss_limit_pct,
    COUNT(ts.id) AS active_position_count,
    COALESCE(SUM(ts.entry_amount), 0) AS total_allocated,
    ROUND(100.0 * COALESCE(SUM(ts.entry_amount), 0) / NULLIF(pc.total_capital, 0), 2) AS allocation_pct,
    COUNT(ts.id) FILTER (WHERE ts.is_overnight = TRUE) AS overnight_count,
    dp.net_pnl_pct AS today_pnl_pct,
    dp.daily_loss_limit_hit,
    dp.current_drawdown_pct
FROM portfolio_config pc
LEFT JOIN trading_signals ts ON ts.position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
LEFT JOIN daily_pnl dp ON dp.date = CURRENT_DATE
GROUP BY pc.total_capital, pc.max_position_count, pc.max_sector_pct,
         pc.daily_loss_limit_pct, dp.net_pnl_pct, dp.daily_loss_limit_hit,
         dp.current_drawdown_pct;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'open_positions'
    ) THEN
        EXECUTE 'ALTER TABLE open_positions RENAME TO open_positions_legacy';
    END IF;
END $$;

CREATE OR REPLACE VIEW open_positions AS
SELECT
    COALESCE(ts.legacy_open_position_id, ts.id) AS id,
    ts.id AS signal_id,
    ts.stk_cd,
    ts.stk_nm,
    ts.strategy::varchar(30) AS strategy,
    ts.market_type AS market,
    ts.sector,
    ts.entry_price::numeric(10,0) AS entry_price,
    ts.entry_qty,
    ts.entry_amount,
    ts.entry_at,
    ts.tp1_price::numeric(10,0) AS tp1_price,
    ts.tp2_price::numeric(10,0) AS tp2_price,
    ts.sl_price::numeric(10,0) AS sl_price,
    ts.tp_method,
    ts.sl_method,
    ts.rr_ratio,
    ts.position_status AS status,
    ts.tp1_hit_at,
    ts.tp1_exit_qty,
    ts.remaining_qty,
    ts.is_overnight,
    ts.overnight_verdict,
    ts.overnight_score,
    ts.sl_alert_sent,
    ts.rule_score,
    ts.ai_score,
    ts.peak_price,
    ts.trailing_pct,
    ts.monitor_enabled,
    ts.trailing_activation,
    ts.trailing_basis,
    ts.strategy_version,
    ts.time_stop_type,
    ts.time_stop_minutes,
    ts.time_stop_session
FROM trading_signals ts
WHERE ts.position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT', 'CLOSED');

CREATE OR REPLACE FUNCTION sync_open_positions_view()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE trading_signals
        SET legacy_open_position_id = COALESCE(NEW.id, legacy_open_position_id),
            sector = NEW.sector,
            entry_qty = NEW.entry_qty,
            entry_amount = NEW.entry_amount,
            entry_at = COALESCE(NEW.entry_at, entry_at),
            tp1_price = COALESCE(NEW.tp1_price::double precision, tp1_price),
            tp2_price = COALESCE(NEW.tp2_price::double precision, tp2_price),
            sl_price = COALESCE(NEW.sl_price::double precision, sl_price),
            tp_method = COALESCE(NEW.tp_method, tp_method),
            sl_method = COALESCE(NEW.sl_method, sl_method),
            rr_ratio = COALESCE(NEW.rr_ratio, rr_ratio),
            position_status = COALESCE(NEW.status, position_status),
            tp1_hit_at = NEW.tp1_hit_at,
            tp1_exit_qty = NEW.tp1_exit_qty,
            remaining_qty = NEW.remaining_qty,
            is_overnight = COALESCE(NEW.is_overnight, is_overnight),
            overnight_verdict = NEW.overnight_verdict,
            overnight_score = NEW.overnight_score,
            sl_alert_sent = COALESCE(NEW.sl_alert_sent, sl_alert_sent),
            rule_score = COALESCE(NEW.rule_score, rule_score),
            ai_score = COALESCE(NEW.ai_score, ai_score),
            peak_price = NEW.peak_price,
            trailing_pct = NEW.trailing_pct,
            monitor_enabled = COALESCE(NEW.monitor_enabled, monitor_enabled),
            trailing_activation = NEW.trailing_activation,
            trailing_basis = NEW.trailing_basis,
            strategy_version = NEW.strategy_version,
            time_stop_type = NEW.time_stop_type,
            time_stop_minutes = NEW.time_stop_minutes,
            time_stop_session = NEW.time_stop_session
        WHERE id = NEW.signal_id;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        UPDATE trading_signals
        SET sector = NEW.sector,
            entry_qty = NEW.entry_qty,
            entry_amount = NEW.entry_amount,
            entry_at = NEW.entry_at,
            tp1_price = NEW.tp1_price::double precision,
            tp2_price = NEW.tp2_price::double precision,
            sl_price = NEW.sl_price::double precision,
            tp_method = NEW.tp_method,
            sl_method = NEW.sl_method,
            rr_ratio = NEW.rr_ratio,
            position_status = NEW.status,
            tp1_hit_at = NEW.tp1_hit_at,
            tp1_exit_qty = NEW.tp1_exit_qty,
            remaining_qty = NEW.remaining_qty,
            is_overnight = NEW.is_overnight,
            overnight_verdict = NEW.overnight_verdict,
            overnight_score = NEW.overnight_score,
            sl_alert_sent = NEW.sl_alert_sent,
            rule_score = NEW.rule_score,
            ai_score = NEW.ai_score,
            peak_price = NEW.peak_price,
            trailing_pct = NEW.trailing_pct,
            monitor_enabled = NEW.monitor_enabled,
            trailing_activation = NEW.trailing_activation,
            trailing_basis = NEW.trailing_basis,
            strategy_version = NEW.strategy_version,
            time_stop_type = NEW.time_stop_type,
            time_stop_minutes = NEW.time_stop_minutes,
            time_stop_session = NEW.time_stop_session
        WHERE id = NEW.signal_id;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE trading_signals
        SET position_status = 'CLOSED',
            monitor_enabled = FALSE
        WHERE id = OLD.signal_id;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_open_positions_view ON open_positions;
CREATE TRIGGER trg_sync_open_positions_view
INSTEAD OF INSERT OR UPDATE OR DELETE ON open_positions
FOR EACH ROW
EXECUTE FUNCTION sync_open_positions_view();
