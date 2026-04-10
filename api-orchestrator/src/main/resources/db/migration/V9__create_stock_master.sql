-- V9: stock_master — 종목 기준 정보 (StockMasterScheduler 월요일 07:00 갱신)

CREATE TABLE IF NOT EXISTS stock_master (
    stk_cd          VARCHAR(20) PRIMARY KEY,
    stk_nm          VARCHAR(100) NOT NULL,
    market          VARCHAR(10),             -- 001=KOSPI, 101=KOSDAQ
    sector          VARCHAR(50),
    industry        VARCHAR(50),
    listed_at       DATE,
    par_value       INTEGER,
    listed_shares   BIGINT,
    is_active       BOOLEAN DEFAULT TRUE,
    last_price      NUMERIC(10,0),
    last_price_date DATE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sm_market ON stock_master(market);
CREATE INDEX IF NOT EXISTS idx_sm_sector ON stock_master(sector);
CREATE INDEX IF NOT EXISTS idx_sm_active ON stock_master(is_active) WHERE is_active = TRUE;
