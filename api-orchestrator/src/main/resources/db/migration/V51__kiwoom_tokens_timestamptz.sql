-- V51__kiwoom_tokens_timestamptz.sql
-- 생성일: 2026-07-26
-- 설명: kiwoom_tokens.updated_at/expires_at을 다른 주요 테이블과 동일한
--       timestamp with time zone으로 변환한다. 기존 값은 DB 세션 타임존인
--       Asia/Seoul 기준의 벽시계 시각으로 저장되어 있으므로 AT TIME ZONE으로
--       동일 시점을 유지한 채 timestamptz로 변환한다.

ALTER TABLE kiwoom_tokens
    ALTER COLUMN updated_at TYPE timestamptz
    USING updated_at AT TIME ZONE 'Asia/Seoul';

ALTER TABLE kiwoom_tokens
    ALTER COLUMN expires_at TYPE timestamptz
    USING expires_at AT TIME ZONE 'Asia/Seoul';
