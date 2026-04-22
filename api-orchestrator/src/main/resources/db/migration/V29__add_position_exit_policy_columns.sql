-- V29: open_positions 에 전략별 trailing/time-stop 메타를 저장한다.
-- Python tp_sl_engine / position_monitor 의 단일 기준을 DB에 보존하기 위한 컬럼.

ALTER TABLE open_positions
    ADD COLUMN IF NOT EXISTS trailing_activation NUMERIC(10, 0),
    ADD COLUMN IF NOT EXISTS trailing_basis      VARCHAR(40),
    ADD COLUMN IF NOT EXISTS strategy_version    VARCHAR(40),
    ADD COLUMN IF NOT EXISTS time_stop_type      VARCHAR(30),
    ADD COLUMN IF NOT EXISTS time_stop_minutes   INTEGER,
    ADD COLUMN IF NOT EXISTS time_stop_session   VARCHAR(30);

COMMENT ON COLUMN open_positions.trailing_activation IS 'TP1 이후 trailing 활성화 가격';
COMMENT ON COLUMN open_positions.trailing_basis IS 'trailing 기준 설명';
COMMENT ON COLUMN open_positions.strategy_version IS 'TP/SL 전략 버전';
COMMENT ON COLUMN open_positions.time_stop_type IS '시간청산 정책 유형';
COMMENT ON COLUMN open_positions.time_stop_minutes IS '시간청산 기준 분/거래일 수';
COMMENT ON COLUMN open_positions.time_stop_session IS '시간청산 세션 기준';
