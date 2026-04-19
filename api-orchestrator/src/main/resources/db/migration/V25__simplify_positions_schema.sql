-- V25: open_positions 스키마 간소화 + 미사용 테이블 정리
--
-- 설계 변경 요약:
--   포지션 종료(TP/SL/trailing stop) 시 open_positions 행을 DELETE 하는 플로우로 전환.
--   따라서 청산 완료 전용 컬럼들이 불필요해졌고, CLOSED/CLOSING 상태 또한 제거.
--   trading_signals 쪽의 exit_type/exit_pnl_pct 등은 이력 목적으로 그대로 유지.
--
-- 영향 범위:
--   - open_positions : CLOSED 행 삭제, 청산 컬럼 4개 DROP, CHECK 제약 추가
--   - v_active_positions : open_positions 참조 뷰 — 재작성
--   - v_portfolio_risk_snapshot : open_positions 참조 뷰 — 재작성
--   - sector_daily_stats : 미사용 테이블 — DROP
--   - economic_events : INSERT 경로 없는 미사용 테이블 — DROP (시퀀스 포함)

-- ============================================================
-- STEP 1. 뷰 선제 DROP
-- open_positions 컬럼을 참조하는 뷰는 ALTER TABLE 전에 반드시 DROP.
-- v_strategy_performance_30d, v_score_outcome_correlation 은
-- trading_signals 만 참조하므로 이 단계에서는 건드리지 않음.
-- ============================================================

DROP VIEW IF EXISTS v_active_positions;
DROP VIEW IF EXISTS v_portfolio_risk_snapshot;

-- ============================================================
-- STEP 2. CLOSED 행 삭제
-- 새 플로우에서 포지션 종료 = DELETE 이므로 기존 CLOSED 행은 불필요.
-- CLOSING 상태도 과도기 상태이므로 함께 제거.
-- ============================================================

DELETE FROM open_positions
WHERE status IN ('CLOSED', 'CLOSING');

-- ============================================================
-- STEP 3. 청산 전용 컬럼 DROP
-- 포지션 종료 후 행을 DELETE 하므로 아래 컬럼은 더 이상 의미 없음.
--   closed_at        — 청산 시각
--   exit_type        — TP1_HIT / TP2_HIT / SL_HIT / FORCE_CLOSE / MANUAL
--   exit_price       — 청산 가격
--   realized_pnl_pct — 실현 손익률
-- 주의: realized_pnl_abs / hold_duration_min 은 요구사항에 없으므로 유지.
-- ============================================================

ALTER TABLE open_positions
    DROP COLUMN IF EXISTS closed_at,
    DROP COLUMN IF EXISTS exit_type,
    DROP COLUMN IF EXISTS exit_price,
    DROP COLUMN IF EXISTS realized_pnl_pct;

-- ============================================================
-- STEP 4. status CHECK 제약 추가
-- 기존 V4 에서 status 는 명시적 CHECK 없이 VARCHAR(20) 으로만 정의됨.
-- 새 플로우에서 허용 값: ACTIVE / PARTIAL_TP / OVERNIGHT
-- CLOSED / CLOSING 은 이제 유효하지 않으므로 DB 수준에서 차단.
-- ============================================================

ALTER TABLE open_positions
    ADD CONSTRAINT chk_op_status
        CHECK (status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT'));

-- ============================================================
-- STEP 5. 뷰 재생성
-- open_positions 를 참조하는 두 뷰를 새 컬럼 구조에 맞게 재작성.
-- 삭제된 컬럼(closed_at, exit_type, exit_price, realized_pnl_pct) 참조 제거.
-- ============================================================

-- v_active_positions — 활성 포지션 현황
-- 변경: closed_at / exit_type / exit_price / realized_pnl_pct 참조 제거.
-- 뷰 자체의 컬럼 구성은 유지하되 삭제된 컬럼은 자연히 빠짐.
CREATE OR REPLACE VIEW v_active_positions AS
SELECT
    op.id,
    op.stk_cd,
    COALESCE(sm.stk_nm, op.stk_nm)     AS stk_nm,
    sm.sector,
    op.strategy,
    op.entry_price,
    op.entry_at,
    op.tp1_price,
    op.sl_price,
    op.rr_ratio,
    op.status,
    op.is_overnight,
    op.rule_score,
    op.peak_price,
    op.trailing_pct,
    op.monitor_enabled,
    EXTRACT(EPOCH FROM (NOW() - op.entry_at)) / 60 AS hold_min_so_far,
    ts.ai_reason,
    ts.tp_method,
    ts.sl_method
FROM open_positions op
LEFT JOIN stock_master sm ON sm.stk_cd = op.stk_cd
LEFT JOIN trading_signals ts ON ts.id = op.signal_id
WHERE op.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');

-- v_portfolio_risk_snapshot — 현재 포트폴리오 리스크 상태
-- 변경: open_positions 참조는 유지, 삭제 컬럼 참조 없으므로 구조 동일.
-- STEP 1 에서 DROP 됐으므로 여기서 재생성.
CREATE OR REPLACE VIEW v_portfolio_risk_snapshot AS
SELECT
    pc.total_capital,
    pc.max_position_count,
    pc.max_sector_pct,
    pc.daily_loss_limit_pct,

    COUNT(op.id)                                            AS active_position_count,
    COALESCE(SUM(op.entry_amount), 0)                       AS total_allocated,
    ROUND(100.0 * COALESCE(SUM(op.entry_amount), 0)
          / NULLIF(pc.total_capital, 0), 2)                 AS allocation_pct,
    COUNT(op.id) FILTER (WHERE op.is_overnight = TRUE)      AS overnight_count,

    dp.net_pnl_pct                                          AS today_pnl_pct,
    dp.daily_loss_limit_hit,
    dp.current_drawdown_pct

FROM portfolio_config pc
LEFT JOIN open_positions op ON op.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
LEFT JOIN daily_pnl dp ON dp.date = CURRENT_DATE
GROUP BY pc.total_capital, pc.max_position_count, pc.max_sector_pct,
         pc.daily_loss_limit_pct, dp.net_pnl_pct, dp.daily_loss_limit_hit,
         dp.current_drawdown_pct;

-- ============================================================
-- STEP 6. sector_daily_stats 테이블 삭제
-- V12 에서 생성됐으나 코드 어디에서도 INSERT/SELECT 경로가 없는 데드 스키마.
-- 의존 객체(인덱스 idx_sector_stats_date) 는 CASCADE 로 함께 삭제됨.
-- ============================================================

DROP TABLE IF EXISTS sector_daily_stats CASCADE;

-- STEP 7. economic_events 는 JPA 엔티티 매핑이 살아있어 DROP 생략.
-- INSERT 경로 없음 — EconomicCalendarScheduler @Component 주석 처리로 스케줄러만 비활성화.
