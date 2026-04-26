-- V34: 미사용 테이블 3종 정리
-- 대상 테이블 모두 어떤 Java 엔티티, Python db_writer/db_reader/rr_fit_report 에도
-- INSERT / SELECT / UPDATE 참조가 없음을 V33 이후 전체 코드베이스 검색으로 확인함.

-- ============================================================
-- 1. trade_path_bars
-- V31에서 생성. 분봉 바 단위 MFE/MAE 기록용이나 Python db_writer.py 와
-- 어떤 Java 서비스도 이 테이블에 데이터를 쓰지 않음.
-- signal_id → trading_signals(ON DELETE CASCADE),
-- plan_id   → trade_plans(ON DELETE CASCADE) FK 를 가지는 자식 테이블.
-- trade_plans 를 DROP 하기 전에 먼저 제거해야 한다.
-- CASCADE 를 명시해 혹시 남아있는 자식 참조까지 연쇄 제거.
-- ============================================================

DROP TABLE IF EXISTS trade_path_bars CASCADE;

-- ============================================================
-- 2. strategy_bucket_stats
-- V31에서 생성. 전략별 버킷 통계 누적 테이블이나
-- rr_fit_report.py 는 trading_signals 만 조회하고 이 테이블에는 절대 쓰지 않음.
-- Java 코드에도 참조 없음.
-- FK 없이 UNIQUE 제약(uq_strategy_bucket_stats) 만 보유하므로 단순 DROP.
-- ============================================================

DROP TABLE IF EXISTS strategy_bucket_stats CASCADE;

-- ============================================================
-- 3. open_positions_legacy
-- V30에서 기존 open_positions 테이블을 RENAME 한 것.
-- V30에서 데이터를 trading_signals 로 이관 완료.
-- 현재 open_positions 라는 이름으로는 VIEW 가 생성되어 운영 중.
-- open_positions_legacy 를 참조하는 코드 없음.
-- 이미 이전 환경에서 수동으로 DROP 됐을 수 있으므로 IF EXISTS 필수.
-- CASCADE 로 혹시 남아 있는 FK 자식 참조까지 연쇄 처리.
-- ============================================================

DROP TABLE IF EXISTS open_positions_legacy CASCADE;
