-- KST 2026-08-18~2026-08-21 ENTER 신호 재현 쿼리
SELECT created_at::date AS 거래일,
       count(*) AS 전체_신호,
       count(*) FILTER (WHERE execution_decision = 'ENTER') AS 진입,
       count(*) FILTER (WHERE execution_decision = 'WATCH') AS 관심,
       count(*) FILTER (WHERE execution_decision = 'BLOCK') AS 차단
FROM trading_signals
WHERE created_at >= '2026-08-18 00:00:00+09'
  AND created_at <  '2026-08-22 00:00:00+09'
GROUP BY 1
ORDER BY 1;

SELECT id, created_at, stk_cd, stk_nm, strategy, strategy_family,
       entry_price, tp1_price, tp2_price, sl_price,
       effective_rr, min_rr_ratio, rule_score, ai_score,
       signal_status, position_status, blocking_reasons,
       data_source, source_timestamp, source_age_ms
FROM trading_signals
WHERE created_at >= '2026-08-18 00:00:00+09'
  AND created_at <  '2026-08-22 00:00:00+09'
  AND execution_decision = 'ENTER'
ORDER BY created_at;

SELECT s.id AS signal_id,
       count(DISTINCT o.id) AS outcome_count,
       count(DISTINCT p.id) AS position_count
FROM trading_signals s
LEFT JOIN trade_outcomes o ON o.signal_id = s.id
LEFT JOIN open_positions p ON p.signal_id = s.id
WHERE s.id IN (4379, 4424)
GROUP BY s.id
ORDER BY s.id;
