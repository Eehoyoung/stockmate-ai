-- V42: 매수/매도 박스(Zone) 컬럼 추가
-- Phase 1 적용 전략: S8_GOLDEN_CROSS, S9_PULLBACK_SWING, S13_BOX_BREAKOUT,
--                   S14_OVERSOLD_BOUNCE, S15_MOMENTUM_ALIGN
-- NULL 허용 컬럼만 추가 — PostgreSQL metadata-only 연산 (테이블 재작성 없음)

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS buy_zone_low      NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS buy_zone_high     NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS buy_zone_anchors  TEXT,
    ADD COLUMN IF NOT EXISTS buy_zone_strength SMALLINT,
    ADD COLUMN IF NOT EXISTS sell_zone1_low    NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS sell_zone1_high   NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS sell_zone2_low    NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS sell_zone2_high   NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS zone_rr           NUMERIC(5,3);

COMMENT ON COLUMN trading_signals.buy_zone_low      IS '매수 박스 하단 (Phase 1: S8/S9/S13/S14/S15)';
COMMENT ON COLUMN trading_signals.buy_zone_high     IS '매수 박스 상단';
COMMENT ON COLUMN trading_signals.buy_zone_anchors  IS '매수 박스 근거 레벨 목록 (JSON array: ["MA20","BB_LOWER"])';
COMMENT ON COLUMN trading_signals.buy_zone_strength IS '매수 박스 강도 1~5 (anchor 수 기반)';
COMMENT ON COLUMN trading_signals.sell_zone1_low    IS '1차 매도 박스 하단';
COMMENT ON COLUMN trading_signals.sell_zone1_high   IS '1차 매도 박스 상단';
COMMENT ON COLUMN trading_signals.sell_zone2_low    IS '2차 매도 박스 하단 (Optional)';
COMMENT ON COLUMN trading_signals.sell_zone2_high   IS '2차 매도 박스 상단 (Optional)';
COMMENT ON COLUMN trading_signals.zone_rr           IS '존 기반 R:R — 최악 진입(buy_zone.high) 기준, 슬리피지 반영';
