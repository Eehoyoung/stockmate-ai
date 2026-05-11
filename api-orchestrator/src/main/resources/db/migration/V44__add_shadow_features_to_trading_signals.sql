-- V44: trading_signals 에 shadow_features JSONB 컬럼 추가
-- Phase 3 shadow feature 관측·EV 검증 데이터 저장용.
-- ENTER/CANCEL gate 판단에는 미사용 — 2~4주 수집 후 Phase 4 에서 승격 여부 결정.
-- NULL 허용 컬럼만 추가 — PostgreSQL metadata-only 연산 (테이블 재작성 없음)

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS shadow_features JSONB;

COMMENT ON COLUMN trading_signals.shadow_features IS
    'Phase 3 shadow feature 관측값 — orderbook, relative_strength, tick_pressure, cvd, anchored_vwap, adx. Gate 판단 외 EV/MFE/MAE 분석용.';
