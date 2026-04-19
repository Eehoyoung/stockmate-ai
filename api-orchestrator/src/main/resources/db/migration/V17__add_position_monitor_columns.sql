-- V17: open_positions 포지션 모니터링 컬럼 추가
-- position_monitor.py 가 트레일링 스탑 · 추세 반전 감지에 사용
-- 쓰기 주체: Python ai-engine/position_monitor.py

ALTER TABLE open_positions
    ADD COLUMN IF NOT EXISTS peak_price      NUMERIC(10, 0),
    ADD COLUMN IF NOT EXISTS trailing_pct    NUMERIC(5, 2) DEFAULT 1.5,
    ADD COLUMN IF NOT EXISTS monitor_enabled BOOLEAN       DEFAULT TRUE;

COMMENT ON COLUMN open_positions.peak_price      IS 'TP1 도달 후 고가 추적 (트레일링 스탑 기준)';
COMMENT ON COLUMN open_positions.trailing_pct    IS '트레일링 스탑 낙폭 % (기본 1.5%)';
COMMENT ON COLUMN open_positions.monitor_enabled IS 'position_monitor.py 감시 활성 여부';
