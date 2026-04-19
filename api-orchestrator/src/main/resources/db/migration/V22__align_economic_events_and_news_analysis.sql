-- V22: economic_events · news_analysis 스키마를 JPA 엔티티에 맞게 정합
-- 원인: V1 baseline 이 구형 컬럼(title, headline, sector 등)으로 테이블을 생성했으나
--       이후 엔티티 리팩토링으로 컬럼 구조가 변경됨.
--       ddl-auto:update 환경에서는 Hibernate 이 자동 추가했으나,
--       ddl-auto:validate 전환 후 신규 DB 기동 시 validate 실패 위험.
-- 수정: ADD COLUMN IF NOT EXISTS 로 멱등하게 누락 컬럼 추가.
--       기존 production DB 에는 이미 컬럼이 존재하므로 IF NOT EXISTS 로 안전.

-- ── economic_events ────────────────────────────────────────────────────────
-- EconomicEvent 엔티티 기준 누락 컬럼 추가
ALTER TABLE economic_events
    ADD COLUMN IF NOT EXISTS event_name      VARCHAR(100) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS event_type      VARCHAR(20)  NOT NULL DEFAULT 'CUSTOM',
    ADD COLUMN IF NOT EXISTS event_time      TIME,
    ADD COLUMN IF NOT EXISTS expected_impact VARCHAR(10)  NOT NULL DEFAULT 'MEDIUM',
    ADD COLUMN IF NOT EXISTS description     TEXT,
    ADD COLUMN IF NOT EXISTS notified        BOOLEAN      NOT NULL DEFAULT FALSE;

-- EconomicEvent 엔티티가 요구하는 시퀀스 (BIGSERIAL이 생성한 economic_events_id_seq 와 별도)
CREATE SEQUENCE IF NOT EXISTS economic_events_seq
    START WITH 1
    INCREMENT BY 10;

-- ── news_analysis ──────────────────────────────────────────────────────────
-- NewsAnalysis 엔티티 기준 누락 컬럼 추가
ALTER TABLE news_analysis
    ADD COLUMN IF NOT EXISTS sectors      TEXT,
    ADD COLUMN IF NOT EXISTS risk_factors TEXT,
    ADD COLUMN IF NOT EXISTS summary      TEXT,
    ADD COLUMN IF NOT EXISTS confidence   VARCHAR(10),
    ADD COLUMN IF NOT EXISTS news_count   INTEGER;

-- NewsAnalysis 엔티티가 요구하는 시퀀스
CREATE SEQUENCE IF NOT EXISTS news_analysis_seq
    START WITH 1
    INCREMENT BY 10;

-- 인덱스 보강 (EconomicEvent 엔티티 @Index 선언과 일치)
CREATE INDEX IF NOT EXISTS idx_event_date   ON economic_events(event_date);
CREATE INDEX IF NOT EXISTS idx_event_impact ON economic_events(expected_impact);
CREATE INDEX IF NOT EXISTS idx_news_analysis_at ON news_analysis(analyzed_at);
