-- V20: vi_events.id 시퀀스 복구
-- 원인: Hibernate ddl-auto:update 가 BIGSERIAL 컬럼을 bigint NOT NULL 로 재생성하면서
--       DEFAULT nextval() 이 제거됨 → VI 이벤트 INSERT 시 null violation 으로 실패
-- 수정: 시퀀스 생성 후 id 컬럼 DEFAULT 복구. 기존 최대값 이후부터 채번.

CREATE SEQUENCE IF NOT EXISTS vi_events_id_seq;

ALTER TABLE vi_events
    ALTER COLUMN id SET DEFAULT nextval('vi_events_id_seq');

SELECT setval(
    'vi_events_id_seq',
    COALESCE((SELECT MAX(id) FROM vi_events WHERE id IS NOT NULL), 0) + 1,
    false
);
