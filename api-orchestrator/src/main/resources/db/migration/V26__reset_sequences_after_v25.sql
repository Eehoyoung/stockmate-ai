-- V26: V25 DDL 변경 후 시퀀스 리셋
-- Hibernate ddl-auto:update 가 V25 대규모 DDL 이후 시퀀스를 1로 초기화.
-- 기존 행 ID와 충돌 → vi_events_pkey / ws_tick_data_pkey duplicate key 에러.

SELECT setval('vi_events_id_seq',
    (SELECT COALESCE(MAX(id), 0) + 50 FROM vi_events), true);

SELECT setval('ws_tick_data_id_seq',
    (SELECT COALESCE(MAX(id), 0) + 200 FROM ws_tick_data), true);
