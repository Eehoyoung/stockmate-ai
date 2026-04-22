-- V28: vi_events 기본키 생성 전략을 DB 기본 시퀀스와 일치시킨다.
-- 원인:
--   - 테이블 기본값은 BIGSERIAL 계열 시퀀스(vi_events_id_seq)를 사용
--   - JPA ViEvent 엔티티는 vi_events_seq 시퀀스를 별도로 사용
--   - 두 시퀀스가 서로 다른 값을 가리키면서 duplicate key(id) 충돌 발생
--
-- 조치:
--   1. vi_events.id 기본값을 vi_events_id_seq로 고정
--   2. vi_events_id_seq 값을 현재 MAX(id) 다음으로 재정렬

CREATE SEQUENCE IF NOT EXISTS vi_events_id_seq;

ALTER TABLE vi_events
    ALTER COLUMN id SET DEFAULT nextval('vi_events_id_seq');

ALTER SEQUENCE vi_events_id_seq
    OWNED BY vi_events.id;

SELECT setval(
    'vi_events_id_seq',
    COALESCE((SELECT MAX(id) FROM vi_events WHERE id IS NOT NULL), 0) + 1,
    false
);
