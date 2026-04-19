-- V16: candidate_pool_history UNIQUE 제약 보완
-- V13의 CREATE TABLE IF NOT EXISTS 가 이미 존재하는 테이블을 스킵하면서
-- UNIQUE(date, strategy, market, stk_cd) 제약이 누락된 경우를 사후 보정한다.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint
        WHERE  conrelid = 'candidate_pool_history'::regclass
          AND  contype   = 'u'
          AND  conname   = 'candidate_pool_history_date_strategy_market_stk_cd_key'
    ) THEN
        ALTER TABLE candidate_pool_history
            ADD CONSTRAINT candidate_pool_history_date_strategy_market_stk_cd_key
            UNIQUE (date, strategy, market, stk_cd);
    END IF;
END
$$;
