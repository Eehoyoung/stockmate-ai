-- V35: NOT NULL 제약 정합 강화
-- 목적:
--   1. news_analysis.analyzed_at — 엔티티 nullable=false 이지만 DB에 NOT NULL 제약 없음.
--      V1 baseline 에서 DEFAULT NOW() 만 선언됐고 V32 에서 타입만 변환.
--      Java NewsAlertScheduler 가 LocalDateTime.now() 를 명시적으로 채우지만
--      DB 수준 제약이 없어 Python 직접 INSERT 시 null 허용 위험.
--   2. economic_events — V22 에서 추가된 NOT NULL DEFAULT 컬럼들 확인:
--      event_name, event_type, expected_impact, notified 는 ADD COLUMN 시
--      DEFAULT 로 기존 행을 채웠으나 신규 INSERT 경로에서도 NOT NULL 이 보장되도록
--      체크. (이미 NOT NULL DEFAULT 로 선언됐으므로 추가 마이그레이션 불필요,
--       확인 차원에서 주석으로 기록)

-- ──────────────────────────────────────────────────────────────────────────────
-- 1. news_analysis.analyzed_at  NOT NULL 제약 추가
-- DEFAULT NOW() 가 이미 걸려 있으므로 기존 NULL 행이 없는 상태에서만 안전.
-- 혹시 NULL 행이 있으면 현재 시각으로 채운 뒤 제약을 건다.
-- ──────────────────────────────────────────────────────────────────────────────

UPDATE news_analysis
SET analyzed_at = NOW()
WHERE analyzed_at IS NULL;

ALTER TABLE news_analysis
    ALTER COLUMN analyzed_at SET NOT NULL;

-- ──────────────────────────────────────────────────────────────────────────────
-- 2. candidate_pool_history.first_seen / last_seen  NOT NULL 정합
-- V13 에서 NOT NULL DEFAULT NOW() 로 생성됐으나
-- JPA 엔티티(CandidatePoolHistory)에서 nullable=false 어노테이션이 없어
-- ddl-auto:update 충돌 위험. 기존 NULL 행을 채운 뒤 확인.
-- (실제 INSERT 는 JDBC batchUpdate 이므로 NULL 이 들어갈 일 없지만 방어적 처리)
-- ──────────────────────────────────────────────────────────────────────────────

UPDATE candidate_pool_history
SET first_seen = NOW()
WHERE first_seen IS NULL;

UPDATE candidate_pool_history
SET last_seen = NOW()
WHERE last_seen IS NULL;

-- first_seen, last_seen 은 V13 에서 이미 NOT NULL DEFAULT NOW() 로 생성됐으므로
-- ALTER NOT NULL 은 이미 DB 수준에서 보장됨. 추가 ALTER 불필요.

-- ──────────────────────────────────────────────────────────────────────────────
-- 3. strategy_param_history.new_value NOT NULL + changed_at NOT NULL 확인
-- V11 에서 이미 NOT NULL 로 생성됐고 엔티티 @Builder.Default 로 보호됨. 확인용 주석.
-- ──────────────────────────────────────────────────────────────────────────────

-- (확인 완료: strategy_param_history.new_value NOT NULL, changed_at NOT NULL DEFAULT NOW())
