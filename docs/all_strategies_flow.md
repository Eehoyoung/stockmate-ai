# StockMate AI – 전체 전략 플로우 분석 (S1~S15)

> 작성일: 2026-04-01
> 대상 모듈: api-orchestrator (Java), ai-engine (Python), websocket-listener (Python), telegram-bot (Node.js)

---

## 공통 사항

### Kiwoom REST API 공통 HTTP 헤더 (Java)

모든 Kiwoom REST API 호출(Java `KiwoomApiService.post()`)에 동일하게 적용된다.

```
POST https://api.kiwoom.com/{endpoint}
Headers:
  api-id:        {apiId}                      ← 전략별 TR 코드 (예: ka10080)
  Authorization: Bearer {accessToken}          ← Redis kiwoom:token 에서 로드
  Content-Type:  application/json;charset=UTF-8
  (페이지네이션 시 추가)
  cont-yn:       Y
  next-key:      {nextKey}
```

**Rate Limiter**: `KiwoomRateLimiter` – 초당 3회 제한, 초과 시 자동 대기
**재시도**: 최대 3회 지수 백오프 (`Retry.backoff(3, Duration.ofSeconds(1))`)
**에러 감지**: HTTP 200이라도 `return_code != "0"` 또는 `"error"` 키 존재 시 실패 처리

### Kiwoom REST API 공통 HTTP 헤더 (Python httpx)

Python 전략 파일에서 직접 호출하는 경우:

```
POST {KIWOOM_BASE_URL}/{endpoint}
Headers:
  api-id:        {apiId}
  Authorization: Bearer {token}               ← Redis kiwoom:token 에서 로드
  Content-Type:  application/json;charset=UTF-8
```

---

## 공통 신호 처리 플로우 (Java → AI Engine → Telegram)

```
StrategyService → SignalService.processSignal()
  1. 중복 체크: Redis signal:{stk_cd}:{strategy} TTL 기반
  2. 종목 쿨다운: Redis cooldown:{stk_cd} (stockCooldownMinutes)
  3. 일일 상한: Redis daily:signal:count:{YYYYMMDD}
  4. DB 저장: PostgreSQL TradingSignal
  5. 전략 태그: Redis candidates:tag:{stk_cd} (TTL 24h)
  6. 섹터 과열 추적
  7. LPUSH telegram_queue {JSON payload}
      ↓
queue_worker.py (RPOP, 2초 폴링)
  → 뉴스 제어 확인 (Redis news:trading_control)
  → WS 온라인 확인 (Redis ws:py_heartbeat)
  → 실시간 시세: ws:tick, ws:hoga, ws:strength, vi:{stk_cd}
  → scorer.rule_score() → 1차 점수
  → 전략별 임계값 미달 → CANCEL → ai_scored_queue
  → 임계값 이상 → human_confirm_queue → confirm_worker.py
      ↓
confirm_worker.py
  → analyzer.analyze_signal() → Claude API
  → LPUSH ai_scored_queue {JSON}
      ↓
telegram-bot signals.js (RPOP ai_scored_queue, 2초 폴링)
  → action=ENTER + ai_score >= MIN_AI_SCORE → 텔레그램 발송
```

---

## S1 – 갭상승 시초가 매수 (GAP_OPEN)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S1_GAP_OPEN` |
| 타이밍 | 장전 08:30 ~ 개장 직후 09:10 |
| 진입방식 | 시초가\_시장가 |
| TP1 / TP2 / SL | +4.0% / +6.0% / -2.0% |
| 스캔 주기 | `@Scheduled(cron="0 0/2 9 * * MON-FRI")` 2분 (09:00~09:10) |
| Claude 임계값 | **70점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS1Candidates)

Redis 캐시 키: `candidates:s1:{market}` (TTL 3분)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10029
Body: {
  "mrkt_tp":       "001" | "101",
  "sort_tp":       "1",       // 상승률순
  "trde_qty_cnd":  "10",      // 만주 이상
  "stk_cnd":       "1",       // 관리종목 제외
  "crd_cnd":       "0",
  "pric_cnd":      "8",       // 1천원 이상
  "stex_tp":       "1"        // 거래소
}
응답 필드: flu_rt, stk_cd, stk_nm
필터: flu_rt 3.0% ~ 15.0%
limit: 100개
```

### Phase 2 – 스캔 (TradingScheduler.scanGapOpening)

스케줄: `09:00 ~ 09:10`, 2분마다
후보: `getS1Candidates("001") + getS1Candidates("101")` → distinct

### Phase 3 – 진입 조건 판정 (StrategyService.scanGapOpening)

**데이터 소스: Redis 전용 (API 추가 호출 없음)**

| 데이터 | Redis 키 | 필터 조건 |
|--------|---------|----------|
| 예상체결가, 전일종가 | `ws:expected:{stk_cd}` | gap_pct = (exp - prev) / prev × 100 → **3.0 ~ 15.0%** |
| 체결강도 | `ws:strength:{stk_cd}` (최근 5개 평균) | 데이터 있을 시 **≥ 130.0** |
| 호가잔량 | `ws:hoga:{stk_cd}` | bid/ask → **≥ 1.3** |

**점수 계산**:
```
score = gap_pct × 0.5 + (strength - 100) × 0.3 + bid_ratio × 0.2
```

**TradingSignalDto 주요 필드**:
```
strategy:   S1_GAP_OPEN
entryPrice: exp_cntr_pric (예상체결가)
gapPct:     갭 비율 (%)
cntrStrength: 체결강도 평균
bidRatio:   호가매수비율
entryType:  "시초가_시장가"
tp1Price:   expPrice × 1.04
tp2Price:   expPrice × 1.06
slPrice:    expPrice × 0.98
```

### Scorer 로직 (scorer.py case "S1_GAP_OPEN")

```python
gap = signal["gap_pct"]
score += 20 if 3<=gap<5 else (15 if 5<=gap<8 else (10 if 8<=gap<15 else (-10 if gap>=15 else 0)))
score += 30 if strength>150 else (20 if strength>130 else (10 if strength>110 else 0))
score += 25 if bid_ratio>2 else (20 if bid_ratio>1.5 else (10 if bid_ratio>1.3 else 0))
cntr_sig = signal.get("cntr_strength", 0)
if cntr_sig > 0:
    score += 10 if cntr_sig>150 else (5 if cntr_sig>130 else 0)
# 시간대 보너스: 09:00~09:30 → +5점
```

### Claude 프롬프트 (analyzer.py)

```
갭상승 매수 신호 평가:
종목: {stk_nm}({stk_cd}), 갭: {gap_pct}%, 호가비율: {bid_ratio},
체결강도: {strength}, 등락: {flu_rt}%, 규칙점수: {rule_score}/100
진입가:{entry}원 | 규칙TP1:+4.0% | 규칙TP2:+6.0% | 규칙SL:-2.0% | 실질R:R={eff_rr}
매수 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요.
```

### Python 스캐너 경로 (strategy_runner.py + strategy_1_gap_opening.py)

활성 시간: `08:30 ~ 09:10`
후보: `rdb.lrange("candidates:s1:001", 0, 99)` + `rdb.lrange("candidates:s1:101", 0, 99)`
데이터: Redis `ws:expected`, `ws:strength`, `ws:hoga` (API 미호출)

---

## S2 – VI 발동 후 눌림목 재진입 (VI_PULLBACK)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S2_VI_PULLBACK` |
| 타이밍 | 09:00 ~ 15:20, 이벤트 기반 (5초 폴링) |
| 진입방식 | 지정가\_눌림목 |
| TP1 / TP2 / SL | +3.0% / +4.5% / -2.0% |
| 스캔 주기 | `@Scheduled(fixedDelay=5000)` 5초 (큐 폴링) |
| Claude 임계값 | **65점** |

### Phase 1 – 이벤트 수신 (websocket-listener → Redis)

```
websocket-listener ws_client.py
  → Kiwoom WebSocket GRP 타입 0D (VI 발동)
  → redis_writer.py LPUSH vi_watch_queue {
      "stk_cd": "005930",
      "vi_price": 75000.0,
      "is_dynamic": true,
      "watch_until": {epoch_ms + 10분},
      "vi_type": "동적VI"
    }
```

### Phase 2 – 큐 처리 (TradingScheduler.processViWatchQueue → ViWatchService)

스케줄: `fixedDelay=5000ms`, 09:00~15:20
`viWatchService.processViWatchQueue()` → 한 번에 최대 20건

### Phase 3 – 눌림목 조건 판정 (StrategyService.checkViPullback)

**데이터 소스: Redis 전용**

| 데이터 | Redis 키 | 필터 조건 |
|--------|---------|----------|
| 현재가 | `ws:tick:{stk_cd}` (cur_prc) | 필수 |
| pullback | (cur_prc - vi_price) / vi_price × 100 | **-3.0% ~ -1.0%** |
| 체결강도 | `ws:strength:{stk_cd}` (최근 3개) | **≥ 110.0** |
| 호가비율 | `ws:hoga:{stk_cd}` | **≥ 1.3** |

**VI 감시 실패 시**: `redisService.pushViWatchBack()` → vi_watch_queue에 재삽입 (감시 시간 내에만)

**TradingSignalDto**:
```
strategy:    S2_VI_PULLBACK
entryPrice:  cur_prc
pullbackPct: (cur - vi_price) / vi_price × 100
entryType:   "지정가_눌림목"
tp1Price:    cur_prc × 1.03
tp2Price:    cur_prc × 1.045
slPrice:     cur_prc × 0.98
```

### Scorer 로직 (scorer.py case "S2_VI_PULLBACK")

```python
pullback = abs(signal["pullback_pct"])
score += 30 if 1.0<=pullback<2.0 else (20 if pullback<3.0 else 0)
is_dynamic = bool(signal.get("is_dynamic", False))
score += 15 if is_dynamic else 0
score += 20 if strength>120 else (10 if strength>110 else 0)
score += 20 if bid_ratio>1.5 else (10 if bid_ratio>1.3 else 0)
```

---

## S3 – 외인 + 기관 동시 순매수 (INST_FRGN)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S3_INST_FRGN` |
| 타이밍 | 09:30 ~ 14:30 |
| 진입방식 | 지정가\_1호가 |
| TP1 / TP2 / SL | +3.5%(→+6.0%) / +5.0%(→+10.0%) / -2.0%(→-3.0%) |
| 스캔 주기 | `@Scheduled(cron="0 0/5 9-14 * * MON-FRI")` 5분 |
| Claude 임계값 | **60점** |

### Phase 1 – API 호출 (StrategyService.scanInstFrgn)

**① 장중 투자자별 매매 (동시순매수)**

```
POST https://api.kiwoom.com/api/dostk/mrkcond
api-id: ka10063
Body: {
  "mrkt_tp": "001" | "101"
}
응답 필드: stk_cd, stk_nm, net_buy_amt (외인+기관 합산 순매수금액)
```

**② 기관+외국인 연속 순매수**

```
POST https://api.kiwoom.com/api/dostk/frgnistt
api-id: ka10131
Body: {
  "mrkt_tp": "001" | "101"
}
응답 필드: stk_cd, cont_dt_cnt (연속일수)
```

**교집합 로직**: ka10063 결과 ∩ ka10131 결과 (stk_cd 기준)

**③ 거래량 비율 (Redis)**

```
ws:tick:{stk_cd}.vol_ratio → ≥ 1.5 조건
```

**TradingSignalDto**:
```
strategy:       S3_INST_FRGN
netBuyAmt:      외인+기관 합산 순매수금액 (원)
continuousDays: ka10131 cont_dt_cnt
volRatio:       ws:tick vol_ratio
entryType:      "지정가_1호가"
tp1Price:       cur_prc × 1.06
tp2Price:       cur_prc × 1.10
slPrice:        cur_prc × 0.97
```

### Scorer 로직 (scorer.py case "S3_INST_FRGN")

```python
net_amt   = signal["net_buy_amt"]
cont_days = int(signal.get("continuous_days", 0))
vol_ratio = signal["vol_ratio"]
score += min(25, net_amt / 1_000_000 * 0.5)                                    # 최대 25점
score += 30 if cont_days>=5 else (20 if cont_days>=3 else (10 if cont_days>=1 else 0))
score += 25 if vol_ratio>=3 else (20 if vol_ratio>=2 else (10 if vol_ratio>=1.5 else 0))
```

### Python 스캐너 경로 (strategy_3_inst_foreign.py)

활성 시간: `09:30 ~ 14:30`
ka10063 + ka10131 직접 호출 후 교집합 (후보 풀 없음)

---

## S4 – 장대양봉 + 거래량 급증 추격매수 (BIG_CANDLE)

> 상세 플로우는 `docs/s4_strategy_flow.md` 참고

### 개요 요약

| 항목 | 값 |
|------|---|
| 전략코드 | `S4_BIG_CANDLE` |
| 타이밍 | 09:30 ~ 14:30 |
| 진입방식 | 추격\_시장가 |
| TP1 / TP2 / SL | +4.0% / +6.0% / -2.5% (저가 하방) |
| 스캔 주기 | `@Scheduled(cron="0 0/3 9-14 * * MON-FRI")` 3분 |
| Claude 임계값 | **75점** (전략 중 최고) |

### API 호출 목록

| API | URL | 용도 |
|-----|-----|-----|
| ka10032 | `POST /api/dostk/rkinfo` | S12 후보 풀 (거래대금 상위, flu_rt>0) |
| ka10023 | `POST /api/dostk/rkinfo` | 사전 필터 – 거래량 급증 (sdnin_rt≥50%) |
| ka10019 | `POST /api/dostk/stkinfo` | 사전 필터 – 가격 급등 (jmp_rt≥3.0%) |
| ka10080 | `POST /api/dostk/chart` | 5분봉 차트 (장대양봉 판정) |

**핵심 조건**: body_ratio≥0.70, gain_pct≥3.0%, vol_ratio≥5.0배, strength≥120

---

## S5 – 프로그램 순매수 + 외인 동반 (PROG_FRGN)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S5_PROG_FRGN` |
| 타이밍 | 10:00 ~ 14:00 |
| 진입방식 | 지정가\_1호가 |
| TP1 / TP2 / SL | +3.0%(→+5%) / +4.5%(→+8%) / -2.0%(→-3%) |
| 스캔 주기 | `@Scheduled(cron="0 0/10 10-13 * * MON-FRI")` 10분 |
| Claude 임계값 | **65점** |

### Phase 1 – API 호출 (StrategyService.scanProgramFrgn)

**① 프로그램 순매수 상위**

```
POST https://api.kiwoom.com/api/dostk/stkinfo
api-id: ka90003
Body: {
  "mrkt_tp": "001" | "101"
}
응답 필드: stk_cd, stk_nm, net_buy_amt (프로그램 순매수금액)
```

**② 외국인+기관 상위 (동반 조건)**

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka90009
Body: {
  "mrkt_tp": "001" | "101"
}
응답 필드: stk_cd (외국인+기관 상위 종목)
```

**교집합 로직**: ka90003 결과 ∩ ka90009 결과 (stk_cd 기준)

**TradingSignalDto**:
```
strategy:   S5_PROG_FRGN
netBuyAmt:  프로그램 순매수금액 (원)
entryType:  "지정가_1호가"
tp1Price:   cur_prc × 1.05
tp2Price:   cur_prc × 1.08
slPrice:    cur_prc × 0.97
```

### Scorer 로직 (scorer.py case "S5_PROG_FRGN")

```python
net_amt = signal["net_buy_amt"]
score += min(40, net_amt / 1_000_000 * 0.4)                            # 최대 40점
score += 25 if strength>130 else (20 if strength>120 else (10 if strength>100 else 0))
score += 20 if bid_ratio>2 else (15 if bid_ratio>1.5 else (8 if bid_ratio>1.2 else 0))
```

### Python 스캐너 경로 (strategy_5_program_buy.py)

활성 시간: `10:00 ~ 14:00`
ka90003 + ka90009 직접 호출 후 교집합

---

## S6 – 테마 상위 후발주 (THEME_LAGGARD)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S6_THEME_LAGGARD` |
| 타이밍 | 09:30 ~ 13:00 |
| 진입방식 | 지정가\_1호가 |
| TP1 / TP2 / SL | 테마 상승률 × 50% / × 70% / -2.0% |
| 스캔 주기 | `@Scheduled(cron="0 0/10 9-12 * * MON-FRI")` 10분 |
| Claude 임계값 | **60점** |

### Phase 1 – 테마 그룹 조회

```
POST https://api.kiwoom.com/api/dostk/thme
api-id: ka90001
Body: {}
응답 필드: thema_grp_cd, thema_nm, flu_rt (테마 등락률)
처리: 상위 5개 테마만 처리 (flu_rt ≥ 2.0%)
```

### Phase 2 – 테마별 구성 종목 조회

테마당 1회 호출:

```
POST https://api.kiwoom.com/api/dostk/thme
api-id: ka90002
Body: {
  "thema_grp_cd": "{themaGrpCd}"
}
응답 필드: stk_cd, stk_nm, flu_rt (개별 종목 등락률)
```

**후발주 조건**:
- 개별 종목 flu_rt: **0.5% ~ P70(상위 30% 하단)** 미만 && < 5.0%
- 체결강도: `ws:strength:{stk_cd}` 데이터 있을 시 ≥ 120.0

**점수 계산**:
```
score = strength × 0.3 + (theme_flu_rt - stk_flu_rt) × 2
target = min(theme_flu_rt × 0.6, 5.0)
tp1Pct = min(theme_flu_rt × 0.5, 6.0)
tp2Pct = min(theme_flu_rt × 0.7, 9.0)
```

**TradingSignalDto**:
```
strategy:   S6_THEME_LAGGARD
themeName:  테마명
gapPct:     개별 종목 등락률 (후발주 정도)
cntrStrength: 체결강도
entryType:  "지정가_1호가"
slPrice:    cur_prc × 0.97
```

### Scorer 로직 (scorer.py case "S6_THEME_LAGGARD")

```python
gap = signal["gap_pct"]    # 후발주 등락률
cntr_sig = signal.get("cntr_strength", 0)
score += 25 if 1<=gap<3 else (15 if 3<=gap<5 else 0)
effective_strength = cntr_sig if cntr_sig>0 else strength
score += 30 if effective_strength>150 else (20 if effective_strength>120 else 0)
score += 20 if bid_ratio>1.5 else (10 if bid_ratio>1.2 else 0)
```

---

## S7 – 장전 동시호가 (AUCTION)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S7_AUCTION` |
| 타이밍 | 08:30 ~ 09:00 (장전 동시호가) |
| 진입방식 | 시초가\_시장가 |
| TP1 / TP2 / SL | gap × 80% / TP1 × 150% / -2.0% |
| 스캔 주기 | `@Scheduled(cron="0 0/2 8 * * MON-FRI")` 2분 |
| Claude 임계값 | **70점** |

### Phase 1 – 3중 사전 필터 (TradingScheduler.scanAuction)

**① S7 후보 풀 (ka10029, 갭 2~10%)**

Redis: `candidates:s7:{market}` (TTL 3분)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10029
Body: {
  "mrkt_tp":      "001" | "101",
  "sort_tp":      "1",
  "trde_qty_cnd": "10",
  "stk_cnd":      "1",
  "crd_cnd":      "0",
  "pric_cnd":     "8",
  "stex_tp":      "1"
}
필터: flu_rt 2.0% ~ 10.0%
```

**② 거래대금 상위 (ka10030, 10억 이상)**

코스피/코스닥 각 1회:

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10030
Body: {
  "mrkt_tp":       "001" | "101",
  "sort_tp":       "1",
  "mang_stk_incls":"1",
  "crd_tp":        "0",
  "trde_qty_tp":   "10",
  "pric_tp":       "8",
  "trde_prica_tp": "0",
  "mrkt_open_tp":  "0",
  "stex_tp":       "1"
}
필터: trde_amt ≥ 1000 (10억)
```

**③ 호가 매수비율 상위 (ka10020, BidUpperService)**

코스피/코스닥 각 1회:

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10020
Body: {
  "mrkt_tp":      "001" | "101",
  "sort_tp":      "3",       // 매수비율순
  "trde_qty_tp":  "0000",
  "stk_cnd":      "1",
  "crd_cnd":      "0",
  "stex_tp":      "1"
}
필터: buy_rt ≥ 200.0%
```

**교집합**: `gapSet ∩ (volSet ∪ bidSet)`

### Phase 2 – 진입 조건 판정 (StrategyService.scanAuction)

**① ka10029 호출 (내부 재조회)**

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10029
Body: { 동일 }
처리: limit 50개, 사전 필터 포함 여부 확인
```

**② Redis 데이터 확인**

| 데이터 | Redis 키 | 조건 |
|--------|---------|-----|
| 예상체결가, 전일종가 | `ws:expected:{stk_cd}` | gap_pct **2.0 ~ 10.0%** |
| 호가잔량 | `ws:hoga:{stk_cd}` | bid_ratio **≥ 2.0** |

**점수 계산**:
```
score = bid_ratio × 10 + gap_pct + (50 - rank) × 0.5
```

**TradingSignalDto**:
```
strategy:  S7_AUCTION
entryPrice: exp_cntr_pric (예상체결가)
gapPct:    갭 비율
bidRatio:  호가 매수비율
volRank:   예상체결 상승률 순위
entryType: "시초가_시장가"
tp1Price:  expPrice × (1 + t1/100)   -- t1 = min(gap×0.8, 5.0)
tp2Price:  expPrice × (1 + t2/100)   -- t2 = min(t1×1.5, 8.0)
slPrice:   expPrice × 0.98
```

### Scorer 로직 (scorer.py case "S7_AUCTION")

```python
gap = signal["gap_pct"]
score += 25 if 2<=gap<5 else (15 if 5<=gap<8 else 0)
score += 30 if bid_ratio>3 else (25 if bid_ratio>2 else (10 if bid_ratio>1.5 else 0))
vol_rank = int(signal.get("vol_rank", 999))
score += 20 if vol_rank<=10 else (15 if vol_rank<=20 else (5 if vol_rank<=30 else 0))
# 시간대 보너스: 09:00~09:30 → +5점
```

---

## S8 – 5일선 골든크로스 스윙 (GOLDEN_CROSS)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S8_GOLDEN_CROSS` |
| 타이밍 | 10:00 ~ 14:30 |
| 진입방식 | 당일종가\_또는\_익일시가 |
| 보유기간 | 5~10 거래일 |
| TP1 / TP2 | 최근 10일 고가 / TP1 × 1.05 |
| SL | MA20 × 0.98 |
| 스캔 주기 | `@Scheduled(cron="0 0/10 10-14 * * MON-FRI")` 10분 |
| Claude 임계값 | **65점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS8Candidates)

Redis: `candidates:s8:{market}` (TTL 20분)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10027
Body: {
  "mrkt_tp":       "001" | "101",
  "sort_tp":       "1",       // 상승률순
  "trde_qty_cnd":  "0010",    // 만주 이상
  "stk_cnd":       "1",
  "crd_cnd":       "0",
  "updown_incls":  "0",
  "pric_cnd":      "8",
  "trde_prica_cnd":"0"
}
필터: flu_rt 0.5% ~ 8.0%
limit: 150개
```

### Phase 2 – 골든크로스 판정 (StrategyService.scanGoldenCross)

일봉 조회:

```
POST https://api.kiwoom.com/api/dostk/chart
api-id: ka10081
Body: {
  "stk_cd":        "{stkCd}",
  "base_dt":       "",         // 당일 기준
  "upd_stkpc_tp":  "1"
}
응답 필드: stk_dd_pole_chart_qry[].{cur_prc, open_pric, high_pric, low_pric, trde_qty}
최소 봉 수: 26개
```

**기술지표 계산 (Java 내장)**:

| 지표 | 파라미터 | 조건 |
|------|---------|-----|
| MA5, MA20 | 5일 / 20일 | MA5 ≥ MA20 (오늘) **AND** MA5 < MA20 (어제) = 골든크로스 |
| 정배열 | — | closes[0] > MA5 |
| 등락률 | — | **0% < flu_rt ≤ 12%** |
| RSI | 14 | **≤ 75** (과열 제외) |
| 거래량비율 | MA20 대비 | **≥ 1.2배** |
| MACD | 12/26/9 | 히스토그램 확장 여부 보너스 |
| 체결강도 | ws:strength | 점수에 반영 |

**기술적 TP/SL**:
```
SL:  MA20 × 0.98
TP1: max(최근 10일 고가, cur_prc × 1.05)
TP2: TP1 × 1.05
```

### Scorer 로직 (scorer.py case "S8_GOLDEN_CROSS")

```python
flu_rt_s8  = signal.get("flu_rt", 0) or flu_rt
vol_ratio  = signal["vol_ratio"]
cntr_sig   = signal.get("cntr_strength", 0)
effective_str = cntr_sig if cntr_sig>0 else strength
rsi = _safe_float(signal.get("rsi", 0))

score += 25 if 1<=flu_rt_s8<=5 else (15 if 5<flu_rt_s8<=10 else 0)
score += 20 if vol_ratio>=3.0 else (12 if vol_ratio>=1.5 else (5 if vol_ratio>=1.0 else 0))
score += 30 if effective_str>130 else (20 if effective_str>110 else (10 if effective_str>100 else 0))
score += 15 if bid_ratio>1.5 else (8 if bid_ratio>1.2 else 0)
if rsi > 0:
    score += 10 if rsi>55 else (5 if rsi>50 else 0)
# 시간대 보너스: 09:00~10:30 → +5점
```

---

## S9 – 정배열 눌림목 지지 반등 스윙 (PULLBACK_SWING)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S9_PULLBACK_SWING` |
| 타이밍 | 09:30 ~ 13:00 |
| 진입방식 | 당일종가\_또는\_익일시가 |
| 보유기간 | 5~8 거래일 |
| SL | MA20 × 0.97 |
| 스캔 주기 | `@Scheduled(cron="0 0/10 9-12 * * MON-FRI")` 10분 |
| Claude 임계값 | **60점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS9Candidates)

Redis: `candidates:s9:{market}` (TTL 20분)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10027
Body: {
  "mrkt_tp":       "001" | "101",
  "sort_tp":       "1",
  "trde_qty_cnd":  "0010",
  "stk_cnd":       "1",
  "crd_cnd":       "0",
  "updown_incls":  "0",
  "pric_cnd":      "8",
  "trde_prica_cnd":"0"
}
필터: flu_rt 0.3% ~ 5.0%
limit: 150개
```

### Phase 2 – 눌림목 판정 (StrategyService.scanPullbackSwing)

일봉 조회 (ka10081, S8과 동일 URL):

```
POST https://api.kiwoom.com/api/dostk/chart
api-id: ka10081
Body: { "stk_cd": "{stkCd}", "upd_stkpc_tp": "1" }
최소 봉 수: 21개
```

**기술지표 계산**:

| 지표 | 조건 |
|------|-----|
| 정배열 | closes[0] > MA5 > MA20 |
| 눌림목 | 최근 3일 중 1일 low ≤ MA5×1.01 AND close ≥ MA5×0.99 |
| 등락률 | **0% < flu_rt ≤ 8%** |
| RSI 14 | **≤ 68** |
| Stochastic Slow 14/3/3 | %K↑ AND 전일 %K ≤ %D AND %K < 25 (골든크로스 하단) |
| 거래량비율 | MA20 대비 |
| 체결강도 | ws:strength |

**기술적 TP/SL**:
```
SL:  MA20 × 0.97
TP1: max(최근 10일 고가, cur_prc × 1.05)
TP2: max(최근 20일 고가, TP1 × 1.03)
```

### Scorer 로직 (scorer.py case "S9_PULLBACK_SWING")

```python
flu_rt_s9 = signal.get("flu_rt", 0) or flu_rt
cntr_sig  = signal.get("cntr_strength", 0)
effective_str = cntr_sig if cntr_sig>0 else strength
rsi = _safe_float(signal.get("rsi", 0))

score += 30 if 0.5<=flu_rt_s9<=3 else (20 if 3<flu_rt_s9<=6 else (10 if 6<flu_rt_s9<=10 else 0))
score += 35 if effective_str>130 else (25 if effective_str>110 else (10 if effective_str>100 else 0))
score += 20 if bid_ratio>1.5 else (10 if bid_ratio>1.2 else 0)
if rsi > 0:
    score += 10 if 40<=rsi<=60 else (5 if 60<rsi<=70 else 0)
```

---

## S10 – 52주 신고가 돌파 스윙 (NEW_HIGH)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S10_NEW_HIGH` |
| 타이밍 | 11:00 ~ 14:00 |
| 진입방식 | 당일종가\_또는\_익일시가 |
| 보유기간 | — |
| TP1 / TP2 | +8.0% / +15.0% |
| SL | 52주 고가 × 0.99 |
| 스캔 주기 | `@Scheduled(cron="0 0/15 11-13 * * MON-FRI")` 15분 |
| Claude 임계값 | **65점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS10Candidates)

Redis: `candidates:s10:{market}` (TTL 20분)

```
POST https://api.kiwoom.com/api/dostk/stkinfo
api-id: ka10016
Body: {
  "mrkt_tp": "001" | "101"
  // ntl_tp 생략 시 기본 신고가
}
응답 필드: stk_cd (당일 신고가 돌파 종목)
limit: 100개
```

**폴백**: ka10016 결과 없으면 → `priceSurgeService(ka10019)` or `getS8Candidates`

### Phase 2 – 신고가 판정 (StrategyService.checkNewHigh)

```
POST https://api.kiwoom.com/api/dostk/chart
api-id: ka10081
Body: { "stk_cd": "{stkCd}", "upd_stkpc_tp": "1" }
최소 봉 수: 20개
```

**기술지표 계산**:

| 조건 | 값 |
|------|---|
| 52주 신고가 | today_high ≥ 전일까지 250봉 max_high × 0.999 |
| 등락률 | **0.5% ~ 15.0%** |
| 거래량비율 | 최근 20일 평균 대비 **≥ 1.5배** |
| MA20 이격 | closes[0] ≤ MA20 × 1.25 (버블 제외) |
| 양봉 | closes[0] > opens[0] |
| 체결강도 | ws:strength 반영 (점수) |

**거래량 급증률 변환**:
```
vol_surge_rt = max(0.0, (vol_ratio - 1.0) × 100)   // 2.0배 → 100%
```

**기술적 TP/SL**:
```
SL:  year_high × 0.99    (52주 고가 직하 – 돌파 후 지지)
TP1: cur_prc × 1.08      (+8%)
TP2: cur_prc × 1.15      (+15%)
```

### Scorer 로직 (scorer.py case "S10_NEW_HIGH")

```python
vol_surge = signal.get("vol_surge_rt", 0)
if vol_surge == 0:
    vol_ratio_java = signal.get("vol_ratio", 0)
    vol_surge = max(0.0, (vol_ratio_java - 1.0) * 100)
score += 30 if vol_surge>=300 else (20 if vol_surge>=200 else (10 if vol_surge>=100 else 0))
score += 20 if 2<=flu_rt<=8 else (10 if 0<flu_rt<=15 else (-10 if flu_rt>15 else 0))
cntr_sig_s10 = signal.get("cntr_strength", 0)
effective_str = cntr_sig_s10 if cntr_sig_s10>0 else strength
score += 30 if effective_str>130 else (20 if effective_str>110 else (10 if effective_str>100 else 0))
```

> **참고**: S10 CANCEL은 오류가 아닌 정상 필터 동작. 52주 신고가 종목은 WS 미구독이라 strength=100(기본값) 경우 많음.

---

## S11 – 외국인 연속 순매수 스윙 (FRGN_CONT)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S11_FRGN_CONT` |
| 타이밍 | 09:30 ~ 14:30 |
| 진입방식 | 지정가\_1호가 |
| 보유기간 | 5~10 거래일 |
| TP1 / TP2 / SL | +8.0% / +12.0%(→14%) / -5.0% |
| 스캔 주기 | `@Scheduled(cron="0 0/15 9-14 * * MON-FRI")` 15분 |
| Claude 임계값 | **60점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS11Candidates)

Redis: `candidates:s11:{market}` (TTL 30분)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10035
Body: {
  "mrkt_tp":    "001" | "101",
  "trde_tp":    "2",    // 연속순매수
  "base_dt_tp": "1"     // D-1 기준
}
응답 필드: stk_cd, dm1, dm2, dm3, tot
필터: dm1>0 AND dm2>0 AND dm3>0 AND tot>0    (3일 연속 외인 순매수)
limit: 80개
```

### Phase 2 – 연속 순매수 판정 (StrategyService.scanFrgnCont)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10035
Body: {
  "mrkt_tp":    "001" | "101",
  "trde_tp":    "2",    // 연속순매수
  "base_dt_tp": "0"     // 당일기준
}
응답 필드: stk_cd, stk_nm, dm1, dm2, dm3, tot, limit_exh_rt (한도소진율)
필터: dm1>0 AND dm2>0 AND dm3>0
```

**점수 계산**:
```
score = 15.0
      + min(tot / 100_000, 20.0)      # 총 순매수 비중 (최대 20점)
      + limit_exh_rt × 0.5            # 한도소진율 (최대 ~25점)
      + vol_ratio × 3.0
      + max(cntr_str - 100, 0) × 0.2
```

**TradingSignalDto**:
```
strategy:       S11_FRGN_CONT
continuousDays: 3 (고정)
volRatio:       ws:tick vol_ratio
cntrStrength:   ws:strength
entryType:      "지정가_1호가"
holdingDays:    "5~10거래일"
tp1Price:       cur_prc × 1.08
tp2Price:       cur_prc × 1.14
slPrice:        cur_prc × 0.95
```

### Scorer 로직 (scorer.py case "S11_FRGN_CONT")

```python
dm1 = signal.get("dm1", 0)
dm2 = signal.get("dm2", 0)
dm3 = signal.get("dm3", 0)
cont_days = sum(1 for d in (dm1, dm2, dm3) if d > 0)
score += 30 if cont_days>=3 else (20 if cont_days>=2 else 0)
score += 20 if flu_rt>0 else (-10 if flu_rt<-3 else 0)
score += 30 if strength>120 else (20 if strength>100 else 0)
```

---

## S12 – 종가 강도 확인 매수 (CLOSING)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S12_CLOSING` |
| 타이밍 | 14:30 ~ 15:10 |
| 진입방식 | 종가\_동시호가 |
| TP1 / TP2 / SL | +5.0% / +7.5% / -3.0% |
| 스캔 주기 | `@Scheduled(cron="0 0/5 14 * * MON-FRI")` 5분 (14:30~15:10) |
| Claude 임계값 | **65점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS12Candidates)

Redis: `candidates:s12:{market}` (TTL 10분) — S4도 이 풀을 공유

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10032
Body: {
  "mrkt_tp":        "001" | "101",
  "mang_stk_incls": "0"            // 관리종목 미포함
}
응답 필드: stk_cd, flu_rt
필터: flu_rt > 0 (당일 양전 종목)
limit: 50개
```

### Phase 2 – 종가 강도 판정 (StrategyService.checkClosingStrength)

**데이터 소스: Redis 전용 (API 추가 호출 없음)**

| 데이터 | Redis 키 | 조건 |
|--------|---------|-----|
| 등락률, 현재가 | `ws:tick:{stk_cd}` (flu_rt, cur_prc) | **4.0% ~ 15.0%** |
| 체결강도 | `ws:strength:{stk_cd}` (최근 5개) | **≥ 110.0** |
| 호가비율 | `ws:hoga:{stk_cd}` | **≥ 1.5** |

**점수 계산**:
```
score = flu_rt × 3 + (strength - 100) × 0.3 + bid_ratio × 5
```

**TradingSignalDto**:
```
strategy:    S12_CLOSING
entryPrice:  cur_prc
gapPct:      flu_rt (당일 등락률)
cntrStrength: 체결강도
bidRatio:    호가비율
entryType:   "종가_동시호가"
tp1Price:    cur_prc × 1.05
tp2Price:    cur_prc × 1.075
slPrice:     cur_prc × 0.97
```

### Scorer 로직 (scorer.py case "S12_CLOSING")

```python
cntr_str_sig = signal.get("cntr_strength", 0)
effective_str = cntr_str_sig if cntr_str_sig>0 else strength
score += 30 if 4<=flu_rt<=10 else (15 if 10<flu_rt<=15 else (-10 if flu_rt>15 else 0))
score += 35 if effective_str>=130 else (25 if effective_str>=110 else (10 if effective_str>=100 else 0))
score += 20 if bid_ratio>1.5 else (10 if bid_ratio>1.2 else 0)
# 시간대 보너스: 14:30~15:30 → +5점
```

---

## S13 – 거래량 폭발 박스권 돌파 스윙 (BOX_BREAKOUT)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S13_BOX_BREAKOUT` |
| 타이밍 | 09:30 ~ 14:00 |
| 진입방식 | 당일종가\_또는\_익일시가 |
| 보유기간 | 3~7 거래일 |
| TP1 / TP2 | 진입가 + 박스높이 / + 박스높이 × 2 |
| SL | 박스 상단 × 0.99 |
| 스캔 주기 | `@Scheduled(cron="0 0/15 9-13 * * MON-FRI")` 15분 |
| Claude 임계값 | **65점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS13Candidates)

**S8 ∪ S10 합산** (별도 API 호출 없음):

```
getS8Candidates(market) ∪ getS10Candidates(market) → distinct → limit(150)
Redis: candidates:s13:{market} (TTL 20분)
```

### Phase 2 – 박스권 돌파 판정 (StrategyService.scanBoxBreakout)

```
POST https://api.kiwoom.com/api/dostk/chart
api-id: ka10081
Body: { "stk_cd": "{stkCd}", "upd_stkpc_tp": "1" }
최소 봉 수: 22개
```

**기술지표 계산**:

| 조건 | 값 |
|------|---|
| 박스 상단 | 최근 5~20일 고가 최대값 |
| 돌파 | closes[0] > box_high × 1.002 |
| 등락률 | **1.0% ~ 15.0%** |
| 거래량비율 | MA20 대비 **≥ 2.0배** |
| 볼린저밴드 너비 | < 6.0% = 스퀴즈 확인 (보너스) |
| MFI 14 | > 55 = 자금 유입 확인 (보너스) |
| 체결강도 | ws:strength |

**박스높이 기반 TP/SL**:
```
box_height = max(box_high - box_low, cur_prc × 0.03)
TP1 = cur_prc + box_height
TP2 = cur_prc + box_height × 2.0
SL  = box_high × 0.99       (돌파 전 저항선 직하)
```

### Scorer 로직 (scorer.py case "S13_BOX_BREAKOUT")

```python
cntr_sig  = signal.get("cntr_strength", 0)
effective_str = cntr_sig if cntr_sig>0 else strength
rsi = _safe_float(signal.get("rsi", 0))

score += 30 if 3<=flu_rt_s13<=8 else (20 if 8<flu_rt_s13<=15 else 0)
score += 35 if effective_str>150 else (25 if effective_str>130 else (10 if effective_str>110 else 0))
score += 25 if bid_ratio>2 else (15 if bid_ratio>1.5 else (5 if bid_ratio>1.2 else 0))
if rsi > 0:
    score += 10 if rsi>60 else (5 if rsi>50 else 0)
# 시간대 보너스: 09:00~10:30 → +5점
```

---

## S14 – 과매도 오실레이터 수렴 반등 스윙 (OVERSOLD_BOUNCE)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S14_OVERSOLD_BOUNCE` |
| 타이밍 | 09:30 ~ 14:00 |
| 진입방식 | 당일종가\_또는\_익일시가 |
| 보유기간 | 3~5 거래일 |
| TP1 / TP2 | ATR × 3.5 / MA20 또는 ATR × 5 |
| SL | ATR × 2 하방 |
| 스캔 주기 | `@Scheduled(cron="0 5/15 9-13 * * MON-FRI")` 15분 (09:35~) |
| Claude 임계값 | **65점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS14Candidates)

Redis: `candidates:s14:{market}` (TTL 20분)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
api-id: ka10027
Body: {
  "mrkt_tp":       "001" | "101",
  "sort_tp":       "3",       // 하락률순
  "trde_qty_cnd":  "0010",
  "stk_cnd":       "1",
  "crd_cnd":       "0",
  "updown_incls":  "0",
  "pric_cnd":      "8",
  "trde_prica_cnd":"0"
}
필터: abs(flu_rt) 3.0% ~ 10.0% (하락 종목)
limit: 100개
```

### Phase 2 – 과매도 반등 판정 (StrategyService.scanOversoldBounce)

```
POST https://api.kiwoom.com/api/dostk/chart
api-id: ka10081
Body: { "stk_cd": "{stkCd}", "upd_stkpc_tp": "1" }
최소 봉 수: 30개
```

**필수 조건 (4개 모두 통과)**:

| 조건 | 값 |
|------|---|
| RSI 14 | **20 ~ 38** (과매도) |
| MA60 생존 | closes[0] ≥ MA60 × 0.88 (추세 붕괴 종목 제외) |
| ATR% | ≤ 4.0% (변동성 과다 종목 제외) |
| 당일 낙폭 | flu_rt ≥ -5.0% (폭락 제외) |

**선택 조건 (2개 이상 충족 필요)**:

| 지표 | 조건 |
|------|-----|
| Stochastic Slow 14/3/3 | %K↑ 골든크로스 AND 전일 %K < 25 |
| Williams %R 14 | 전일 < -80 AND 오늘 > 전일 (−80 상향 돌파) |
| MFI 14 | < 30 AND (증가 OR > 25) (과매도 구간 자금 유입) |

**ATR 기반 TP/SL**:
```
SL  = cur_prc - ATR × 2.0
TP1 = cur_prc + ATR × 3.5
TP2 = max(MA20, cur_prc + ATR × 5.0)
```

**TradingSignalDto**:
```
strategy:   S14_OVERSOLD_BOUNCE
rsi:        RSI 값
atrPct:     ATR% (변동성)
condCount:  충족 선택 조건 수 (2 or 3)
holdingDays:"3~5거래일"
```

### Scorer 로직 (scorer.py case "S14_OVERSOLD_BOUNCE")

```python
cntr_sig = signal.get("cntr_strength", 0)
effective_str = cntr_sig if cntr_sig>0 else strength
atr_pct = _safe_float(signal.get("atr_pct", 0))
rsi = _safe_float(signal.get("rsi", 0))

if rsi > 0:
    score += 40 if rsi<25 else (30 if rsi<30 else (20 if rsi<35 else (10 if rsi<40 else 0)))
else:
    score += 15
score += 20 if atr_pct>3 else (12 if atr_pct>2 else (5 if atr_pct>1 else 0))
score += 25 if effective_str>120 else (15 if effective_str>110 else (5 if effective_str>100 else 0))
score += 15 if bid_ratio>1.5 else (8 if bid_ratio>1.2 else 0)
```

---

## S15 – 다중지표 모멘텀 동조 스윙 (MOMENTUM_ALIGN)

### 개요

| 항목 | 값 |
|------|---|
| 전략코드 | `S15_MOMENTUM_ALIGN` |
| 타이밍 | 10:00 ~ 14:30 |
| 진입방식 | 당일종가\_또는\_익일시가 |
| 보유기간 | 5~10 거래일 |
| TP1 / TP2 | 볼린저 상단 / 볼린저 상단 + ATR × 0.5 |
| SL | ATR × 2 하방 |
| 스캔 주기 | `@Scheduled(cron="0 10/15 10-14 * * MON-FRI")` 15분 (10:10~) |
| Claude 임계값 | **70점** |

### Phase 1 – 후보 풀 구성 (CandidateService.getS15Candidates)

**S8 풀 재활용** (별도 API 호출 없음):

```
getS8Candidates(market) → 별도 캐시 저장
Redis: candidates:s15:{market} (TTL 20분)
```

### Phase 2 – 모멘텀 동조 판정 (StrategyService.scanMomentumAlign)

```
POST https://api.kiwoom.com/api/dostk/chart
api-id: ka10081
Body: { "stk_cd": "{stkCd}", "upd_stkpc_tp": "1" }
최소 봉 수: 35개
```

**필수 조건 (3개 모두)**:

| 조건 | 값 |
|------|---|
| 현재가 | closes[0] ≥ MA20 |
| 등락률 | **0% < flu_rt ≤ 12%** |
| RSI 14 | **≤ 72** |

**선택 조건 (4개 중 3개 이상)**:

| 지표 | 조건 |
|------|-----|
| A. MACD 12/26/9 | 골든크로스 당일 OR 히스토그램 확장 |
| B. RSI | **48 ~ 68** (모멘텀 구간) |
| C. 볼린저 %B | **0.45 ~ 0.82** (중상단 진행) |
| D. 거래량 | MA20 대비 **≥ 1.3배** |

**추가**:
- ATR% **1.0% ~ 3.0%** = 적정 변동성 보너스
- condCount == 4 → +20점 보너스

**볼린저/ATR 기반 TP/SL**:
```
SL  = cur_prc - ATR × 2.0
TP1 = 볼린저 상단 (20일, 2σ)
TP2 = TP1 + ATR × 0.5
```

**TradingSignalDto**:
```
strategy:   S15_MOMENTUM_ALIGN
rsi:        RSI 값
atrPct:     ATR%
condCount:  충족 선택 조건 수 (3 or 4)
volRatio:   거래량 비율
holdingDays:"5~10거래일"
```

### Scorer 로직 (scorer.py case "S15_MOMENTUM_ALIGN")

```python
cntr_sig  = signal.get("cntr_strength", 0)
effective_str = cntr_sig if cntr_sig>0 else strength
vol_ratio = signal.get("vol_ratio", 0)
rsi = _safe_float(signal.get("rsi", 0))
flu_rt_s15 = flu_rt or signal.get("flu_rt", 0)

if rsi > 0:
    score += 35 if 50<=rsi<=65 else (25 if 65<rsi<=75 else (10 if 45<=rsi<50 else 0))
else:
    score += 10
score += 25 if vol_ratio>=3.0 else (18 if vol_ratio>=2.0 else (10 if vol_ratio>=1.5 else 0))
score += 25 if effective_str>130 else (18 if effective_str>110 else (8 if effective_str>100 else 0))
score += 15 if bid_ratio>1.5 else (8 if bid_ratio>1.2 else 0)
score += 5 if 1<=flu_rt_s15<=5 else (3 if 5<flu_rt_s15<=8 else 0)
```

---

## 전략별 종합 비교표

| 전략 | 코드 | 타이밍 | 스캔 주기 | 후보 풀 API | 핵심 판정 API | Claude 임계값 | 진입방식 |
|------|------|--------|----------|-----------|------------|------------|--------|
| S1 갭상승 | S1_GAP_OPEN | 09:00~09:10 | 2분 | ka10029 | Redis만 | **70** | 시초가 시장가 |
| S2 VI눌림 | S2_VI_PULLBACK | 09:00~15:20 | 5초 이벤트 | 없음 (WS) | Redis만 | **65** | 지정가 눌림목 |
| S3 외인기관 | S3_INST_FRGN | 09:30~14:30 | 5분 | 없음 | ka10063+ka10131 | **60** | 지정가 1호가 |
| S4 장대양봉 | S4_BIG_CANDLE | 09:30~14:30 | 3분 | ka10032 | ka10080 5분봉 | **75** | 추격 시장가 |
| S5 프로그램 | S5_PROG_FRGN | 10:00~14:00 | 10분 | 없음 | ka90003+ka90009 | **65** | 지정가 1호가 |
| S6 테마 | S6_THEME_LAGGARD | 09:30~13:00 | 10분 | 없음 | ka90001+ka90002 | **60** | 지정가 1호가 |
| S7 동시호가 | S7_AUCTION | 08:30~09:00 | 2분 | ka10029 | ka10029+Redis | **70** | 시초가 시장가 |
| S8 골든크로스 | S8_GOLDEN_CROSS | 10:00~14:30 | 10분 | ka10027 | ka10081 일봉 | **65** | 익일 시가 |
| S9 눌림목 | S9_PULLBACK_SWING | 09:30~13:00 | 10분 | ka10027 | ka10081 일봉 | **60** | 익일 시가 |
| S10 신고가 | S10_NEW_HIGH | 11:00~14:00 | 15분 | ka10016 | ka10081 일봉 | **65** | 익일 시가 |
| S11 외인연속 | S11_FRGN_CONT | 09:30~14:30 | 15분 | ka10035 | ka10035 | **60** | 지정가 1호가 |
| S12 종가강도 | S12_CLOSING | 14:30~15:10 | 5분 | ka10032 | Redis만 | **65** | 종가 동시호가 |
| S13 박스돌파 | S13_BOX_BREAKOUT | 09:30~14:00 | 15분 | S8∪S10 | ka10081 일봉 | **65** | 익일 시가 |
| S14 과매도 | S14_OVERSOLD_BOUNCE | 09:30~14:00 | 15분 | ka10027 | ka10081 일봉 | **65** | 익일 시가 |
| S15 모멘텀 | S15_MOMENTUM_ALIGN | 10:00~14:30 | 15분 | S8 재활용 | ka10081 일봉 | **70** | 익일 시가 |

---

## 전체 Kiwoom API 호출 목록 (URL + 헤더 + 바디 요약)

### 공통 헤더 (모든 API)
```
api-id:        {아래 표 참고}
Authorization: Bearer {accessToken}
Content-Type:  application/json;charset=UTF-8
```

| API ID | URL | 용도 | 주요 Body 파라미터 |
|--------|-----|-----|-----------------|
| ka10016 | `POST https://api.kiwoom.com/api/dostk/stkinfo` | 신고가 종목 조회 | mrkt_tp |
| ka10019 | `POST https://api.kiwoom.com/api/dostk/stkinfo` | 가격급등락 조회 | mrkt_tp, flu_tp, tm_tp, tm |
| ka10020 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 호가잔량 매수비율 상위 | mrkt_tp, sort_tp="3" |
| ka10023 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 거래량 급증 | mrkt_tp, sort_tp="2", tm="5" |
| ka10027 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 전일대비 등락률 상위 | mrkt_tp, sort_tp=1(상승)/3(하락) |
| ka10029 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 예상체결 등락률 상위 | mrkt_tp, sort_tp="1" |
| ka10030 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 당일 거래량 상위 | mrkt_tp, sort_tp="1" |
| ka10032 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 거래대금 상위 | mrkt_tp, mang_stk_incls="0" |
| ka10035 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 외인 연속 순매매 상위 | mrkt_tp, trde_tp="2", base_dt_tp |
| ka10046 | `POST https://api.kiwoom.com/api/dostk/mrkcond` | 체결강도 추이 (Python) | stk_cd |
| ka10063 | `POST https://api.kiwoom.com/api/dostk/mrkcond` | 장중 투자자별 매매 | mrkt_tp |
| ka10080 | `POST https://api.kiwoom.com/api/dostk/chart` | 주식 5분봉 차트 | stk_cd, tic_scope="5", upd_stkpc_tp="1" |
| ka10081 | `POST https://api.kiwoom.com/api/dostk/chart` | 주식 일봉 차트 | stk_cd, upd_stkpc_tp="1" |
| ka10131 | `POST https://api.kiwoom.com/api/dostk/frgnistt` | 기관+외인 연속 순매수 | mrkt_tp |
| ka90001 | `POST https://api.kiwoom.com/api/dostk/thme` | 테마그룹 상위 | (없음) |
| ka90002 | `POST https://api.kiwoom.com/api/dostk/thme` | 테마 구성 종목 | thema_grp_cd |
| ka90003 | `POST https://api.kiwoom.com/api/dostk/stkinfo` | 프로그램 순매수 상위 | mrkt_tp |
| ka90009 | `POST https://api.kiwoom.com/api/dostk/rkinfo` | 외국인+기관 상위 | mrkt_tp |

---

## Redis 키 전체 목록

| 키 패턴 | 용도 | TTL | 생성 주체 |
|---------|-----|-----|---------|
| `candidates:{market}` | 구형 통합 후보 풀 (점진적 제거 중) | 3분 | Java CandidateService |
| `candidates:s1:{market}` | S1 후보 풀 (ka10029 갭 3~15%) | 3분 | Java |
| `candidates:s7:{market}` | S7 후보 풀 (ka10029 갭 2~10%) | 3분 | Java |
| `candidates:s8:{market}` | S8 후보 풀 (ka10027 0.5~8%) | 20분 | Java |
| `candidates:s9:{market}` | S9 후보 풀 (ka10027 0.3~5%) | 20분 | Java |
| `candidates:s10:{market}` | S10 후보 풀 (ka10016 신고가) | 20분 | Java |
| `candidates:s11:{market}` | S11 후보 풀 (ka10035 외인연속) | 30분 | Java |
| `candidates:s12:{market}` | S12/S4 후보 풀 (ka10032 거래대금) | 10분 | Java |
| `candidates:s13:{market}` | S13 후보 풀 (S8∪S10) | 20분 | Java |
| `candidates:s14:{market}` | S14 후보 풀 (ka10027 하락 3~10%) | 20분 | Java |
| `candidates:s15:{market}` | S15 후보 풀 (S8 재활용) | 20분 | Java |
| `candidates:watchlist` | WS 동적 구독 대상 목록 | 10분 | Java |
| `candidates:tag:{stk_cd}` | 종목별 전략 태그 Set | 24시간 | Java |
| `ws:tick:{stk_cd}` | 실시간 체결 데이터 Hash | 30초 | websocket-listener |
| `ws:expected:{stk_cd}` | 예상체결 데이터 Hash | 60초 | websocket-listener |
| `ws:hoga:{stk_cd}` | 호가잔량 데이터 Hash | 30초 | websocket-listener |
| `ws:strength:{stk_cd}` | 체결강도 List (최신→과거) | 5분 | websocket-listener |
| `vi:{stk_cd}` | VI 상태 Hash | 1시간 | websocket-listener |
| `vi_watch_queue` | VI 감시 큐 (S2용) | — | websocket-listener |
| `kiwoom:token` | Kiwoom 액세스 토큰 | — | Java TokenService |
| `telegram_queue` | 신호 발행 큐 | 12시간 | Java SignalService / Python Runner |
| `ai_scored_queue` | AI 분석 결과 큐 | — | Python confirm_worker |
| `human_confirm_queue` | Claude 호출 대기 큐 | — | Python queue_worker |
| `scanner:dedup:{strategy}:{stk_cd}` | Python 스캐너 중복 방지 | 1시간 | Python strategy_runner |
| `claude:daily_calls:{YYYYMMDD}` | Claude API 일별 호출 횟수 | 24시간 | Python scorer/analyzer |
| `claude:daily_tokens:{YYYYMMDD}` | Claude API 일별 토큰 합계 | 24시간 | Python analyzer |
| `news:trading_control` | 뉴스 기반 매매 제어 (NORMAL/CAUTIOUS/PAUSE) | — | Java NewsControlService |
| `news:market_sentiment` | 시장 심리 (BULLISH/BEARISH/NEUTRAL) | — | Java |
| `news:analysis` | 뉴스 분석 결과 JSON | — | Java |
| `ws:py_heartbeat` | Python WS 온라인 여부 | — | websocket-listener |
| `signal:{stk_cd}:{strategy}` | 중복 신호 방지 TTL 키 | 전략별 | Java RedisMarketDataService |
| `cooldown:{stk_cd}` | 종목 크로스-전략 쿨다운 | stockCooldownMinutes | Java |
| `daily:signal:count:{YYYYMMDD}` | 일일 총 신호 카운터 | 24시간 | Java |
| `error_queue` | AI 처리 실패 dead-letter 큐 | 24시간 | Python queue_worker |
