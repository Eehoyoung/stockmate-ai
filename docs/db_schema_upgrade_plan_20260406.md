# PostgreSQL 스키마 고도화 계획서 v2 (2026-04-06)
> "신호를 발행하는 시스템"에서 "학습하고 개선되는 트레이딩 시스템"으로

---

## 0. 설계 철학

### 기존 계획의 한계
v1 계획은 "스코어를 DB에 저장하자"는 수준에 머물렀다. 진짜 문제는 다음 세 가지다.

```
문제 1: 운영 맹점 (Operational Blindspot)
  → open_positions 테이블 없음
  → 이중매수 방지, 포지션 사이징, 실시간 리스크 계산 불가

문제 2: 학습 불가 (No Learning Loop)
  → 스코어 컴포넌트별 기여를 저장 안 함
  → "어떤 지표가 실제로 수익에 기여했나?" 분석 불가
  → 임계값 변경 전후 비교 데이터 없음

문제 3: 컨텍스트 소실 (Context Loss)
  → 신호 시점의 시장 전체 상태(KOSPI 수준, 시장 분위기)가 사라짐
  → 기술지표를 매번 API 재호출로 재계산 (성능 낭비)
  → "왜 이날 신호들이 다 실패했나?" 소급 분석 불가
```

### 설계 원칙

| 원칙 | 적용 |
|------|------|
| **불변 감사 추적** | DELETE 없음, 상태 변경은 UPDATE + 이력 INSERT |
| **쓰기 책임 분리** | Java/Python/Scheduler 컬럼 소유권 명시 |
| **조회 성능** | 집계 테이블(stats) 별도 운영, 원장 직접 집계 지양 |
| **JSONB 전략** | 전략별로 다른 컨텍스트는 JSONB로 — 공통 필드는 컬럼화 |
| **파티셔닝 준비** | 대용량 테이블(tick, signals) → 월별 RANGE 파티션 |
| **timezone** | 모든 timestamp는 TIMESTAMPTZ (KST ↔ UTC 변환 명시) |

---

## 1. 현황 분석

### 1.1 기존 테이블 현황

| 테이블 | 역할 | 문제점 |
|--------|------|--------|
| `trading_signals` | 신호 원장 | score 필드 1개, Python 결과 미저장 |
| `vi_events` | VI 이력 | 신호와 연결 없음 |
| `ws_tick_data` | WS 체결 | 무한 증가, 파티션 없음, 90일 후 무용 |
| `kiwoom_token` | 인증 | 현재 수준 유지 |
| `economic_events` | 캘린더 | 신호 영향 분석 미연결 |
| `news_analysis` | 뉴스 감성 | 신호 시점 감성 저장 안 됨 |

### 1.2 데이터 소실 경로 (현재)

```
Java SignalService
  → trading_signals INSERT (스코어 없음)
  → telegram_queue LPUSH {id, stk_cd, entry_price, ...}
                                  ↓
Python queue_worker
  → rule_score 계산
  → TP/SL 계산 (tp_method, sl_method)
  → RSI, MA, BB 기술지표 수집
  → action=ENTER/CANCEL 결정
  → ai_scored_queue LPUSH          ◄─── [여기서 모든 분석 결과 소멸]
                                  ↓
Node.js telegram-bot
  → 텔레그램 메시지 발송
  → 끝 (기록 없음)

overnight_worker
  → 8개 컴포넌트 스코어 계산
  → HOLD/FORCE_CLOSE 결정
  → ai_scored_queue LPUSH          ◄─── [여기서도 모든 판단 근거 소멸]
```

---

## 2. 전체 테이블 설계 (16개)

### 2.A 기존 테이블 확장 (2개)

---

#### 2.A-1. `trading_signals` — 스코어링 + 컨텍스트 컬럼 추가

**추가 컬럼:**

```sql
-- ── Python ai-engine이 스코어링 완료 후 UPDATE ─────────────────
ALTER TABLE trading_signals
  ADD COLUMN rule_score        NUMERIC(5,2),   -- 1차 규칙 스코어
  ADD COLUMN ai_score          NUMERIC(5,2),   -- 최종 ai_score (현재는 rule_score와 동일)
  ADD COLUMN rr_ratio          NUMERIC(5,2),   -- Risk:Reward 비율 (슬리피지 반영)
  ADD COLUMN action            VARCHAR(20),    -- ENTER / CANCEL / HOLD
  ADD COLUMN confidence        VARCHAR(10),    -- HIGH / MEDIUM / LOW
  ADD COLUMN ai_reason         TEXT,           -- 판단 사유
  ADD COLUMN tp_method         VARCHAR(60),    -- swing_resistance / fib_1272 / MA20_x099 등
  ADD COLUMN sl_method         VARCHAR(60),    -- swing_low_x099 / MA20_x099 / ATR_x20 등
  ADD COLUMN skip_entry        BOOLEAN DEFAULT FALSE,  -- R:R < 1.0 경보
  ADD COLUMN scored_at         TIMESTAMPTZ,    -- 스코어링 완료 시각

-- ── 신호 시점 기술지표 스냅샷 (Python이 수집, UPDATE) ────────────
  ADD COLUMN ma5_at_signal     NUMERIC(10,0),
  ADD COLUMN ma20_at_signal    NUMERIC(10,0),
  ADD COLUMN ma60_at_signal    NUMERIC(10,0),
  ADD COLUMN rsi14_at_signal   NUMERIC(5,2),
  ADD COLUMN bb_upper_at_sig   NUMERIC(10,0),
  ADD COLUMN bb_lower_at_sig   NUMERIC(10,0),
  ADD COLUMN atr_at_signal     NUMERIC(10,2),  -- ATR(14) 절대값

-- ── 신호 시점 시장 컨텍스트 (Python이 Redis에서 수집) ───────────
  ADD COLUMN market_flu_rt     NUMERIC(6,3),   -- 당일 KOSPI/KOSDAQ 지수 등락률
  ADD COLUMN news_sentiment    VARCHAR(20),    -- 신호 시점 뉴스 감성 (BULLISH/NEUTRAL/BEARISH)
  ADD COLUMN news_ctrl         VARCHAR(20),    -- 신호 시점 매매 제어 상태

-- ── 청산 시 Java ForceCloseScheduler가 UPDATE ──────────────────
  ADD COLUMN exit_type         VARCHAR(20),    -- TP1_HIT/TP2_HIT/SL_HIT/FORCE_CLOSE/EXPIRED
  ADD COLUMN exit_price        NUMERIC(10,0),
  ADD COLUMN exit_pnl_pct      NUMERIC(7,4),   -- 슬리피지 반영 실현 수익률
  ADD COLUMN exit_pnl_abs      NUMERIC(14,0),  -- 손익 원화
  ADD COLUMN hold_duration_min INTEGER,
  ADD COLUMN exited_at         TIMESTAMPTZ;

-- ── 복합 인덱스 추가 ───────────────────────────────────────────
CREATE INDEX idx_ts_action_created  ON trading_signals(action, created_at);
CREATE INDEX idx_ts_exit_type       ON trading_signals(exit_type) WHERE exit_type IS NOT NULL;
CREATE INDEX idx_ts_stk_action      ON trading_signals(stk_cd, action, created_at);
```

**컬럼 소유권 테이블:**

| 컬럼 그룹 | 작성자 | 시점 | NULL 허용 |
|----------|--------|------|-----------|
| stk_cd, strategy, entry_price, tp1/tp2/sl_price, signal_score | Java SignalService | 신호 생성 | 일부 |
| rule_score, ai_score, rr_ratio, action, confidence, ai_reason, tp/sl_method, *_at_signal, news_*, scored_at | **Python queue_worker** | 스코어링 완료 후 | YES |
| signal_status, closed_at, realized_pnl | Java ForceCloseScheduler | 청산 처리 | YES |
| exit_type, exit_price, exit_pnl_*, hold_duration_min, exited_at | **Java ForceCloseScheduler** | 청산 시 | YES |

---

#### 2.A-2. `ws_tick_data` — 파티셔닝 준비

```sql
-- 현재: 무제한 증가 테이블 (WS 체결 건당 1행 → 하루 수십만건)
-- 목표: 월별 RANGE 파티션으로 자동 분리 + 90일 후 파티션 DROP

-- 단기 조치: 90일 이전 데이터 정기 삭제 (DataCleanupScheduler)
-- 장기 조치: ws_tick_data를 파티션 테이블로 전환

-- DataCleanupScheduler에 추가할 쿼리:
DELETE FROM ws_tick_data WHERE created_at < NOW() - INTERVAL '90 days';
```

---

### 2.B 신규 테이블 — 트레이딩 운영 (4개)

---

#### 2.B-1. `signal_score_components` — 스코어 컴포넌트 상세 ⭐

> **Why 가장 중요한가:** "rule_score=72점"만 알아서는 전략 개선 불가.
> "거래량 +15, RSI +8, MA 배열 -5, 시간대 +5"까지 알아야 어느 지표가 실제 수익 예측에 기여하는지 분석 가능.

```sql
CREATE TABLE signal_score_components (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    strategy        VARCHAR(30) NOT NULL,

    -- ── 공통 컴포넌트 ───────────────────────────────────────────
    base_score          NUMERIC(5,2),   -- 기본 베이스 점수
    time_bonus          NUMERIC(5,2),   -- 시간대 보너스 (9:00~9:30 등)
    vol_score           NUMERIC(5,2),   -- 거래량 관련 (거래량비율, OBV 등)
    momentum_score      NUMERIC(5,2),   -- 모멘텀 (등락률, 체결강도)
    technical_score     NUMERIC(5,2),   -- MA 배열, RSI, 볼린저
    demand_score        NUMERIC(5,2),   -- 수급 (호가비율, 기관·외인 순매수)
    risk_penalty        NUMERIC(5,2),   -- 리스크 패널티 (과매수, 뉴스 PAUSE 등)

    -- ── 전략별 특화 컴포넌트 (JSONB) ───────────────────────────
    strategy_components JSONB,
    -- S1: {"gap_pct": 2.1, "gap_score": 10}
    -- S8: {"golden_cross_today": true, "gc_score": 15, "gap_from_ma20_pct": 3.2}
    -- S10: {"new_high_pct": 1.2, "fib_tp": 85200, "box_days": 45}
    -- S14: {"rsi_score": 12, "stoch_score": 8, "cond_count": 4}

    -- ── 집계 ──────────────────────────────────────────────────
    total_score         NUMERIC(5,2),
    threshold_used      NUMERIC(5,2),   -- 이 전략에 적용된 임계값
    passed_threshold    BOOLEAN,

    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_ssc_signal_id ON signal_score_components(signal_id);
CREATE INDEX idx_ssc_strategy        ON signal_score_components(strategy, computed_at);
```

**분석 활용 예시:**
```sql
-- "S8 전략에서 technical_score가 높을수록 실제 TP_HIT 확률이 높은가?"
SELECT
    AVG(ssc.technical_score) AS avg_tech_score,
    ts.exit_type,
    COUNT(*) AS cnt
FROM signal_score_components ssc
JOIN trading_signals ts ON ts.id = ssc.signal_id
WHERE ssc.strategy = 'S8_GOLDEN_CROSS'
  AND ts.exit_type IS NOT NULL
GROUP BY ts.exit_type
ORDER BY avg_tech_score DESC;
```

---

#### 2.B-2. `open_positions` — 실시간 포지션 원장 ⭐⭐

> **Why 절대적으로 필요한가:** 이 테이블 없이는:
> - 같은 종목 이중매수 방지 불가
> - 총 포지션 수 제한 불가
> - 섹터별 익스포저 계산 불가
> - 실시간 포트폴리오 P&L 계산 불가

```sql
CREATE TABLE open_positions (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT NOT NULL REFERENCES trading_signals(id),
    stk_cd          VARCHAR(20) NOT NULL,
    stk_nm          VARCHAR(100),
    strategy        VARCHAR(30) NOT NULL,
    market          VARCHAR(10),        -- 001=KOSPI, 101=KOSDAQ
    sector          VARCHAR(50),        -- 업종 (stock_master에서)

    -- ── 진입 정보 ────────────────────────────────────────────────
    entry_price     NUMERIC(10,0) NOT NULL,
    entry_qty       INTEGER,            -- 수량 (portfolio_config 기반 계산)
    entry_amount    NUMERIC(14,0),      -- 진입 금액 (entry_price × qty)
    entry_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ── TP/SL 기준 ──────────────────────────────────────────────
    tp1_price       NUMERIC(10,0),
    tp2_price       NUMERIC(10,0),
    sl_price        NUMERIC(10,0) NOT NULL,
    tp_method       VARCHAR(60),
    sl_method       VARCHAR(60),
    rr_ratio        NUMERIC(5,2),

    -- ── 상태 ──────────────────────────────────────────────────
    status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    -- ACTIVE / PARTIAL_TP / OVERNIGHT / CLOSING / CLOSED

    -- ── 부분 TP 처리 ─────────────────────────────────────────
    tp1_hit_at      TIMESTAMPTZ,        -- TP1 달성 시각
    tp1_exit_qty    INTEGER,            -- TP1 청산 수량 (전체의 50%)
    remaining_qty   INTEGER,            -- 잔여 수량

    -- ── 오버나잇 ────────────────────────────────────────────────
    is_overnight    BOOLEAN DEFAULT FALSE,
    overnight_verdict VARCHAR(20),      -- HOLD / FORCE_CLOSE (overnight_evaluations 결과)
    overnight_score NUMERIC(5,2),

    -- ── 알림 ──────────────────────────────────────────────────
    sl_alert_sent   BOOLEAN DEFAULT FALSE,  -- SL 80% 접근 알림 발송 여부
    rule_score      NUMERIC(5,2),
    ai_score        NUMERIC(5,2),

    -- ── 청산 완료 ─────────────────────────────────────────────
    closed_at       TIMESTAMPTZ,
    exit_type       VARCHAR(20),        -- TP1_HIT / TP2_HIT / SL_HIT / FORCE_CLOSE / MANUAL
    exit_price      NUMERIC(10,0),
    realized_pnl_pct NUMERIC(7,4),
    realized_pnl_abs NUMERIC(14,0),
    hold_duration_min INTEGER
);

-- 활성 포지션 조회 최적화
CREATE UNIQUE INDEX idx_op_signal_id     ON open_positions(signal_id);
CREATE INDEX idx_op_stk_status          ON open_positions(stk_cd, status);
CREATE INDEX idx_op_status_entry        ON open_positions(status, entry_at) WHERE status = 'ACTIVE';
CREATE INDEX idx_op_strategy_status     ON open_positions(strategy, status);
```

**Java ForceCloseScheduler 연동 패턴:**
```java
// 신호 ENTER 시 open_positions INSERT
// TP1 도달 시 tp1_hit_at, tp1_exit_qty, remaining_qty, status='PARTIAL_TP' UPDATE
// TP2 또는 SL 도달 시 status='CLOSED', closed_at, exit_type, realized_pnl_* UPDATE
// FORCE_CLOSE 시 status='CLOSED', exit_type='FORCE_CLOSE' UPDATE

// 중복 진입 방지 쿼리:
// SELECT COUNT(*) FROM open_positions WHERE stk_cd=? AND status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT')
```

---

#### 2.B-3. `portfolio_config` — 자본·리스크 설정 ⭐

> 단일 행 설정 테이블. Java TradingController REST API로 변경, DB에 영속화.

```sql
CREATE TABLE portfolio_config (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    CHECK (id = 1),     -- 단일 행 보장

    -- ── 자본 설정 ─────────────────────────────────────────────
    total_capital       NUMERIC(16,0) NOT NULL DEFAULT 10000000,  -- 총 운용 자본 (원)
    max_position_pct    NUMERIC(5,2)  NOT NULL DEFAULT 10.0,       -- 종목당 최대 비중 (%)
    max_position_count  INTEGER       NOT NULL DEFAULT 5,          -- 최대 동시 포지션 수
    max_sector_pct      NUMERIC(5,2)  NOT NULL DEFAULT 30.0,       -- 섹터당 최대 비중 (%)

    -- ── 리스크 설정 ───────────────────────────────────────────
    daily_loss_limit_pct NUMERIC(5,2) NOT NULL DEFAULT 3.0,        -- 일일 손실 한도 (%)
    daily_loss_limit_abs NUMERIC(14,0),                            -- 일일 손실 한도 (원)
    max_drawdown_pct    NUMERIC(5,2)  NOT NULL DEFAULT 10.0,       -- 최대 드로다운 한도 (%)
    sl_mandatory        BOOLEAN       NOT NULL DEFAULT TRUE,       -- SL 필수 여부
    min_rr_ratio        NUMERIC(5,2)  NOT NULL DEFAULT 1.0,        -- 최소 R:R 비율

    -- ── 전략 활성화 ──────────────────────────────────────────
    enabled_strategies  JSONB DEFAULT '["S1_GAP_OPEN","S7_AUCTION","S8_GOLDEN_CROSS","S9_PULLBACK_SWING","S10_NEW_HIGH","S11_FRGN_CONT","S12_CLOSING","S13_BOX_BREAKOUT","S14_OVERSOLD_BOUNCE","S15_MOMENTUM_ALIGN"]',

    -- ── 포지션 사이징 방식 ────────────────────────────────────
    sizing_method       VARCHAR(20)   NOT NULL DEFAULT 'FIXED_PCT',
    -- FIXED_PCT: 총자본의 max_position_pct 고정
    -- KELLY: Kelly Criterion 기반 동적 사이징 (향후 구현)
    -- VOLATILITY: ATR 기반 변동성 조정 사이징 (향후 구현)

    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_by          VARCHAR(50)   -- 변경자 (telegram chatId 등)
);

INSERT INTO portfolio_config (id) VALUES (1) ON CONFLICT DO NOTHING;
```

---

#### 2.B-4. `daily_pnl` — 일별 포트폴리오 손익 ⭐

```sql
CREATE TABLE daily_pnl (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,

    -- ── 당일 신호 통계 ───────────────────────────────────────
    total_signals       INTEGER DEFAULT 0,
    enter_count         INTEGER DEFAULT 0,
    cancel_count        INTEGER DEFAULT 0,

    -- ── 당일 청산 결과 ───────────────────────────────────────
    closed_count        INTEGER DEFAULT 0,
    tp_hit_count        INTEGER DEFAULT 0,   -- TP1 + TP2 합산
    sl_hit_count        INTEGER DEFAULT 0,
    force_close_count   INTEGER DEFAULT 0,
    win_rate            NUMERIC(5,2),        -- tp_hit / (tp_hit + sl_hit) × 100

    -- ── 손익 ─────────────────────────────────────────────────
    gross_pnl_abs       NUMERIC(14,0),       -- 총 손익 (수수료 전)
    net_pnl_abs         NUMERIC(14,0),       -- 순 손익 (수수료·세금 후)
    gross_pnl_pct       NUMERIC(7,4),        -- 총자본 대비 수익률
    net_pnl_pct         NUMERIC(7,4),
    avg_pnl_per_trade   NUMERIC(7,4),        -- 거래당 평균 수익률

    -- ── 리스크 지표 ──────────────────────────────────────────
    max_intraday_loss_pct NUMERIC(7,4),      -- 당일 최대 낙폭
    daily_loss_limit_hit  BOOLEAN DEFAULT FALSE,  -- 일일 손실 한도 도달 여부

    -- ── 누적 ────────────────────────────────────────────────
    cumulative_pnl_abs  NUMERIC(16,0),       -- 운용 시작 이후 누적 손익
    cumulative_pnl_pct  NUMERIC(7,4),
    peak_capital        NUMERIC(16,0),       -- 최고 자본 (드로다운 계산용)
    current_drawdown_pct NUMERIC(7,4),       -- 현재 드로다운 (%)

    -- ── 시장 컨텍스트 ─────────────────────────────────────────
    kospi_change_pct    NUMERIC(6,3),        -- 당일 KOSPI 등락률
    kosdaq_change_pct   NUMERIC(6,3),        -- 당일 KOSDAQ 등락률
    market_sentiment    VARCHAR(20),         -- news_analysis에서

    aggregated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_daily_pnl_date ON daily_pnl(date DESC);
```

---

### 2.C 신규 테이블 — 시장 데이터 (3개)

---

#### 2.C-1. `daily_indicators` — 기술지표 영속 캐시 ⭐⭐

> **Why 핵심인가:** 현재 Python 전략들이 매 스캔마다 ka10081 API를 호출해 RSI/MA/BB를 계산.
> 재시작 시 인메모리 캐시 초기화 → 또 API 호출. 하루에 수백 번 동일한 계산 반복.
> DB에 한 번 저장하면: API 호출 95% 감소 + 역사 데이터로 백테스팅 가능.

```sql
CREATE TABLE daily_indicators (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    stk_cd          VARCHAR(20) NOT NULL,

    -- ── 이동평균 ─────────────────────────────────────────────
    close_price     NUMERIC(10,0),      -- 당일 종가
    open_price      NUMERIC(10,0),
    high_price      NUMERIC(10,0),
    low_price       NUMERIC(10,0),
    volume          BIGINT,             -- 거래량
    volume_ratio    NUMERIC(6,2),       -- 거래량비율 (20일 평균 대비)

    ma5             NUMERIC(10,0),
    ma20            NUMERIC(10,0),
    ma60            NUMERIC(10,0),
    ma120           NUMERIC(10,0),
    vol_ma20        BIGINT,             -- 거래량 20일 평균

    -- ── 오실레이터 ───────────────────────────────────────────
    rsi14           NUMERIC(5,2),
    stoch_k         NUMERIC(5,2),       -- Stochastic %K
    stoch_d         NUMERIC(5,2),       -- Stochastic %D

    -- ── 밴드/변동성 ──────────────────────────────────────────
    bb_upper        NUMERIC(10,0),
    bb_mid          NUMERIC(10,0),
    bb_lower        NUMERIC(10,0),
    bb_width_pct    NUMERIC(6,3),       -- (upper-lower)/mid × 100 (변동성 압축 감지)
    pct_b           NUMERIC(6,3),       -- (close-lower)/(upper-lower) × 100

    atr14           NUMERIC(10,2),      -- ATR(14) 절대값
    atr_pct         NUMERIC(6,3),       -- ATR / close × 100 (%)

    -- ── MACD ────────────────────────────────────────────────
    macd_line       NUMERIC(10,2),
    macd_signal     NUMERIC(10,2),
    macd_hist       NUMERIC(10,2),

    -- ── 추세/패턴 플래그 ─────────────────────────────────────
    is_bullish_aligned   BOOLEAN,       -- MA5 > MA20 > MA60
    is_above_ma20        BOOLEAN,
    is_new_high_52w      BOOLEAN,       -- 52주 신고가
    golden_cross_today   BOOLEAN,       -- 오늘 골든크로스 발생

    -- ── 스윙 포인트 (tp_sl_engine용) ─────────────────────────
    swing_high_20d  NUMERIC(10,0),      -- 최근 20일 스윙 고점
    swing_low_20d   NUMERIC(10,0),      -- 최근 20일 스윙 저점
    swing_high_60d  NUMERIC(10,0),
    swing_low_60d   NUMERIC(10,0),

    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (date, stk_cd)
);

CREATE INDEX idx_di_date_stk    ON daily_indicators(date DESC, stk_cd);
CREATE INDEX idx_di_stk_date    ON daily_indicators(stk_cd, date DESC);
CREATE INDEX idx_di_rsi_low     ON daily_indicators(date, rsi14) WHERE rsi14 < 30;  -- 과매도 조회
CREATE INDEX idx_di_aligned     ON daily_indicators(date, is_bullish_aligned) WHERE is_bullish_aligned = TRUE;
```

**Python 전략 수정 패턴 (db_reader.py 추가):**
```python
# 현재: 매번 fetch_daily_candles() → 인디케이터 계산
# 변경 후:
async def get_indicators(pool, stk_cd, date=today):
    row = await pool.fetchrow(
        "SELECT * FROM daily_indicators WHERE stk_cd=$1 AND date=$2",
        stk_cd, date
    )
    if row:
        return dict(row)  # DB 캐시 히트
    # miss → API 호출 → 계산 → INSERT → 반환
    candles = await fetch_daily_candles(token, stk_cd)
    indicators = compute_all_indicators(candles)
    await pool.execute("INSERT INTO daily_indicators ...", indicators)
    return indicators
```

---

#### 2.C-2. `market_daily_context` — 시장 전체 컨텍스트 ⭐

> 특정 날 신호들이 집단적으로 실패했을 때 "왜?"를 분석하는 핵심 데이터.

```sql
CREATE TABLE market_daily_context (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,

    -- ── 지수 ─────────────────────────────────────────────────
    kospi_open      NUMERIC(8,2),
    kospi_close     NUMERIC(8,2),
    kospi_change_pct NUMERIC(6,3),
    kospi_volume    BIGINT,             -- KOSPI 거래대금 (억원)

    kosdaq_open     NUMERIC(8,2),
    kosdaq_close    NUMERIC(8,2),
    kosdaq_change_pct NUMERIC(6,3),
    kosdaq_volume   BIGINT,

    -- ── 시장 분위기 ──────────────────────────────────────────
    advancing_stocks   INTEGER,         -- 상승 종목 수 (KOSPI+KOSDAQ)
    declining_stocks   INTEGER,
    unchanged_stocks   INTEGER,
    advance_decline_ratio NUMERIC(6,3), -- 상승/하락 비율

    -- ── 외국인·기관 수급 ──────────────────────────────────────
    frgn_net_buy_kospi   NUMERIC(14,0), -- 외국인 KOSPI 순매수 (억원)
    inst_net_buy_kospi   NUMERIC(14,0), -- 기관 KOSPI 순매수 (억원)
    frgn_net_buy_kosdaq  NUMERIC(14,0),
    inst_net_buy_kosdaq  NUMERIC(14,0),

    -- ── 시장 전반 상태 ────────────────────────────────────────
    news_sentiment      VARCHAR(20),    -- 장 시작 시 뉴스 감성
    news_trading_ctrl   VARCHAR(20),    -- 장 시작 시 매매 제어 상태
    vix_equivalent      NUMERIC(6,2),   -- 공포지수 유사 지표 (없으면 NULL)
    economic_event_today BOOLEAN DEFAULT FALSE,  -- 당일 고영향 경제지표 발표 여부
    economic_event_nm   VARCHAR(200),   -- 발표 이벤트명 (EconomicEvent JOIN)

    -- ── 당일 성과 요약 (장 종료 후 채움) ──────────────────────
    total_signals_today    INTEGER,
    signal_win_rate_today  NUMERIC(5,2),
    avg_pnl_pct_today      NUMERIC(7,4),

    recorded_at         TIMESTAMPTZ DEFAULT NOW()
);
```

**Java TradingScheduler 장전 적재:**
```java
@Scheduled(cron = "0 30 8 * * MON-FRI")  // 08:30
public void recordMarketContext() {
    // KOSPI/KOSDAQ 지수 조회 (ka10001 또는 별도 API)
    // news_analysis 최근 레코드에서 감성 가져오기
    // economic_events 오늘 HIGH impact 이벤트 확인
    // market_daily_context INSERT
}
```

---

#### 2.C-3. `sector_daily_stats` — 섹터별 일별 성과 ⭐

> S6(테마 후발주), S3(기관·외인), S11(외인 지속)의 성과를 섹터 단위로 분석.

```sql
CREATE TABLE sector_daily_stats (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    sector          VARCHAR(50) NOT NULL,

    -- ── 섹터 수급 ────────────────────────────────────────────
    frgn_net_buy    NUMERIC(14,0),      -- 외국인 섹터 순매수
    inst_net_buy    NUMERIC(14,0),
    avg_change_pct  NUMERIC(6,3),       -- 섹터 평균 등락률
    top_stock_cd    VARCHAR(20),        -- 섹터 1위 종목
    top_stock_pct   NUMERIC(6,3),       -- 1위 종목 등락률

    -- ── 신호 성과 ────────────────────────────────────────────
    signal_count    INTEGER DEFAULT 0,  -- 이 섹터에서 발생한 신호 수
    enter_count     INTEGER DEFAULT 0,
    avg_rule_score  NUMERIC(5,2),
    tp_count        INTEGER DEFAULT 0,
    sl_count        INTEGER DEFAULT 0,
    sector_win_rate NUMERIC(5,2),       -- 섹터 내 승률
    avg_sector_pnl  NUMERIC(7,4),       -- 섹터 내 평균 수익률

    -- ── 뉴스 연계 ────────────────────────────────────────────
    news_recommended BOOLEAN DEFAULT FALSE,  -- news_analysis 추천 섹터 여부

    UNIQUE (date, sector)
);

CREATE INDEX idx_sector_stats_date ON sector_daily_stats(date DESC);
```

---

### 2.D 신규 테이블 — 전략 분석·개선 (3개)

---

#### 2.D-1. `strategy_daily_stats` — 전략별 일별 집계

```sql
CREATE TABLE strategy_daily_stats (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    strategy        VARCHAR(30) NOT NULL,

    -- ── 신호 건수 ────────────────────────────────────────────
    total_signals       INTEGER DEFAULT 0,
    enter_count         INTEGER DEFAULT 0,
    cancel_count        INTEGER DEFAULT 0,
    skip_entry_count    INTEGER DEFAULT 0,   -- R:R 미달로 경보 발생 건수

    -- ── 청산 결과 ─────────────────────────────────────────────
    tp1_hit_count       INTEGER DEFAULT 0,
    tp2_hit_count       INTEGER DEFAULT 0,
    sl_hit_count        INTEGER DEFAULT 0,
    force_close_count   INTEGER DEFAULT 0,
    expired_count       INTEGER DEFAULT 0,
    overnight_count     INTEGER DEFAULT 0,
    win_rate            NUMERIC(5,2),        -- (tp1+tp2)/(tp1+tp2+sl) × 100

    -- ── 스코어 통계 ──────────────────────────────────────────
    avg_rule_score      NUMERIC(5,2),
    avg_ai_score        NUMERIC(5,2),
    avg_rr_ratio        NUMERIC(5,2),
    pct_above_threshold NUMERIC(5,2),        -- 임계값 초과 비율 (%)

    -- ── 성과 통계 ─────────────────────────────────────────────
    avg_pnl_pct         NUMERIC(7,4),        -- 청산된 건 평균 수익률
    total_pnl_abs       NUMERIC(14,0),       -- 총 손익 합산
    avg_hold_min        NUMERIC(7,1),        -- 평균 보유 시간
    best_pnl_pct        NUMERIC(7,4),        -- 당일 최고 수익
    worst_pnl_pct       NUMERIC(7,4),        -- 당일 최저 수익

    -- ── 임계값 (기록 시점 기준) ─────────────────────────────
    threshold_snapshot  NUMERIC(5,2),        -- 집계 당시 임계값 (strategy_param_history와 연계)

    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, strategy)
);

CREATE INDEX idx_sds_date     ON strategy_daily_stats(date DESC);
CREATE INDEX idx_sds_strategy ON strategy_daily_stats(strategy, date DESC);
```

---

#### 2.D-2. `strategy_param_history` — 파라미터 변경 이력 ⭐

> **Why 필요한가:** "S10 임계값을 65→58로 낮췄을 때 성과가 개선됐나?" 라는 질문에 지금은 답할 수 없다.
> 이 테이블이 있으면 변경 전후 기간을 나눠 strategy_daily_stats와 JOIN해서 비교 가능.

```sql
CREATE TABLE strategy_param_history (
    id              BIGSERIAL PRIMARY KEY,
    strategy        VARCHAR(30) NOT NULL,
    param_name      VARCHAR(50) NOT NULL,   -- 'threshold', 'time_bonus_start', 'vol_weight' 등
    old_value       VARCHAR(100),
    new_value       VARCHAR(100) NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by      VARCHAR(50),            -- 'admin', 'auto_tune', telegram chatId
    reason          TEXT                    -- 변경 사유
);

CREATE INDEX idx_sph_strategy ON strategy_param_history(strategy, changed_at DESC);

-- 초기 파라미터 기록 (현재 값 스냅샷)
INSERT INTO strategy_param_history (strategy, param_name, old_value, new_value, reason) VALUES
('S1_GAP_OPEN',        'threshold', NULL, '70', '초기 설정'),
('S2_VI_PULLBACK',     'threshold', NULL, '65', '초기 설정'),
('S8_GOLDEN_CROSS',    'threshold', '65', '60', 'signal 필드 보완 후 재조정'),
('S9_PULLBACK_SWING',  'threshold', '60', '55', 'signal 필드 보완 후 재조정'),
('S10_NEW_HIGH',       'threshold', '65', '58', 'signal 필드 보완 후 재조정'),
...;
```

---

#### 2.D-3. `overnight_evaluations` — 오버나잇 평가 이력

```sql
CREATE TABLE overnight_evaluations (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT REFERENCES trading_signals(id) ON DELETE SET NULL,
    position_id     BIGINT REFERENCES open_positions(id) ON DELETE SET NULL,
    stk_cd          VARCHAR(20) NOT NULL,
    strategy        VARCHAR(30),

    -- ── Java OvernightScoringService 결과 ────────────────────
    java_overnight_score  NUMERIC(5,2),

    -- ── Python overnight_scorer.py 결과 ──────────────────────
    final_score           NUMERIC(5,2),
    verdict               VARCHAR(20),       -- HOLD / FORCE_CLOSE
    confidence            VARCHAR(10),
    reason                TEXT,

    -- ── 평가 시점 지표 스냅샷 ─────────────────────────────────
    pnl_pct               NUMERIC(7,4),      -- 미실현 손익
    flu_rt                NUMERIC(7,4),      -- 당일 등락률
    cntr_strength         NUMERIC(7,2),
    rsi14                 NUMERIC(5,2),
    ma_alignment          VARCHAR(30),
    bid_ratio             NUMERIC(6,3),
    entry_price           NUMERIC(10,0),
    cur_prc_at_eval       NUMERIC(10,0),

    -- ── 컴포넌트별 점수 ───────────────────────────────────────
    score_components      JSONB,
    -- {"base":10,"pnl":15,"strength":5,"bid":5,"flu":3,"strategy":10,"rsi":5,"ma":8}

    -- ── 사후 검증 (다음날 장 시작 후 채움) ────────────────────
    next_day_open         NUMERIC(10,0),     -- 익일 시가 (HOLD 결정이 맞았나?)
    next_day_pnl_pct      NUMERIC(7,4),      -- 익일 오전 최고가 기준 수익률
    verdict_correct       BOOLEAN,           -- HOLD 결정이 실제로 이익이었나?

    evaluated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_oe_signal_id   ON overnight_evaluations(signal_id);
CREATE INDEX idx_oe_position_id ON overnight_evaluations(position_id);
CREATE INDEX idx_oe_stk_cd      ON overnight_evaluations(stk_cd, evaluated_at DESC);
CREATE INDEX idx_oe_verdict     ON overnight_evaluations(verdict, evaluated_at DESC);
```

---

### 2.E 신규 테이블 — 기준 데이터·이력 (3개)

---

#### 2.E-1. `stock_master` — 종목 기준 정보

```sql
CREATE TABLE stock_master (
    stk_cd          VARCHAR(20) PRIMARY KEY,
    stk_nm          VARCHAR(100) NOT NULL,
    market          VARCHAR(10),             -- 001=KOSPI, 101=KOSDAQ
    sector          VARCHAR(50),
    industry        VARCHAR(50),             -- 세부 업종
    listed_at       DATE,
    par_value       INTEGER,                 -- 액면가
    listed_shares   BIGINT,                  -- 상장 주식수
    is_active       BOOLEAN DEFAULT TRUE,
    last_price      NUMERIC(10,0),           -- 최근 종가 (캐싱)
    last_price_date DATE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sm_market  ON stock_master(market);
CREATE INDEX idx_sm_sector  ON stock_master(sector);
CREATE INDEX idx_sm_active  ON stock_master(is_active) WHERE is_active = TRUE;
```

---

#### 2.E-2. `candidate_pool_history` — 후보 풀 일별 이력

```sql
CREATE TABLE candidate_pool_history (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    strategy        VARCHAR(30) NOT NULL,
    market          VARCHAR(10) NOT NULL,
    stk_cd          VARCHAR(20) NOT NULL,
    stk_nm          VARCHAR(100),

    pool_score      NUMERIC(5,2),            -- candidates_builder가 계산한 점수 (있으면)
    appear_count    INTEGER DEFAULT 1,        -- 당일 해당 전략 풀에 등장 횟수
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 신호로 이어졌나?
    led_to_signal   BOOLEAN DEFAULT FALSE,
    signal_id       BIGINT REFERENCES trading_signals(id) ON DELETE SET NULL,

    UNIQUE (date, strategy, market, stk_cd)
);

CREATE INDEX idx_cph_date     ON candidate_pool_history(date DESC);
CREATE INDEX idx_cph_stk_date ON candidate_pool_history(stk_cd, date DESC);
CREATE INDEX idx_cph_strategy ON candidate_pool_history(strategy, date DESC);
```

---

#### 2.E-3. `risk_events` — 리스크 한도 위반 로그

```sql
CREATE TABLE risk_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(30) NOT NULL,
    -- DAILY_LOSS_LIMIT / MAX_POSITION_EXCEEDED / SECTOR_LIMIT / DRAWDOWN_LIMIT
    -- NEWS_PAUSE / DUPLICATE_SIGNAL_BLOCKED / RR_BELOW_MIN

    stk_cd          VARCHAR(20),
    strategy        VARCHAR(30),
    signal_id       BIGINT REFERENCES trading_signals(id) ON DELETE SET NULL,

    threshold_value NUMERIC(10,2),           -- 적용된 한도값
    actual_value    NUMERIC(10,2),            -- 실제 발생값
    description     TEXT,
    action_taken    VARCHAR(100),             -- SIGNAL_CANCELLED / TRADING_PAUSED 등

    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_re_type_date ON risk_events(event_type, occurred_at DESC);
CREATE INDEX idx_re_date      ON risk_events(occurred_at DESC);
```

---

## 3. DB 뷰 설계 (4개)

### 3.1 `v_active_positions` — 활성 포지션 현황

```sql
CREATE OR REPLACE VIEW v_active_positions AS
SELECT
    op.id,
    op.stk_cd,
    sm.stk_nm,
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
    -- 실시간 P&L은 앱 레이어에서 계산 (현재가 - entry_price)
    EXTRACT(EPOCH FROM (NOW() - op.entry_at)) / 60 AS hold_min_so_far,
    ts.ai_reason,
    ts.tp_method,
    ts.sl_method
FROM open_positions op
LEFT JOIN stock_master sm ON sm.stk_cd = op.stk_cd
LEFT JOIN trading_signals ts ON ts.id = op.signal_id
WHERE op.status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT');
```

### 3.2 `v_strategy_performance_30d` — 30일 롤링 전략 성과

```sql
CREATE OR REPLACE VIEW v_strategy_performance_30d AS
SELECT
    strategy,
    COUNT(*) FILTER (WHERE action = 'ENTER') AS enter_count,
    COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT')) AS tp_count,
    COUNT(*) FILTER (WHERE exit_type = 'SL_HIT') AS sl_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT'))
        / NULLIF(COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT','SL_HIT')), 0)
    , 2) AS win_rate_pct,
    ROUND(AVG(rule_score) FILTER (WHERE rule_score IS NOT NULL), 2) AS avg_rule_score,
    ROUND(AVG(rr_ratio) FILTER (WHERE rr_ratio IS NOT NULL), 2) AS avg_rr,
    ROUND(AVG(exit_pnl_pct) FILTER (WHERE exit_pnl_pct IS NOT NULL) * 100, 3) AS avg_pnl_pct,
    ROUND(AVG(hold_duration_min) FILTER (WHERE hold_duration_min IS NOT NULL), 0) AS avg_hold_min
FROM trading_signals
WHERE created_at >= NOW() - INTERVAL '30 days'
  AND action = 'ENTER'
GROUP BY strategy
ORDER BY win_rate_pct DESC NULLS LAST;
```

### 3.3 `v_score_outcome_correlation` — 스코어 컴포넌트 ↔ 결과 상관관계

```sql
CREATE OR REPLACE VIEW v_score_outcome_correlation AS
SELECT
    ssc.strategy,
    ts.exit_type,
    COUNT(*) AS cnt,
    ROUND(AVG(ssc.vol_score), 2)       AS avg_vol_score,
    ROUND(AVG(ssc.momentum_score), 2)  AS avg_momentum_score,
    ROUND(AVG(ssc.technical_score), 2) AS avg_technical_score,
    ROUND(AVG(ssc.demand_score), 2)    AS avg_demand_score,
    ROUND(AVG(ssc.total_score), 2)     AS avg_total_score,
    ROUND(AVG(ts.exit_pnl_pct) * 100, 3) AS avg_pnl_pct
FROM signal_score_components ssc
JOIN trading_signals ts ON ts.id = ssc.signal_id
WHERE ts.exit_type IS NOT NULL
  AND ts.created_at >= NOW() - INTERVAL '90 days'
GROUP BY ssc.strategy, ts.exit_type;
```

### 3.4 `v_portfolio_risk_snapshot` — 현재 포트폴리오 리스크 상태

```sql
CREATE OR REPLACE VIEW v_portfolio_risk_snapshot AS
SELECT
    pc.total_capital,
    pc.max_position_count,
    pc.max_sector_pct,
    pc.daily_loss_limit_pct,

    -- 활성 포지션
    COUNT(op.id) AS active_position_count,
    SUM(op.entry_amount) AS total_allocated,
    ROUND(100.0 * SUM(op.entry_amount) / NULLIF(pc.total_capital, 0), 2) AS allocation_pct,

    -- 오버나잇
    COUNT(op.id) FILTER (WHERE op.is_overnight = TRUE) AS overnight_count,

    -- 당일 손익
    dp.net_pnl_pct AS today_pnl_pct,
    dp.daily_loss_limit_hit,
    dp.current_drawdown_pct

FROM portfolio_config pc
LEFT JOIN open_positions op ON op.status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT')
LEFT JOIN daily_pnl dp ON dp.date = CURRENT_DATE
GROUP BY pc.total_capital, pc.max_position_count, pc.max_sector_pct,
         pc.daily_loss_limit_pct, dp.net_pnl_pct, dp.daily_loss_limit_hit,
         dp.current_drawdown_pct;
```

---

## 4. 서비스별 쓰기 책임 완전 정리

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PostgreSQL (SMA Database)                           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  JAVA api-orchestrator                                              │   │
│  │  trading_signals (INSERT + status/exit UPDATE)                      │   │
│  │  open_positions (INSERT on ENTER, UPDATE on CLOSE)                  │   │
│  │  signal_score_components.threshold_snapshot (via Scheduler)         │   │
│  │  strategy_daily_stats (15:35 집계)                                  │   │
│  │  sector_daily_stats (15:40 집계)                                    │   │
│  │  daily_pnl (15:45 집계)                                             │   │
│  │  market_daily_context (08:30 적재)                                  │   │
│  │  stock_master (장전 UPSERT)                                         │   │
│  │  risk_events (실시간 INSERT)                                        │   │
│  │  strategy_param_history (파라미터 변경 시)                           │   │
│  │  overnight_evaluations.next_day_* (익일 09:30 채움)                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  PYTHON ai-engine                                                   │   │
│  │  trading_signals (score 컬럼 UPDATE — 14개 컬럼만)                  │   │
│  │  signal_score_components (INSERT — 컴포넌트 상세)                   │   │
│  │  overnight_evaluations (INSERT)                                     │   │
│  │  daily_indicators (UPSERT — 전략 스캔 후)                          │   │
│  │  candidate_pool_history (UPSERT)                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  READ-ONLY                                                          │   │
│  │  Node.js telegram-bot: 모든 테이블 REST API 통해 읽기               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Python ai-engine DB 연동 설계

### 5.1 `ai-engine/db_writer.py` — asyncpg 기반

```python
"""
db_writer.py
ai-engine → PostgreSQL 직접 쓰기 (asyncpg 커넥션 풀).

커넥션 풀은 engine.py main()에서 초기화하고 rdb(Redis)처럼 주입.
"""

import asyncpg
import os

_pool: asyncpg.Pool | None = None

async def init_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL"),  # postgresql://user:pw@host:5432/SMA
        min_size=2, max_size=5,
        command_timeout=10,
        server_settings={"application_name": "stockmate-ai-engine"}
    )
    return _pool

async def close_pool():
    if _pool:
        await _pool.close()

# ─────────────────────────────────────────────────────────
# queue_worker.py에서 스코어링 완료 후 호출
async def update_signal_score(signal_id: int, score_data: dict):
    await _pool.execute("""
        UPDATE trading_signals SET
          rule_score=$2, ai_score=$3, rr_ratio=$4,
          action=$5, confidence=$6, ai_reason=$7,
          tp_method=$8, sl_method=$9, skip_entry=$10,
          ma5_at_signal=$11, ma20_at_signal=$12, ma60_at_signal=$13,
          rsi14_at_signal=$14, bb_upper_at_sig=$15, bb_lower_at_sig=$16,
          atr_at_signal=$17, market_flu_rt=$18,
          news_sentiment=$19, news_ctrl=$20,
          scored_at=NOW()
        WHERE id=$1
    """, signal_id, score_data['rule_score'], ...)

# ─────────────────────────────────────────────────────────
# signal_score_components INSERT
async def insert_score_components(signal_id: int, strategy: str, components: dict):
    await _pool.execute("""
        INSERT INTO signal_score_components
          (signal_id, strategy, base_score, time_bonus, vol_score,
           momentum_score, technical_score, demand_score, risk_penalty,
           strategy_components, total_score, threshold_used, passed_threshold)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13)
        ON CONFLICT DO NOTHING
    """, signal_id, strategy, ...)

# ─────────────────────────────────────────────────────────
# overnight_evaluations INSERT
async def insert_overnight_eval(signal_id: int, position_id: int, verdict: dict):
    await _pool.execute("""
        INSERT INTO overnight_evaluations
          (signal_id, position_id, stk_cd, strategy,
           java_overnight_score, final_score, verdict, confidence, reason,
           pnl_pct, flu_rt, cntr_strength, rsi14, ma_alignment, bid_ratio,
           entry_price, cur_prc_at_eval, score_components)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb)
    """, signal_id, position_id, ...)

# ─────────────────────────────────────────────────────────
# daily_indicators UPSERT
async def upsert_daily_indicators(date: str, stk_cd: str, indicators: dict):
    await _pool.execute("""
        INSERT INTO daily_indicators (date, stk_cd, ...)
        VALUES ($1,$2,...)
        ON CONFLICT (date, stk_cd) DO UPDATE SET ...
    """, date, stk_cd, ...)

# ─────────────────────────────────────────────────────────
# candidate_pool_history UPSERT
async def upsert_candidate_pool(date, strategy, market, stk_cd, stk_nm):
    await _pool.execute("""
        INSERT INTO candidate_pool_history
          (date, strategy, market, stk_cd, stk_nm, appear_count, last_seen)
        VALUES ($1,$2,$3,$4,$5,1,NOW())
        ON CONFLICT (date, strategy, market, stk_cd)
        DO UPDATE SET appear_count = candidate_pool_history.appear_count + 1,
                      last_seen = NOW()
    """, date, strategy, market, stk_cd, stk_nm)
```

### 5.2 `ai-engine/db_reader.py` — 기술지표 캐시 조회

```python
"""
db_reader.py
DB → Python 읽기 유틸. 기술지표 캐시 히트 시 API 미호출.
"""

async def get_daily_indicators(pool, stk_cd: str, date: str) -> dict | None:
    """daily_indicators 캐시 조회. 없으면 None 반환."""
    row = await pool.fetchrow(
        "SELECT * FROM daily_indicators WHERE stk_cd=$1 AND date=$2",
        stk_cd, date
    )
    return dict(row) if row else None

async def get_market_context(pool, date: str) -> dict | None:
    """당일 시장 컨텍스트 조회 (뉴스 감성, 지수 등락)."""
    row = await pool.fetchrow(
        "SELECT * FROM market_daily_context WHERE date=$1", date
    )
    return dict(row) if row else None

async def get_active_position(pool, stk_cd: str) -> dict | None:
    """해당 종목 활성 포지션 존재 여부 확인 (이중매수 방지)."""
    row = await pool.fetchrow(
        """SELECT id FROM open_positions
           WHERE stk_cd=$1 AND status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT')
           LIMIT 1""",
        stk_cd
    )
    return dict(row) if row else None

async def get_portfolio_state(pool) -> dict:
    """현재 포트폴리오 상태 (포지션 수, 자본 사용률)."""
    row = await pool.fetchrow("SELECT * FROM v_portfolio_risk_snapshot")
    return dict(row) if row else {}
```

### 5.3 `engine.py` — DB 풀 초기화 추가

```python
# main() 시작 시
from db_writer import init_pool as init_db_pool, close_pool as close_db_pool

db_pool = None
if os.getenv("DATABASE_URL"):
    db_pool = await init_db_pool()
    logger.info("[Engine] PostgreSQL 연결 풀 초기화 완료")

# 종료 시
if db_pool:
    await close_db_pool()
```

---

## 6. Java 변경 사항 (요약)

### 6.1 신규 Entity 목록

| Entity | 테이블 | 우선순위 |
|--------|--------|----------|
| `SignalScoreComponents` | `signal_score_components` | P1 |
| `OpenPosition` | `open_positions` | P1 |
| `PortfolioConfig` | `portfolio_config` | P1 |
| `DailyPnl` | `daily_pnl` | P2 |
| `OvernightEvaluation` | `overnight_evaluations` | P2 |
| `StrategyDailyStat` | `strategy_daily_stats` | P2 |
| `StockMaster` | `stock_master` | P2 |
| `MarketDailyContext` | `market_daily_context` | P2 |
| `CandidatePoolHistory` | `candidate_pool_history` | P3 |
| `SectorDailyStat` | `sector_daily_stats` | P3 |
| `StrategyParamHistory` | `strategy_param_history` | P3 |
| `RiskEvent` | `risk_events` | P3 |

### 6.2 신규 스케줄러 목록

| 스케줄러 | 실행 시각 | 역할 |
|---------|----------|------|
| `MarketContextScheduler` | 08:30 | market_daily_context 적재 |
| `StockMasterScheduler` | 07:00 (주1회 월요일) | stock_master 전종목 갱신 |
| `PerformanceAggregationScheduler` | 15:35 | strategy_daily_stats + sector_daily_stats UPSERT |
| `DailyPnlScheduler` | 15:45 | daily_pnl 집계 |
| `OvernightContextScheduler` | 09:30 (매일) | overnight_evaluations.next_day_* 채움 |

### 6.3 신규 REST 엔드포인트 (요약)

```
# 포지션 관리
GET    /api/positions/active              → v_active_positions
POST   /api/positions                     → open_positions INSERT
PATCH  /api/positions/{id}/close          → open_positions status 업데이트

# 성과 분석
GET    /api/performance/strategy?days=30  → v_strategy_performance_30d
GET    /api/performance/daily?from=&to=   → daily_pnl 목록
GET    /api/performance/score-analysis    → v_score_outcome_correlation

# 포트폴리오
GET    /api/portfolio/risk                → v_portfolio_risk_snapshot
GET    /api/portfolio/config              → portfolio_config
PATCH  /api/portfolio/config              → portfolio_config 업데이트

# 기타
GET    /api/indicators/{stkCd}?date=      → daily_indicators 조회
GET    /api/market-context?date=          → market_daily_context 조회
```

---

## 7. Flyway 마이그레이션 파일 구조

```
api-orchestrator/src/main/resources/db/migration/
  V1__initial_schema.sql              ← 기존 테이블 (Hibernate가 이미 생성)
  V2__add_scoring_columns.sql         ← trading_signals 스코어 컬럼 추가
  V3__create_signal_score_components.sql
  V4__create_open_positions.sql
  V5__create_portfolio_config.sql
  V6__create_daily_pnl.sql
  V7__create_overnight_evaluations.sql
  V8__create_strategy_daily_stats.sql
  V9__create_stock_master.sql
  V10__create_daily_indicators.sql
  V11__create_market_daily_context.sql
  V12__create_sector_daily_stats.sql
  V13__create_candidate_pool_history.sql
  V14__create_strategy_param_history.sql
  V15__create_risk_events.sql
  V16__create_views.sql
  V17__initial_data.sql               ← portfolio_config 초기값, strategy_param 스냅샷
```

> **주의:** 현재 `ddl-auto: update`이므로 Flyway 도입 시
> `ddl-auto: validate`로 변경 후 마이그레이션 파일로 스키마 관리 일원화.

---

## 8. 구현 우선순위 (Phase별)

### Phase 1 — 운영 맹점 해소 (1주일)
> 목표: 스코어가 사라지지 않고, 포지션이 추적된다.

1. `trading_signals` 스코어 컬럼 14개 추가 (V2)
2. `signal_score_components` 테이블 (V3)
3. `open_positions` 테이블 (V4) + Java ForceCloseScheduler 연동
4. `portfolio_config` 테이블 (V5) + 초기값 적재
5. `ai-engine/db_writer.py` — asyncpg 풀 + update_signal_score() + insert_score_components()
6. `queue_worker.py` — 스코어링 후 DB UPDATE 호출
7. `scorer.py` — score_components dict 반환 형태로 리팩터

### Phase 2 — 학습 루프 구축 (2주일)
> 목표: 전략 성과를 수치로 측정하고 비교할 수 있다.

8. `daily_pnl` 테이블 (V6) + 15:45 집계 스케줄러
9. `overnight_evaluations` (V7) + Python overnight_worker 연동
10. `strategy_daily_stats` (V8) + 15:35 집계 스케줄러
11. `stock_master` (V9) + 장전 UPSERT
12. `market_daily_context` (V11) + 08:30 적재
13. `strategy_param_history` (V14) + 초기 스냅샷 INSERT
14. Telegram `/전략분석`, `/성과추적`, `/포트폴리오` 명령어 DB 기반으로 교체

### Phase 3 — 기술지표 영속화 (1주일)
> 목표: 재시작해도 지표 재계산 없음, 백테스팅 데이터 축적 시작.

15. `daily_indicators` 테이블 (V10)
16. `ai-engine/db_reader.py` — 캐시 조회 로직
17. 전략 스캐너 (S8~S15) — DB 캐시 우선 읽기로 교체
18. `candidates_builder.py` — daily_indicators UPSERT 추가

### Phase 4 — 분석 고도화 (2주일)
> 목표: 스코어 컴포넌트 ↔ 수익률 상관관계 분석 가능.

19. `candidate_pool_history` (V13) + Python UPSERT
20. `sector_daily_stats` (V12) + 15:40 집계
21. `risk_events` (V15) + 리스크 한도 초과 시 INSERT
22. DB Views 생성 (V16)
23. Telegram `/분석` 명령어 → v_score_outcome_correlation 쿼리

---

## 9. 핵심 분석 쿼리 레시피

### "어떤 전략이 가장 수익성 좋은가?" (최근 30일)
```sql
SELECT * FROM v_strategy_performance_30d ORDER BY avg_pnl_pct DESC;
```

### "rule_score 대역별 실제 승률"
```sql
SELECT
    CASE
        WHEN rule_score >= 80 THEN '80+'
        WHEN rule_score >= 70 THEN '70-80'
        WHEN rule_score >= 60 THEN '60-70'
        ELSE '<60'
    END AS score_band,
    COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT')) AS wins,
    COUNT(*) FILTER (WHERE exit_type = 'SL_HIT') AS losses,
    ROUND(100.0 * COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT'))
        / NULLIF(COUNT(*) FILTER (WHERE exit_type IN ('TP1_HIT','TP2_HIT','SL_HIT')),0), 1) AS win_pct
FROM trading_signals
WHERE created_at >= NOW() - INTERVAL '90 days' AND action='ENTER'
GROUP BY 1 ORDER BY 1;
```

### "오버나잇 HOLD 결정의 실제 정확도"
```sql
SELECT
    verdict,
    verdict_correct,
    COUNT(*) AS cnt,
    ROUND(AVG(next_day_pnl_pct) * 100, 3) AS avg_next_day_pnl
FROM overnight_evaluations
WHERE next_day_pnl_pct IS NOT NULL
GROUP BY verdict, verdict_correct;
```

### "어떤 날 신호 성과가 가장 나빴고, 시장 컨텍스트는?"
```sql
SELECT
    dp.date, dp.net_pnl_pct, dp.win_rate,
    mc.kospi_change_pct, mc.news_sentiment, mc.economic_event_nm
FROM daily_pnl dp
JOIN market_daily_context mc ON mc.date = dp.date
WHERE dp.date >= NOW() - INTERVAL '90 days'
ORDER BY dp.net_pnl_pct ASC
LIMIT 10;
```

### "임계값 변경 전후 전략 성과 비교"
```sql
WITH param_change AS (
    SELECT changed_at FROM strategy_param_history
    WHERE strategy = 'S10_NEW_HIGH' AND param_name = 'threshold'
    ORDER BY changed_at DESC LIMIT 1
)
SELECT
    CASE WHEN ts.created_at < pc.changed_at THEN 'before' ELSE 'after' END AS period,
    COUNT(*) FILTER (WHERE ts.exit_type IN ('TP1_HIT','TP2_HIT')) AS wins,
    COUNT(*) FILTER (WHERE ts.exit_type = 'SL_HIT') AS losses,
    ROUND(AVG(ts.exit_pnl_pct) * 100, 3) AS avg_pnl
FROM trading_signals ts, param_change pc
WHERE ts.strategy = 'S10_NEW_HIGH' AND ts.action = 'ENTER'
GROUP BY period;
```
