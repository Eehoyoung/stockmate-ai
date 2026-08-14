-- V54: trading_signals에 실행 판정(execution_decision)과 판정 단계(decision_stage) 적재
--
-- 배경 (2026-08-14 관측):
-- RR 프리필터에 걸린 신호는 파이프라인 안에서 action=HOLD / execution_decision=WATCH로
-- 판정되고 텔레그램에도 HOLD_WATCH(관심종목)로 44건 나갔다. 그런데 DB에는
-- action='HOLD'가 한 건도 없었다. 장 마감 시 hold_monitor가 관심 해제하며 같은 행을
-- CANCEL로 UPDATE하기 때문이다.
--
-- 결과적으로 "처음부터 CANCEL이었던 신호"와 "WATCH였다가 해제된 신호"를 구분할 수
-- 없었고, HOLD -> ENTER 전환율을 DB로 측정하는 것이 불가능했다. ai_reason 문자열을
-- 매칭하는 방법밖에 없었다.
--
-- 주의: 이 두 컬럼도 최종 상태만 담는다. WATCH -> 해제 전이 이력 자체를 남기려면
-- 별도 이벤트 테이블이 필요하다. 여기서는 "지금 이 신호가 어떤 판정을 받았는가"를
-- 조회 가능하게 만드는 것까지만 한다.

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS execution_decision VARCHAR(10),
    ADD COLUMN IF NOT EXISTS decision_stage     VARCHAR(30);

COMMENT ON COLUMN trading_signals.execution_decision IS
    'ENTER/WATCH/BLOCK — action(ENTER/HOLD/CANCEL)의 정규화 값. scoring_pipeline.execution_decision 참조';
COMMENT ON COLUMN trading_signals.decision_stage IS
    '판정이 확정된 단계 (예: WATCH_RR, AI_REVIEW). 어느 게이트에서 갈렸는지 추적용';

-- 판정별 집계를 자주 돌리므로 인덱스를 둔다.
CREATE INDEX IF NOT EXISTS idx_ts_execution_decision
    ON trading_signals (execution_decision, created_at DESC)
    WHERE execution_decision IS NOT NULL;
