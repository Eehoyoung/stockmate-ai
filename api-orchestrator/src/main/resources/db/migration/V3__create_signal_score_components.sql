-- V3: signal_score_components — 스코어 컴포넌트 상세 기록
-- 전략별 어떤 지표가 실제 수익에 기여했는지 분석하기 위한 핵심 테이블
-- 쓰기 주체: Python queue_worker (scorer.py rule_score 계산 직후)

CREATE TABLE IF NOT EXISTS signal_score_components (
    id                  BIGSERIAL PRIMARY KEY,
    signal_id           BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    strategy            VARCHAR(30) NOT NULL,

    -- ── 공통 컴포넌트 ──────────────────────────────────────────────────────
    base_score          NUMERIC(5,2),       -- 기본 베이스 점수
    time_bonus          NUMERIC(5,2),       -- 시간대 보너스 (09:00~09:30 등)
    vol_score           NUMERIC(5,2),       -- 거래량 관련 (거래량비율, OBV 등)
    momentum_score      NUMERIC(5,2),       -- 모멘텀 (등락률, 체결강도)
    technical_score     NUMERIC(5,2),       -- MA 배열, RSI, 볼린저
    demand_score        NUMERIC(5,2),       -- 수급 (호가비율, 기관·외인 순매수)
    risk_penalty        NUMERIC(5,2),       -- 리스크 패널티 (과매수, 뉴스 PAUSE 등)

    -- ── 전략별 특화 컴포넌트 (JSONB) ───────────────────────────────────────
    -- S1:  {"gap_pct": 2.1, "gap_score": 10}
    -- S8:  {"golden_cross_today": true, "gc_score": 15, "gap_from_ma20_pct": 3.2}
    -- S10: {"new_high_pct": 1.2, "fib_tp": 85200, "box_days": 45}
    -- S14: {"rsi_score": 12, "stoch_score": 8, "cond_count": 4}
    strategy_components JSONB,

    -- ── 집계 ────────────────────────────────────────────────────────────
    total_score         NUMERIC(5,2),
    threshold_used      NUMERIC(5,2),       -- 이 전략에 적용된 임계값
    passed_threshold    BOOLEAN,

    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ssc_signal_id ON signal_score_components(signal_id);
CREATE INDEX IF NOT EXISTS idx_ssc_strategy        ON signal_score_components(strategy, computed_at);
