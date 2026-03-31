# S4 전략 (장대양봉 + 거래량 급증 추격매수) 완전 플로우 분석

> 작성일: 2026-03-31
> 전략 코드: `S4_BIG_CANDLE`
> 타이밍: 장중 09:30 ~ 14:30 (집중 10:00 ~ 14:30)

---

## 1. 전략 개요

5분봉 기준으로 **장대양봉**이 형성되고 **거래량이 폭발**한 종목을 실시간 추격매수하는 전략.

| 항목 | 값 |
|------|----|
| 전략명 | S4_BIG_CANDLE |
| 진입 방식 | 추격\_시장가 |
| 목표수익(TP1) | +4.0% |
| 목표수익(TP2) | +6.0% |
| 손절(SL) | -2.5% (당일 저가 하방) |
| 스캔 주기 (Java) | 3분마다 (`@Scheduled cron`) |
| 스캔 주기 (Python) | 60초마다 (`STRATEGY_SCAN_INTERVAL_SEC`) |
| Claude 임계값 | **75점** (전략 중 가장 높음) |

---

## 2. 전체 데이터 플로우

```
[websocket-listener]
  └─ ws:strength:{stk_cd} (Redis List, TTL 5분)
         ↓  실시간 체결강도 기록
[api-orchestrator - TradingScheduler]
  1) VolSurgeService  → ka10023 → 거래량 급증 Set
  2) PriceSurgeService → ka10019 → 가격 급등 Set
  3) CandidateService.getS12Candidates() → ka10032 → 후보 풀 (Redis: candidates:s12:{market})
  4) 교집합/합집합 필터 후 종목 목록 30개 이하 확정
  5) StrategyService.checkBigCandle(stkCd) per 종목
       └─ ka10080 5분봉 조회 → 장대양봉 + 거래량 + 체결강도 + 신고가 판정
  6) SignalService.processSignal() → DB저장 + telegram_queue LPUSH
         ↓
[ai-engine - queue_worker.py]
  7) telegram_queue RPOP
  8) scorer.rule_score() → 규칙 기반 1차 점수 산정
  9) 75점 미달 → CANCEL 발행 (Claude 호출 없음)
 10) 75점 이상 → human_confirm_queue LPUSH
         ↓
[ai-engine - confirm_worker.py]
 11) analyzer.analyze_signal() → Claude API 호출 (claude-sonnet-4-20250514)
 12) ai_scored_queue LPUSH
         ↓
[telegram-bot - signals.js]
 13) ai_scored_queue RPOP
 14) action=ENTER + ai_score >= MIN_AI_SCORE → 텔레그램 발송

[ai-engine - strategy_runner.py] (ENABLE_STRATEGY_SCANNER=true 시 병행)
  A) candidates:s12:{market} Redis 풀 읽기 (상위 30개)
  B) check_big_candle() 직접 호출 (ka10080 직접 httpx 호출)
  C) telegram_queue LPUSH (dedup 1h TTL)
  D) TelegramNotifier 직접 알림
```

---

## 3. Phase 1 — 후보 풀 구성 (Java: CandidateService)

### 3-1. S12 후보 풀 (S4가 재활용)

S4는 자체 전용 풀이 없고 **S12 후보 풀**(`candidates:s12:{market}`)을 공유한다.

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/service/CandidateService.java`
**메서드**: `getS12Candidates(String market)`
**Redis 키**: `candidates:s12:{market}` (TTL 10분)

```
POST {KIWOOM_BASE_URL}/api/dostk/rkinfo
api-id: ka10032
Body: { mrkt_tp: "001"|"101", mang_stk_incls: "0" }
```

**필터 조건**:
- `flu_rt > 0` (당일 양전 종목만)
- 상위 50개 limit

**캐시 없을 시 API 호출 → Redis List에 종목코드 저장 (TTL 10분)**

---

## 4. Phase 2 — 사전 필터 (Java: TradingScheduler.scanBigCandle)

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/scheduler/TradingScheduler.java`
**메서드**: `scanBigCandle()`
**스케줄**: `@Scheduled(cron = "0 0/3 9-14 * * MON-FRI")` → 09:30 ~ 14:30, 3분마다

```java
// 실행 시간 범위 재확인
if (now.isBefore(09:30) || now.isAfter(14:30)) return;

// 뉴스 매매 중단 여부 체크
if (newsControl == PAUSE) return;
```

### 4-1. 거래량 급증 사전 필터 — VolSurgeService

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/service/VolSurgeService.java`
**메서드**: `fetchSurgeCandidates()`

```
POST {KIWOOM_BASE_URL}/api/dostk/rkinfo
api-id: ka10023
Body: {
  mrkt_tp: "000",       // 전체 시장
  sort_tp: "2",         // 급증률순
  tm_tp: "1",           // 분 기준
  tm: "5",              // 5분
  trde_qty_tp: "10",    // 만주 이상
  stk_cnd: "1",         // 관리종목 제외
  pric_tp: "8",         // 1천원 이상
  stex_tp: "1"          // 거래소
}
```

**필터**: `sdnin_rt >= 50.0%` (거래량이 평소 대비 50% 이상 급증)
**반환**: 종목코드 `Set<String>`

### 4-2. 가격 급등 사전 필터 — PriceSurgeService

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/service/PriceSurgeService.java`
**메서드**: `fetchSurgeCandidates()`

```
POST {KIWOOM_BASE_URL}/api/dostk/stkinfo
api-id: ka10019
Body: {
  mrkt_tp: "000",       // 전체 시장
  flu_tp: "1",          // 급등
  tm_tp: "1",           // 분 기준
  tm: "30",             // 30분
  trde_qty_tp: "00010", // 만주 이상
  stk_cnd: "1",
  crd_cnd: "0",
  pric_cnd: "8",        // 1천원 이상
  updown_incls: "0",
  stex_tp: "1"
}
```

**필터**: `jmp_rt >= 3.0%` (30분 내 3% 이상 급등)
**반환**: 종목코드 `Set<String>`

### 4-3. 최종 후보 목록 구성 (TradingScheduler)

```java
Set<String> surgeSet = volSurge ∪ priceSurge;

if (surgeSet.isEmpty()) {
    // 사전 필터 API 실패 대비 폴백
    candidates = getS12Candidates("001") + getS12Candidates("101")
                 → distinct → limit(100)
} else {
    candidates = getS12Candidates("001") + getS12Candidates("101")
                 → distinct
                 → filter(surgeSet 교집합)  // 사전 필터 통과 종목만
                 → limit(30)
}

int maxSignals = newsControlService.getMaxSignals(5); // 기본 최대 5건
```

---

## 5. Phase 3 — 장대양봉 조건 판정 (Java: StrategyService)

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/service/StrategyService.java`
**메서드**: `checkBigCandle(String stkCd)` → `Optional<TradingSignalDto>`

### 5-1. 5분봉 데이터 조회

```
POST {KIWOOM_BASE_URL}/api/dostk/chart
api-id: ka10080
Body: {
  stk_cd: "{stkCd}",
  tic_scope: "5",       // 5분봉
  upd_stkpc_tp: "1"
}
```

**최소 10개 봉 필요**, 응답 필드: `open_pric`, `high_pric`, `low_pric`, `cur_prc`, `trde_qty`

### 5-2. 판정 조건 (Java 기준 — 엄격)

| 조건 | Java 임계값 | Python 임계값 (완화) |
|------|------------|---------------------|
| 양봉 여부 | c > o | c > o |
| 몸통 비율 (body_ratio) | **≥ 0.70** | ≥ 0.65 |
| 상승폭 (gain_pct) | **≥ 3.0%** | ≥ 2.5% |
| 거래량 배율 (vol_ratio) | **≥ 5.0배** (직전 5봉 평균 대비) | ≥ 3.0배 |
| 체결강도 (avg_strength) | **≥ 120** (데이터 존재 시만 적용) | ≥ 120 |

**체결강도 조회 경로**:
- Java: `RedisMarketDataService.getAvgCntrStrength(stkCd, 3)` → `ws:strength:{stk_cd}` (Redis List, 최근 3개 평균)
- `hasStrengthData(stkCd)` = false이면 체결강도 필터 **무조건 통과** (장 초반 WS 미수신 대응)

**신고가 여부**:
- candles[1..96] (5분봉 96개 ≈ 8시간)에서 최대 고가 산출
- 현재 고가 `h >= max20d` 이면 `isNewHigh = true`

### 5-3. 점수 산정 (Java 내부 signalScore)

```java
double score = gainPct * 3 + bodyRatio * 10 + volRatio * 0.5
             + (strength - 100) * 0.2 + (isNewHigh ? 20 : 0);
```

### 5-4. TradingSignalDto 생성

```java
TradingSignalDto {
  stkCd         : 종목코드
  strategy      : S4_BIG_CANDLE
  signalScore   : 위 계산값
  entryPrice    : c (5분봉 현재가)
  gapPct        : gain_pct (시가→현재가 상승률)
  volRatio      : 거래량 배율
  cntrStrength  : 체결강도 평균
  bodyRatio     : 몸통 비율
  isNewHigh     : 신고가 여부
  entryType     : "추격_시장가"
  targetPct     : 4.0%
  target2Pct    : 6.0%
  stopPct       : -2.5%
  tp1Price      : c * 1.04 (반올림)
  tp2Price      : c * 1.06 (반올림)
  slPrice       : l * 0.99 (당일저가 하방) or c * 0.975
}
```

---

## 6. Phase 4 — 신호 처리 및 Redis 발행 (Java: SignalService)

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/service/SignalService.java`
**메서드**: `processSignal(TradingSignalDto dto)`

### 처리 순서

1. **중복 체크** → `redisService.isSignalDuplicate(stkCd, "S4_BIG_CANDLE")` (Redis TTL 기반)
2. **종목 쿨다운** → `redisService.tryAcquireStockCooldown(stkCd, N분)` (타 전략과 동일 종목 중복 방지)
3. **일일 신호 상한** → `redisService.incrementDailySignalCount()` → `maxDailySignals` 초과 시 무시
4. **DB 저장** → PostgreSQL `TradingSignal` 엔티티 저장 (`signalRepository.save(signal)`)
5. **전략 태그 기록** → `candidateService.tagStrategy(stkCd, "S4_BIG_CANDLE")` → Redis `candidates:tag:{stkCd}` (TTL 24h)
6. **섹터 과열 추적** → `trackSectorOverheat()`
7. **큐 발행** → `redisService.pushTelegramQueue(json)` → `LPUSH telegram_queue {payload}`

**발행 JSON 구조** (`dto.toQueuePayload(signal.getId())`):

```json
{
  "id": "<DB signal id>",
  "stk_cd": "005930",
  "strategy": "S4_BIG_CANDLE",
  "signal_score": 45.2,
  "entry_price": 75000,
  "gap_pct": 3.5,
  "vol_ratio": 6.2,
  "cntr_strength": 135.0,
  "body_ratio": 0.78,
  "is_new_high": true,
  "entry_type": "추격_시장가",
  "target_pct": 4.0,
  "target2_pct": 6.0,
  "stop_pct": -2.5,
  "tp1_price": 78000,
  "tp2_price": 79500,
  "sl_price": 74250
}
```

---

## 7. Phase 5 — AI Engine 처리 (Python: queue_worker.py)

**파일**: `ai-engine/queue_worker.py`
**메서드**: `process_one(rdb)` → `run_worker(rdb)` 폴링 루프 (2초 간격)

### 처리 순서

```
RPOP telegram_queue
  → type=FORCE_CLOSE/DAILY_REPORT → 즉시 ai_scored_queue pass-through
  → 뉴스 제어 확인 (news:trading_control == PAUSE → CANCEL 발행)
  → WS 온라인 여부 확인 (ws:py_heartbeat)
  → 실시간 시세 수집:
      tick     = ws:tick:{stk_cd}
      hoga     = ws:hoga:{stk_cd}
      strength = ws:strength:{stk_cd} (최근 5개 평균)
      vi       = vi:{stk_cd}
  → scorer.rule_score(signal, market_ctx) 호출
  → should_skip_ai(r_score, "S4_BIG_CANDLE")
       True (< 75점) → CANCEL 발행 → ai_scored_queue LPUSH
       False (≥ 75점) → human_confirm_queue LPUSH → confirm_worker 위임
```

---

## 8. Phase 6 — 규칙 기반 1차 스코어링 (Python: scorer.py)

**파일**: `ai-engine/scorer.py`
**함수**: `rule_score(signal, market_ctx)`
**S4 임계값**: `CLAUDE_THRESHOLDS["S4_BIG_CANDLE"] = 75` (전략 중 가장 높음)

### S4 점수 계산 로직

```python
case "S4_BIG_CANDLE":
    vol_ratio  = signal.get("vol_ratio")   # 거래량 배율
    body_ratio = signal.get("body_ratio")  # 몸통 비율
    strength   = market_ctx.get("strength")  # ws:strength 실시간 체결강도

    # 거래량 배율 (최대 25점)
    score += 25 if vol_ratio > 10 else (20 if vol_ratio > 5 else (10 if vol_ratio > 3 else 0))

    # 몸통 비율 (최대 20점)
    score += 20 if body_ratio >= 0.8 else (10 if body_ratio >= 0.7 else 0)

    # 신고가 여부 (20점)
    score += 20 if signal.get("is_new_high") else 0

    # 체결강도 (최대 20점)
    score += 20 if strength > 150 else (15 if strength > 140 else (5 if strength > 120 else 0))
```

**공통 페널티/보너스**:
- `flu_rt > 15%` → -20점 (과열)
- `flu_rt > 10%` → -10점 (주의)
- `flu_rt < -5%` → -15점 (하락)
- `cond_count >= 4` → +10점, `== 3` → +5점
- S4는 시간대 보너스 없음

**최종 점수 범위**: 0.0 ~ 100.0

---

## 9. Phase 7 — Claude AI 2차 분석 (Python: analyzer.py / confirm_worker.py)

**파일**: `ai-engine/analyzer.py`
**함수**: `analyze_signal(signal, market_ctx, rule_score, rdb)`
**모델**: `claude-sonnet-4-20250514` (`CLAUDE_MODEL` 환경변수)
**타임아웃**: 10초

### S4 Claude 프롬프트 (압축형)

```
장대양봉 신호 평가:
종목: {stk_nm}({stk_cd}), 양봉비율: {body_ratio}, 거래량비율: {vol_ratio}배,
신고가: {is_new_high}, 규칙점수: {rule_score}/100
진입가:{entry_price:,}원 | 규칙TP1:{tp1:,}원(+4.0%) | 규칙TP2:{tp2:,}원(+6.0%) | 규칙SL:{sl:,}원(-2.5%) | 실질R:R={eff_rr:.2f}(OK/⚠️)
추가 상승 가능성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요.
```

**Claude 응답 스키마**:

```json
{
  "action": "ENTER | HOLD | CANCEL",
  "ai_score": 0~100,
  "confidence": "HIGH | MEDIUM | LOW",
  "reason": "2문장 이내",
  "adjusted_target_pct": null,
  "adjusted_stop_pct": null,
  "claude_tp1": 78000,
  "claude_tp2": 79500,
  "claude_sl": 74250
}
```

**실패 폴백** (타임아웃/오류):
- `rule_score >= 70` → ENTER
- `rule_score >= 50` → HOLD
- `rule_score < 50` → CANCEL
- confidence: LOW

### 일별 사용량 추적

- Redis 키: `claude:daily_calls:{YYYYMMDD}` (호출 횟수)
- Redis 키: `claude:daily_tokens:{YYYYMMDD}` (입출력 토큰 합계)
- 상한: `MAX_CLAUDE_CALLS_PER_DAY = 100` (기본값)

---

## 10. Phase 8 — ai_scored_queue 발행

`confirm_worker.py`가 Claude 응답을 원본 signal에 병합하여 발행:

```json
{
  // 원본 signal 필드 모두 포함 +
  "rule_score": 82.0,
  "ai_score": 88,
  "action": "ENTER",
  "confidence": "HIGH",
  "ai_reason": "거래량 폭발 + 신고가 돌파 신호, 추가 상승 여력 충분",
  "adjusted_target_pct": null,
  "adjusted_stop_pct": null,
  "claude_tp1": 78000,
  "claude_tp2": 79500,
  "claude_sl": 74250
}
```

→ `LPUSH ai_scored_queue {위 JSON}`

---

## 11. Phase 9 — 텔레그램 발송 (Node.js: signals.js)

**파일**: `telegram-bot/src/handlers/signals.js`
**처리**: `RPOP ai_scored_queue` → 2초 폴링

**발송 조건**:
- `action == "ENTER"`
- `ai_score >= MIN_AI_SCORE` (환경변수)

**HOLD**: 스코어 높을 때 별도 관망 알림
**CANCEL**: 발송 안 함 (조용히 drop)

---

## 12. Python 스캐너 보완 경로 (strategy_runner.py)

`ENABLE_STRATEGY_SCANNER=true` 환경변수로 활성화.
Java orchestrator와 **병행** 동작하는 보완 경로.

**파일**: `ai-engine/strategy_runner.py` → `_run_once(rdb)` 60초마다
**파일**: `ai-engine/strategy_4_big_candle.py`
**함수**: `check_big_candle(token, stk_cd, rdb)`

### 후보 풀 읽기

```python
kospi  = await rdb.lrange("candidates:s12:001", 0, 99)
kosdaq = await rdb.lrange("candidates:s12:101", 0, 99)
candidates = list(dict.fromkeys(kospi + kosdaq))[:30]  # 상위 30개만
```

### ka10080 직접 호출 (httpx)

```
POST {KIWOOM_BASE_URL}/api/dostk/chart
api-id: ka10080
Headers: Authorization: Bearer {token}
Body: { stk_cd: "{stk_cd}", tic_scope: "5", upd_stkpc_tp: "1" }
```

응답 필드: `stk_min_pole_chart_qry[].{open_pric, high_pric, low_pric, cur_prc, trde_qty}`

### 판정 조건 (Python — 완화)

| 조건 | Python 임계값 |
|------|--------------|
| 양봉 여부 | c > o |
| 몸통 비율 | ≥ 0.65 |
| 상승폭 | ≥ 2.5% |
| 거래량 배율 | ≥ 3.0배 (직전 5봉 평균) |
| 체결강도 | ≥ 120 (ws:strength:{stk_cd} Redis) |

### 체결강도 조회 (Python)

```python
# Redis에서 직접 읽기
strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 2)
avg_strength = mean([float(s) for s in strength_data]) if strength_data else 100
```

### dedup 중복 방지

```python
dedup_key = f"scanner:dedup:S4_BIG_CANDLE:{stk_cd}"
is_new = await rdb.set(dedup_key, "1", nx=True, ex=3600)  # 1시간 TTL
```

### 결과 발행

- `LPUSH telegram_queue {json}` (scanner:dedup 통과 시)
- `TelegramNotifier.send_buy_signal(sig)` → Telegram 직접 알림 (별도 경로)

---

## 13. 유효성 검증 — Kiwoom HTTP 200 에러 감지

**파일**: `ai-engine/http_utils.py`
**함수**: `validate_kiwoom_response(data, "ka10080", logger)`

```python
if "error" in data:       # HTTP 200 wrapping 500
    return False
if return_code != "0":    # API 레벨 비즈니스 오류
    return False
return True
```

→ False 반환 시 `strategy_4_big_candle.py` → `[]` 반환하여 해당 종목 skip

---

## 14. 수동 실행 API (TradingController)

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/controller/TradingController.java`

```
POST /api/trading/strategy/s4/run?market=000
```

**처리 로직**:
```java
candidates = getS12Candidates("001") + getS12Candidates("101")
             → distinct → limit(30)
for (stk_cd : candidates) {
    checkBigCandle(stk_cd) → processSignal() → cnt++
    if (cnt >= 5) break;
}
return { "strategy": "S4_BIG_CANDLE", "published": cnt }
```

> **주의 (Pending P1)**: 수동 실행 API는 사전 필터(volSurge/priceSurge)를 거치지 않고
> 스케줄러와 달리 `getS12Candidates`를 직접 사용함. `getAllCandidates()` → 전략별 풀로
> 교체 대상임 (`docs/보완작업계획_20260331.md` P1 항목).

---

## 15. Redis 키 요약

| 키 | 용도 | TTL | 생성 주체 |
|----|------|-----|----------|
| `candidates:s12:{market}` | S4 후보 풀 (ka10032 거래대금상위) | 10분 | Java CandidateService |
| `ws:strength:{stk_cd}` | 실시간 체결강도 리스트 | 5분 | websocket-listener |
| `telegram_queue` | Java→AI Engine 신호 큐 | 12시간 | Java SignalService |
| `ai_scored_queue` | AI Engine→Telegram Bot 큐 | - | ai-engine confirm_worker |
| `scanner:dedup:S4_BIG_CANDLE:{stk_cd}` | Python 스캐너 중복 방지 | 1시간 | ai-engine strategy_runner |
| `candidates:tag:{stk_cd}` | 종목별 전략 태그 | 24시간 | Java SignalService |
| `claude:daily_calls:{YYYYMMDD}` | Claude API 일별 호출 카운터 | 24시간 | ai-engine scorer/analyzer |
| `claude:daily_tokens:{YYYYMMDD}` | Claude API 일별 토큰 합계 | 24시간 | ai-engine analyzer |
| `news:trading_control` | 뉴스 기반 매매 중단 플래그 | - | api-orchestrator |

---

## 16. 전체 Kiwoom API 호출 목록

| API ID | URL | 호출 주체 | 용도 |
|--------|-----|----------|------|
| `ka10032` | `POST /api/dostk/rkinfo` | Java CandidateService | 거래대금 상위 (S4 후보 풀) |
| `ka10023` | `POST /api/dostk/rkinfo` | Java VolSurgeService | 거래량 급증 사전 필터 |
| `ka10019` | `POST /api/dostk/stkinfo` | Java PriceSurgeService | 가격 급등 사전 필터 |
| `ka10080` | `POST /api/dostk/chart` | Java StrategyService | 5분봉 차트 (장대양봉 판정) |
| `ka10080` | `POST /api/dostk/chart` | Python strategy_4 (httpx) | 5분봉 차트 (스캐너 경로) |
| `ka10046` | `POST /api/dostk/mrkcond` | Python http_utils | 체결강도 REST 조회 (보조) |

---

## 17. 판정 조건 비교표 (Java vs Python)

| 조건 | Java (엄격) | Python (완화) | 비고 |
|------|------------|--------------|------|
| 몸통 비율 | ≥ 0.70 | ≥ 0.65 | |
| 상승폭 | ≥ 3.0% | ≥ 2.5% | |
| 거래량 배율 | **≥ 5.0배** | ≥ 3.0배 | 이평선 필터로 보완 |
| 체결강도 임계 | 120 (데이터 있을 때만) | 120 | |
| 봉 최소 개수 | 10개 | 20개 | Python이 더 엄격 |
| 사전 필터 | volSurge ∪ priceSurge | 없음 (풀에서 직접) | |

---

## 18. 알려진 이슈 / 미완료 항목 (2026-03-31)

1. **[P1] `TradingScheduler.scanBigCandle()`의 후보 풀**
   현재 `getS12Candidates()`를 사용. S4 전용 풀(`candidates:s4:{market}`)로 분리 필요.
   → `docs/보완작업계획_20260331.md` 참고

2. **[P1] `strategy_runner.py` S4 후보 키**
   `candidates:s12:001/101`을 직접 읽음 → 적절하나, S4 전용 풀 생성 후 `candidates:s4:001/101`로 전환 예정

3. **[Pending] `ka10053` 당일상위이탈원 체크**
   전략 정의서에 명시(`상위 이탈원 없음`)되어 있으나 Java / Python 모두 현재 미구현 상태
