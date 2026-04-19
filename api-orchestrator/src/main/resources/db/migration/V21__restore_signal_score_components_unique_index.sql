-- V21: signal_score_components.signal_id UNIQUE INDEX 복구
-- 원인: Hibernate ddl-auto:update 가 V3 에서 생성한
--       CREATE UNIQUE INDEX idx_ssc_signal_id 를 제거함
--       → db_writer.py insert_score_components() 의 ON CONFLICT (signal_id) 실패
-- 수정: UNIQUE INDEX 재생성

CREATE UNIQUE INDEX IF NOT EXISTS idx_ssc_signal_id
    ON signal_score_components (signal_id);
