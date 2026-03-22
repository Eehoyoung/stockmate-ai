# StockMate AI – 전체 프로세스 분석 및 개선 사항

> 최초 작성일: 2026-03-21 | 최종 수정: 2026-03-21 (Phase 1/3/4 고도화 완료 반영)
> 대상 모듈: `ai-engine` · `api-orchestrator` · `telegram-bot` · `websocket-listener`

---

## 1. 전체 프로세스 흐름 (현황)

```
[06:50 / 07:25] api-orchestrator
    TokenRefreshScheduler → Kiwoom REST API → KiwoomToken 저장

[07:30] api-orchestrator
    WebSocketSubscriptionManager.setupPreMarketSubscription()
    → Kiwoom WS (GRP 1~4) : 0H 예상체결, 0D 호가잔량
    → RedisMarketDataService → ws:expected:{stkCd}, ws:hoga:{stkCd}

[병행] websocket-listener (Python)
    ws_client.py → Kiwoom WS (GRP 5~8)
    GRP5 0B 체결   → redis_writer.write_tick()   → ws:tick:{stkCd}, ws:strength:{stkCd}
    GRP6 0H 예상체결 → redis_writer.write_expected() → ws:expected:{stkCd}
    GRP7 1h VI     → redis_writer.write_vi()     → vi:{stkCd}, vi_watch_queue
    GRP8 0D 호가잔량 → redis_writer.write_hoga()   → ws:hoga:{stkCd}

[08:30~09:00] api-orchestrator TradingScheduler
    scanAuction() → StrategyService.scanAuction() → SignalService.processSignal()
    → telegram_queue (Redis LPUSH)

[09:00~09:10] scanGapOpening()  → S1_GAP_OPEN
[실시간 5초마다] processViWatchQueue() → S2_VI_PULLBACK
[09:30~14:30]  scanInstFrgn()   → S3_INST_FRGN
[09:30~14:30]  scanBigCandle()  → S4_BIG_CANDLE
[10:00~14:00]  scanProgramFrgn() → S5_PROG_FRGN
[09:30~13:00]  scanThemeLaggard() → S6_THEME_LAGGARD

[ai-engine] engine.py
    queue_worker.py → RPOP telegram_queue
    → scorer.py.rule_score() : 규칙 기반 1차 스코어
    → (60점 이상) analyzer.py → Claude API
    → LPUSH ai_scored_queue

[telegram-bot] signals.js
    RPOP ai_scored_queue
    → action=ENTER & ai_score >= 65 → Telegram 메시지 발송
    → action=HOLD  & ai_score >= 80 → Telegram 메시지 발송
    → action=CANCEL → 무시
```

---

## 2. 발견된 문제 목록

### 🔴 Critical – 즉시 수정 필요

---

#### [C-1] ✅ 수정 완료 – `ai-engine` 전술 파일 3개 – 잘못된 Redis import

**파일:**
- `ai-engine/strategy_2_vi_pullback.py`
- `ai-engine/strategy_4_big_candle.py`
- `ai-engine/strategy_7_auction.py`

**원인:**
```python
from idlelib.multicall import r  # Python 내부 Tkinter/IDLE 라이브러리
```
`idlelib.multicall`은 Python IDLE 편집기의 내부 모듈로, `r`은 Redis 클라이언트가 아닌 `MultiCall` 클래스다. 이후 `r.hgetall()`, `r.lrange()` 등을 호출하면 `AttributeError` 런타임 크래시가 발생한다.

**적용된 수정:**
```python
import redis as _redis_lib

r = _redis_lib.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD") or None,
    decode_responses=True,
)
```
3개 파일 모두 동일하게 수정. 환경 변수 기반 연결로 전환.

---

#### [C-2] ✅ 수정 완료 – `api-orchestrator` – `telegram_queue` 페이로드 누락

**파일:** `api-orchestrator/.../service/SignalService.java`

**원인:**
`SignalService.processSignal()`이 `telegram_queue`에 넣는 JSON은 4개 필드뿐이었다:
```java
Map.of("id", ..., "stk_cd", ..., "strategy", ..., "message", ...)
```
`ai-engine/scorer.py`의 `rule_score()`는 `gap_pct`, `cntr_strength`, `bid_ratio`, `vol_ratio`, `pullback_pct`, `net_buy_amt`, `continuous_days`, `is_new_high`, `vol_rank`, `theme_name`, `target_pct`, `stop_pct`, `entry_type` 등을 신호 JSON에서 직접 읽는다. 이 필드들이 없으면 모든 전술 `rule_score` = 0점 → `should_skip_ai()` 통과 불가 → **모든 신호 CANCEL 처리 (AI 분석 미실행)**.

**적용된 수정:**
```java
Map<String, Object> payload = new LinkedHashMap<>();
payload.put("id",              signal.getId());
payload.put("stk_cd",          stkCd);
payload.put("stk_nm",          dto.getStkNm());
payload.put("strategy",        strategy);
payload.put("message",         dto.toTelegramMessage());
payload.put("entry_type",      dto.getEntryType());
payload.put("target_pct",      dto.getTargetPct());
payload.put("stop_pct",        dto.getStopPct());
payload.put("signal_score",    dto.getSignalScore());
payload.put("gap_pct",         dto.getGapPct());
payload.put("cntr_strength",   dto.getCntrStrength());
payload.put("bid_ratio",       dto.getBidRatio());
payload.put("vol_ratio",       dto.getVolRatio());
payload.put("pullback_pct",    dto.getPullbackPct());
payload.put("theme_name",      dto.getThemeName());
payload.put("net_buy_amt",     dto.getNetBuyAmt());
payload.put("continuous_days", dto.getContinuousDays());
payload.put("is_new_high",     dto.getIsNewHigh());
payload.put("vol_rank",        dto.getVolRank());
payload.put("market_type",     dto.getMarketType());
String telegramMsg = objectMapper.writeValueAsString(payload);
```
`java.util.LinkedHashMap` import 추가.

---

#### [C-3] ✅ 수정 완료 – `ai-engine` – `analyzer.py` 동기 Claude 클라이언트 사용

**파일:** `ai-engine/analyzer.py`

**원인:**
```python
client = anthropic.Anthropic(api_key=api_key)   # 동기 클라이언트
response = client.messages.create(...)           # 블로킹 호출
```
`analyze_signal()`은 `async def`인데 동기 I/O 호출로 이벤트 루프 블로킹 발생.

**적용된 수정:**
```python
client = anthropic.AsyncAnthropic(api_key=api_key)
response = await client.messages.create(...)
```

---

#### [C-4] ✅ 수정 완료 – `ai-engine` – Python 전술 파일 7개가 파이프라인에 연결되지 않음

**파일:** `ai-engine/strategy_1_gap_opening.py` ~ `strategy_7_auction.py`

**원인:**
7개의 Python 전술 파일은 `engine.py`, `queue_worker.py`, `analyzer.py`, `scorer.py`, `redis_reader.py` 어디에서도 `import`되지 않는다. 실제 전술 실행은 `api-orchestrator`의 `StrategyService.java`에서 이루어진다. 파일들이 초기 프로토타입임을 인식하기 어려워 혼란 유발.

**적용된 수정:**
모든 7개 파일 최상단에 명시적 프로토타입 경고 주석 추가:
```python
# NOTE: 이 파일은 프로토타입 코드입니다. ai-engine 파이프라인(engine.py)에 연결되어 있지 않습니다.
# 실제 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
```
`strategy_1_gap_opening.py`의 하드코딩된 Redis 연결(`host='localhost'`)도 환경 변수 기반으로 함께 수정.

---

### 🟡 Moderate – 기능 이상 또는 데이터 오류 유발 가능

---

#### [M-1] VI 눌림목 감시 큐 이중 등록 (중복 신호 위험)

**파일:**
- `websocket-listener/redis_writer.py:109-125` (`write_vi()`)
- `api-orchestrator/.../service/RedisMarketDataService.java:122-133` (`saveViEvent()`)

**문제:**
두 서비스 모두 Kiwoom WebSocket `1h` (VI 발동/해제) 이벤트를 수신하고, VI 해제 시 `vi_watch_queue`에 감시 아이템을 등록한다. `websocket-listener`와 `api-orchestrator`가 동시에 동작하면 하나의 VI 해제 이벤트에 대해 큐에 **2개의 감시 항목**이 등록되어 S2 신호가 중복 발행된다.

**수정 방향:**
- `vi_watch_queue` 등록 책임을 하나의 모듈(권장: `api-orchestrator`)에만 부여한다.
- `websocket-listener`의 `write_vi()`에서 `vi_watch_queue` LPUSH 로직을 제거하고 VI 상태 저장(`vi:{stkCd}`)만 담당하게 한다.

---

#### [M-2] `scorer.py` S4_BIG_CANDLE – 잘못된 필드 사용

**파일:** `ai-engine/scorer.py:68`

**문제:**
```python
case "S4_BIG_CANDLE":
    body_ratio = _safe_float(signal.get("cntr_strength", 0))  # 임시
```
`cntr_strength`(체결강도)를 `body_ratio`(몸통 비율)로 쓰고 있다. 이 두 값은 전혀 다른 지표다. 실제 `TradingSignalDto`에 `body_ratio` 필드가 없어 임시 처리된 것으로 보이며, 스코어 계산이 부정확하다.

**수정 방향:**
`TradingSignalDto`에 `bodyRatio` 필드를 추가하고, `StrategyService.checkBigCandle()`에서 계산한 `bodyRatio`를 DTO에 포함시켜 전달한다.

---

#### [M-3] `scorer.py` S5_PROG_FRGN – 고정 점수 플레이스홀더

**파일:** `ai-engine/scorer.py:75-77`

**문제:**
```python
case "S5_PROG_FRGN":
    score += min(25, net_amt / 1_000_000 * 0.3)
    score += 25    # ← 고정값 (플레이스홀더)
    score += 15    # ← 고정값 (주석: "상장 대형주 가산 - 실제 구현 시 종목 데이터 활용")
```
net_amt가 0이어도 기본 40점이 보장되어, 약 670억 이상 순매수면 무조건 Claude 호출 임계값(60점)을 넘는다. 실제 대형주/소형주 구분 로직이 없다.

**수정 방향:**
종목 데이터(`시가총액`, `상장주식수` 등)를 Redis나 신호 페이로드에서 읽어 실제 조건을 구현하거나, 임시 가산점에 대한 명시적인 주석을 남긴다.

---

#### [M-4] `TradingScheduler` S5 시장 코드 불일치

**파일:** `api-orchestrator/.../scheduler/TradingScheduler.java:184-185`

**문제:**
```java
List<TradingSignalDto> kospiSignals  = strategyService.scanProgramFrgn("P00101");
List<TradingSignalDto> kosdaqSignals = strategyService.scanProgramFrgn("P10102");
```
다른 전술(S3, S7 등)은 `"001"`, `"101"`을 사용하는데 S5만 `"P00101"`, `"P10102"` 코드를 사용한다. `ka90003` API가 프로그램 매매 전용 시장 코드를 요구하는지, 일반 코드도 수용하는지 확인이 필요하다.

**수정 방향:**
Kiwoom API 문서에서 `ka90003`의 `mrkt_tp` 허용값을 확인하고 일관된 코드 체계를 적용한다.

---

#### [M-5] `strategy_1_gap_opening.py` – 하드코딩된 Redis 연결

**파일:** `ai-engine/strategy_1_gap_opening.py:16`

**문제:**
```python
r = redis.Redis(host='localhost', decode_responses=True)
```
환경 변수를 무시하고 localhost에 고정 연결한다. Docker/원격 환경에서 작동하지 않는다.

---

### 🔵 Minor – 코드 품질 / 잠재적 리스크

---

#### [m-1] `application.yml` 자격 증명 노출

**파일:** `api-orchestrator/src/main/resources/application.yml:7-8`

**문제:**
```yaml
password: cv93523827
```
DB 비밀번호가 소스코드에 평문으로 존재한다. `.env` import가 `optional`로 설정되어 있어 `.env`가 없으면 하드코딩된 값이 사용된다. `.gitignore`에서 `application.yml`이 제외되지 않으면 리포지토리에 노출된다.

**수정 방향:**
개발용 값도 `application-local.yml`로 분리하고, `application.yml`에는 `${}`만 남긴다.

---

#### [m-2] `signals.js` `nextDelay` 함수 오염

**파일:** `telegram-bot/src/handlers/signals.js:92-95`

**문제:**
```javascript
const nextDelay = item => {   // ← `item` 파라미터가 외부 변수명과 충돌
    if (emptyCount === 0) return POLL_INTERVAL_MS;
    return Math.min(POLL_INTERVAL_MS * (1 + emptyCount * 0.1), 10_000);
};
setTimeout(poll, nextDelay());  // 인수 없이 호출
```
`item` 파라미터는 사용되지 않으면서 외부 스코프의 `const item`을 가린다. 기능 버그는 아니지만 가독성 혼란을 유발한다.

**수정 방향:**
```javascript
const nextDelay = () => {
    if (emptyCount === 0) return POLL_INTERVAL_MS;
    return Math.min(POLL_INTERVAL_MS * (1 + emptyCount * 0.1), 10_000);
};
```

---

#### [m-3] `DataCleanupScheduler` / `cleanupTickData` 미구현

**파일:**
- `api-orchestrator/.../scheduler/TradingScheduler.java:269-274` (`cleanupTickData`)
- `api-orchestrator/.../scheduler/DataCleanupScheduler.java` (별도 파일 존재하나 실제 로직 확인 필요)

**문제:**
```java
@Scheduled(cron = "0 0 23 * * *")
public void cleanupTickData() {
    log.info("틱 데이터 정리 완료");  // ← 실제 삭제 로직 없음
}
```
매일 23시에 실행되지만 아무것도 하지 않는다. 틱 데이터 누적 시 DB 용량 문제가 발생할 수 있다.

---

#### [m-4] `websocket-listener` 재연결 상한 초과 시 종료

**파일:** `ai-engine/../websocket-listener/ws_client.py:131-133`

**문제:**
```python
if reconnect_count > MAX_RECONNECTS:   # MAX_RECONNECTS = 10
    logger.critical("[WS] 최대 재연결 횟수 %d 초과 – 종료", MAX_RECONNECTS)
    break
```
10회 재연결 실패 시 프로세스가 조용히 종료된다. 외부 감시(systemd, supervisor, Docker restart policy)가 없으면 장중에 데이터 수집이 중단된다.

**수정 방향:**
`sys.exit(1)`로 명시적 종료 코드를 내보내거나, 재연결 횟수 제한을 제거하고 헬스 엔드포인트(`/health`)를 통해 외부에서 감시하도록 한다.

---

#### [m-5] `ai-engine` 전술 파일에서 비동기/동기 Redis 혼용

**파일:** `strategy_1_gap_opening.py`, `strategy_3_inst_foreign.py`, `strategy_5_program_buy.py` 등

**문제:**
일부 파일은 `httpx.AsyncClient`(비동기)를 사용하면서, 다른 파일은 `redis.Redis`(동기)를 사용하는 혼용 패턴이 존재한다. 파일들이 실제 파이프라인에 연결될 경우 `asyncio` 이벤트 루프와 충돌이 발생한다.

---

## 3. 수정 우선순위 요약

| 우선순위 | ID | 파일 | 내용 | 상태 |
|---|---|---|---|---|
| 🔴 1 | C-2 | `SignalService.java` | `telegram_queue` 전체 DTO 직렬화 → `toQueuePayload()` 중앙화 | ✅ 완료 |
| 🔴 2 | C-1 | `strategy_2,4,7.py` | `idlelib` → Redis import 수정 | ✅ 완료 |
| 🔴 3 | C-3 | `analyzer.py` | `AsyncAnthropic` 비동기 클라이언트 전환 | ✅ 완료 |
| 🔴 4 | C-4 | `strategy_1~7.py` | 프로토타입 경고 주석 추가 + `strategy_runner.py` 생성으로 파이프라인 연결 | ✅ 완료 |
| 🟡 5 | M-1 | `redis_writer.py` | `vi_watch_queue` 이중 등록 제거 | ✅ 완료 |
| 🟡 6 | M-2 | `TradingSignalDto.java`, `StrategyService.java`, `scorer.py` | S4 `bodyRatio` 필드 추가 및 매핑 수정 | ✅ 완료 |
| 🟡 7 | M-3 | `scorer.py` | S5 실제 지표 기반 동적 스코어링으로 교체 | ✅ 완료 |
| 🟡 8 | M-4 | `TradingScheduler.java` | S5 시장 코드 `"P00101"` → `"001"` 통일 | ✅ 완료 |
| 🔵 9 | m-1 | `application.yml` | 하드코딩 자격 증명 → 환경변수 기본값 방식으로 전환 | ✅ 완료 |
| 🔵 10 | m-2 | `signals.js` | `nextDelay` 미사용 `item` 파라미터 제거 | ✅ 완료 |
| 🔵 11 | m-3 | `TradingScheduler.java` | 빈 stub 제거 (DataCleanupScheduler 23:30 전담) | ✅ 완료 |
| 🔵 12 | m-4 | `ws_client.py` | 재연결 한계 초과 시 `sys.exit(1)` 추가 | ✅ 완료 |
| 🔵 13 | 추가발견 | `token_loader.py` | Redis 키 `"kiwoom:access_token"` → `"kiwoom:token"` 수정 | ✅ 완료 |

---

## 4. 아키텍처 관련 제안

### 4-1. WebSocket 역할 분리 명확화

현재 `api-orchestrator`(Java)와 `websocket-listener`(Python) 모두 Kiwoom WebSocket에 연결하고 있다. 서로 다른 GRP 번호를 사용하여 충돌을 피하고 있으나, VI 이벤트(1h)를 두 곳에서 처리하고 있어 중복 문제가 발생한다.

**권장 구조:**
```
websocket-listener (Python)
    → 모든 실시간 데이터 수신 (GRP 통합)
    → Redis 저장만 담당 (단일 책임)

api-orchestrator (Java)
    → Redis 데이터 읽기만 수행
    → WebSocket 연결 제거
```
또는 두 서비스 중 하나를 WebSocket 전담으로 지정하고 나머지는 완전히 제거한다.

### 4-2. `SignalService` 페이로드 직렬화 표준화

`TradingSignalDto`의 Java 필드명(camelCase)과 Python `scorer.py`가 기대하는 필드명(snake_case) 간의 명확한 매핑 계약이 필요하다. `ObjectMapper`에 `PropertyNamingStrategies.SNAKE_CASE`를 설정하거나 `@JsonProperty`를 명시하는 것을 권장한다.

### 4-3. AI Engine 전술 파일 정리

Python 전술 파일(S1~S7)은 두 가지 방향 중 하나를 선택해야 한다:
- **삭제**: Java가 전술 실행을 전담하고, Python은 AI 분석만 담당하는 현재 구조를 유지한다.
- **활성화**: ai-engine을 독립형 전술 스캐너로 전환하고, Java는 오케스트레이션/DB/WebSocket만 담당한다. 이 경우 각 파일의 Redis 연결 방식을 비동기로 통일해야 한다.
