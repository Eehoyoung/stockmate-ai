-- V36: stock_master.market_cap 컬럼 추가
-- ka10001 API 응답 mac(시가총액, 억 원) 필드를 저장.
-- StockMasterScheduler 09:10 배치에서 UPSERT 시 함께 갱신.
-- Python scorer.py 공통 패널티 블록에서 소형주(-15pt / -25pt) 필터로 사용.

ALTER TABLE stock_master
    ADD COLUMN IF NOT EXISTS market_cap BIGINT;

COMMENT ON COLUMN stock_master.market_cap IS '시가총액 (억 원, ka10001 mac 필드)';
