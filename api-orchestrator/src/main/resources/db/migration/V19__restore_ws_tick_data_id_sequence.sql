-- V19: ws_tick_data.id + trading_signals.id 시퀀스 복구
-- 원인: Hibernate ddl-auto:update 가 BIGSERIAL 컬럼을 bigint NOT NULL 로 재생성하면서
--       DEFAULT nextval() 이 제거됨 → INSERT 시 null violation 으로 실패
-- 수정: 시퀀스 생성 후 id 컬럼 DEFAULT 복구. 기존 최대값 이후부터 채번.

-- 1) ws_tick_data.id 시퀀스 복구
CREATE SEQUENCE IF NOT EXISTS ws_tick_data_id_seq;

ALTER TABLE ws_tick_data
    ALTER COLUMN id SET DEFAULT nextval('ws_tick_data_id_seq');

SELECT setval(
    'ws_tick_data_id_seq',
    COALESCE((SELECT MAX(id) FROM ws_tick_data WHERE id IS NOT NULL), 0) + 1,
    false
);

-- 2) trading_signals.id 시퀀스 복구
CREATE SEQUENCE IF NOT EXISTS trading_signals_id_seq;

ALTER TABLE trading_signals
    ALTER COLUMN id SET DEFAULT nextval('trading_signals_id_seq');

SELECT setval(
    'trading_signals_id_seq',
    COALESCE((SELECT MAX(id) FROM trading_signals WHERE id IS NOT NULL), 0) + 1,
    false
);
