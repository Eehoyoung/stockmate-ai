-- Normalize Kiwoom market suffixes such as _AL / _NX to the canonical 6-digit stock code.

-- Delete rows that would collide with an already-normalized key first.
DELETE FROM stock_master sm
WHERE sm.stk_cd LIKE '%\_%' ESCAPE '\'
  AND EXISTS (
      SELECT 1
      FROM stock_master base
      WHERE base.stk_cd = split_part(sm.stk_cd, '_', 1)
  );

DELETE FROM daily_indicators di
WHERE di.stk_cd LIKE '%\_%' ESCAPE '\'
  AND EXISTS (
      SELECT 1
      FROM daily_indicators base
      WHERE base.date = di.date
        AND base.stk_cd = split_part(di.stk_cd, '_', 1)
  );

DELETE FROM candidate_pool_history cph
WHERE cph.stk_cd LIKE '%\_%' ESCAPE '\'
  AND EXISTS (
      SELECT 1
      FROM candidate_pool_history base
      WHERE base.date = cph.date
        AND base.strategy = cph.strategy
        AND base.market = cph.market
        AND base.stk_cd = split_part(cph.stk_cd, '_', 1)
  );

-- Normalize remaining rows in every table that stores stk_cd.
UPDATE trading_signals
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE open_positions
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE risk_events
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE stock_master
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE daily_indicators
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE overnight_evaluations
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE candidate_pool_history
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE vi_events
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';

UPDATE ws_tick_data
SET stk_cd = split_part(stk_cd, '_', 1)
WHERE stk_cd LIKE '%\_%' ESCAPE '\';
