# StockMate AI — 전면 기술 부채 해소 계획

> 작성일: 2026-04-14  
> 범위: ai-engine (Python) · api-orchestrator (Java) · telegram-bot (Node.js) · websocket-listener (Python)  
> 원칙: 기능 변경 없음, 테스트 가능한 증분 적용, 롤백 단위 = 1 PR

---

## 전체 우선순위 맵

| 티어 | 항목 수 | 기준 |
|------|---------|------|
| **Critical** | 4 | 버그 유발·런타임 오류·잘못된 결과 가능성 |
| **High**     | 6 | 중복 로직으로 인한 오작동 위험, 유지보수 불가 수준 |
| **Medium**   | 8 | 가독성·확장성 저해, 다음 기능 개발 속도 저하 |
| **Low**      | 5 | 코드 스타일·일관성·관례 위반 |

---

## 진행 현황 (2026-04-16)

| 항목 | 상태 | 비고 |
|------|------|------|
| C-1 `_safe_float` 통합 | ✅ Done | utils.py 중앙화, 9개 파일 일괄 적용 |
| C-2 config.py 단일 진입점 | ✅ Done | KIWOOM_BASE_URL·REDIS_*·PG_*·MARKET_LIST 통합 |
| C-3 `import json` 모듈 수준 | ✅ Done | queue_worker.py, db_writer.py 정리 |
| C-4 Human Confirm Gate 분리 | ✅ Done | telegram-bot/handlers/confirmGate.js 신규 |
| H-1 CandidateService 템플릿화 | ✅ Done | `loadCandidates()` 공통 템플릿 이미 적용 — 10메서드 2~3줄 stub으로 축소 완료 |
| H-2 signals.js processItem 14분기 | ✅ Done | `BROADCAST_HANDLERS` dispatch map + `_broadcast` 헬퍼 |
| H-3 formatNewsAlert 이동 | ✅ Done | signals.js → formatter.js 완료 |
| H-4 strategy_runner closures 13개 | ✅ Done | `_scan_sN` 모듈 함수 + `_SCHEDULE` 테이블 |
| H-5 analyzer `_build_user_message` 15분기 | ✅ Done | `_STRATEGY_TEMPLATES` dict + body 함수 15개 |
| H-6 CandidateService legacy 제거 | 🔶 Partial | DataQualityScheduler 폴백 제거 완료; `getCandidates()`는 REST controller 의존으로 유지 |
| M-1 health_server 추출 | ✅ Done | ai-engine/health_server.py 분리 완료 |
| M-2 strategy_meta.py 도입 | ✅ Done | ai-engine/strategy_meta.py 신규 생성 완료 |
| M-3 08:30 cron 충돌 | ✅ Done | preMarketNewsBrief 08:28, preloadAuctionCandidates 08:30 으로 분리 |
| M-4 redis_reader Confirm Gate 임포트 | ✅ Done | confirm_gate_redis.py 분리; redis_reader.py 는 하위 호환 재수출만 유지 |
| M-5 queue_worker R:R 인라인 제거 | ✅ Done | `from tp_sl_engine import compute_rr` 위임 완료 |
| M-6 formatter.js `_effectiveRR` | ✅ Done | formatSignal·formatSellSignal 모두 `_effectiveRR()` 단일 경유 |
| M-7 MarketMessageBuilder | ✅ Done | MarketMessageBuilder.java 유틸 클래스 분리 완료 |
| M-8 candidates_builder → http_utils | ✅ Done | `_post_with_retry` 제거, `kiwoom_post()` 위임 완료 |
| L-1 `from __future__ import annotations` | ✅ Done | 전체 Python 파일 적용 완료 |
| L-2 LocalDate.now() 인라인 제거 | ✅ Done | `import java.time.LocalDate` 추가, 인라인 제거 |
| L-3 console.* → logger | ✅ Done | signals.js 전체 logger 통일 완료 |
| L-4 getAvgCntrStrength 명명 | ✅ Done | Javadoc에 get_hoga_ratio() 와의 분자·분모 역전 명시 |
| L-5 bool_env 확산 | ✅ Done | utils.bool_env() → engine.py 전체 적용 완료 |

---

## CRITICAL — 즉시 수정

### C-1. `_safe_float` 계열 4개 중복 정의 → `utils.py` 단일화

**문제**  
동일한 Kiwoom 응답 파싱 로직이 4곳에 산재해 있다. 각 구현의 세부 처리 방식이 미묘하게 달라 동일 입력에 대해 다른 결과를 낼 수 있다.

| 파일 | 이름 | 차이 |
|------|------|------|
| `scorer.py` | `_safe_float(v, default=0.0)` | NaN 방어 없음 |
| `db_writer.py` (inline) | `_sf(v, default=None)` | `f == f` NaN 방어 있음 |
| `candidates_builder.py` | `_clean(v, default=0.0)` | 기본값 0.0, NaN 방어 없음 |
| `queue_worker.py` | `_fv(v, default=0.0)` | NaN 방어 없음 |

**수정 계획**  
1. `ai-engine/utils.py` 신규 생성
```python
# ai-engine/utils.py
from __future__ import annotations
from typing import Optional

def safe_float(v, default: float = 0.0) -> float:
    """Kiwoom 응답 숫자 필드 안전 변환. 쉼표·부호·NaN 방어."""
    try:
        f = float(str(v).replace(",", "").replace("+", ""))
        return f if f == f else default  # NaN guard
    except (TypeError, ValueError):
        return default

def safe_float_opt(v) -> Optional[float]:
    """Optional 버전 — None 입력 시 None 반환."""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").replace("+", ""))
        return f if f == f else None
    except (TypeError, ValueError):
        return None
```

2. 각 파일에서 기존 정의 삭제 후 import 교체:
```python
# Before (scorer.py 등)
def _safe_float(v, default=0.0): ...

# After
from utils import safe_float as _safe_float
```

3. `db_writer.py:137` inline `_sf` — 함수 밖으로 제거 + `from utils import safe_float_opt as _sf`

---

### C-2. `config.py` 사실상 미사용 — 환경변수 선언 일원화

**문제**  
`ai-engine/config.py` (13줄) 에는 `KIWOOM_BASE_URL`, `WS_URL`, `MARKETS`, `COMMON_FILTERS` 만 있지만 실제 모듈들은 이것을 import하지 않고 각자 `os.getenv("KIWOOM_BASE_URL")` 를 재선언한다.

중복 선언 위치:
- `http_utils.py:12` — `KIWOOM_BASE_URL = os.getenv(...)`
- `candidates_builder.py:17` — `KIWOOM_BASE_URL = os.getenv(...)`
- `strategy_runner.py:31` — (http_utils 를 통해 간접 사용)
- 전략 파일 S1~S15 다수 — http_utils 임포트이므로 직접은 아님

**수정 계획**  
`config.py` 를 실질적 설정 허브로 격상:
```python
# ai-engine/config.py (확장 버전)
import os

# Kiwoom
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://openapi.kiwoom.com")
WS_URL          = os.getenv("KIWOOM_WS_URL",   "wss://openapi.kiwoom.com/ws")

# Redis
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None

# PostgreSQL
PG_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
PG_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB       = os.getenv("POSTGRES_DB",       "SMA")
PG_USER     = os.getenv("POSTGRES_USER",     "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
PG_ENABLED  = os.getenv("PG_WRITER_ENABLED", "true").lower() == "true"

# 시장
MARKETS = ["001", "101"]
COMMON_FILTERS = {
    "min_price": 1000,
    "max_price": 500000,
    "min_volume": 100000,
}
```

`engine.py`, `http_utils.py`, `candidates_builder.py` 에서 `os.getenv` 직접 선언 제거 후 `from config import ...` 교체.

---

### C-3. `db_writer.py` 내부 `import json as _json` 함수 내부 위치 오류

**문제**  
`db_writer.py:333` — `insert_overnight_eval()` 함수 **내부**에 `import json as _json` 선언.  
Python 은 함수 내 import를 허용하지만, 매 호출 시마다 모듈 조회 비용 발생 + 가독성 극히 나쁨.

**수정**  
파일 최상단 `import json` 이미 있음(17줄) → 함수 내부 `import json as _json` 제거, `_json.dumps()` → `json.dumps()` 교체.

---

### C-4. `signals.js` — Human Confirm Gate 코드 혼재 (데드코드 위험)

**문제**  
`telegram-bot/src/handlers/signals.js:380~450` 에 `sendConfirmRequest()`, `startConfirmPoller()` 함수가 있다. `ENABLE_CONFIRM_GATE=false` 가 기본값이므로 이 코드는 사실상 항상 비활성이지만 `processItem()` 의 `PAUSE_CONFIRM_REQUEST` 분기와 얽혀 정상 신호 흐름에 영향을 줄 수 있다.

**수정 계획**  
- Confirm Gate 관련 함수를 별도 파일 `src/handlers/confirmGate.js` 로 분리
- `signals.js` 의 `PAUSE_CONFIRM_REQUEST` 분기에 `if (process.env.ENABLE_CONFIRM_GATE !== 'true') return;` 가드 추가
- 분리 후 signals.js 핵심 흐름이 명확해짐

---

## HIGH — 이번 스프린트 내 수정

### H-1. `CandidateService.java` — 10개 `getS{N}Candidates()` 메서드 템플릿화

**문제**  
`getS1Candidates()` ~ `getS15Candidates()` (10개, 약 550줄) 가 아래 6단계를 동일 구조로 반복:
1. `redisTemplate.opsForList().range(key, 0, -1)` 캐시 확인
2. `MarketTimeUtil` 가드
3. Kiwoom API 호출 (`fetchKa10029` 등)
4. `.stream().filter(...).map(...)` 변환
5. `delete + rightPushAll + expire` Redis 갱신
6. `updateWatchlist()` 호출

**수정 계획**  
전략 메타데이터 레코드 + 템플릿 메서드 패턴 적용:

```java
// CandidateService.java — 리팩터링 후 구조

@FunctionalInterface
interface CandidateFetcher {
    List<Map<String, String>> fetch(String market) throws Exception;
}

private record StrategyMeta(
    String strategyKey,   // "s1", "s4" ...
    CandidateFetcher fetcher
) {}

// 빌드 시 초기화 (PostConstruct)
private List<StrategyMeta> strategyMetas;

@PostConstruct
void initStrategyMetas() {
    strategyMetas = List.of(
        new StrategyMeta("s1",  market -> fetchAndFilterS1(market)),
        new StrategyMeta("s3",  market -> fetchAndFilterS3(market)),
        // ...
    );
}

// 공통 템플릿
private void loadCandidates(StrategyMeta meta, String market) {
    String key = "candidates:" + meta.strategyKey() + ":" + market;
    if (!redisTemplate.opsForList().range(key, 0, -1).isEmpty()) return;
    if (!MarketTimeUtil.isMarketHours()) return;
    try {
        List<Map<String, String>> candidates = meta.fetcher().fetch(market);
        if (!candidates.isEmpty()) {
            redisTemplate.delete(key);
            redisTemplate.opsForList().rightPushAll(key, serialize(candidates));
            redisTemplate.expire(key, Duration.ofMinutes(30));
            updateWatchlist(candidates);
        }
    } catch (Exception e) {
        log.warn("[Candidate] {} {} 로드 실패: {}", meta.strategyKey(), market, e.getMessage());
    }
}
```

결과: 550줄 → 약 180줄 (핵심 fetch 로직만 남김)

---

### H-2. `signals.js processItem()` — 14분기 if-chain → dispatch table

**문제**  
`processItem()` 함수가 14개 타입을 if/else if 체인으로 처리. 각 분기마다:
```javascript
for (const chatId of chatIds) {
    await bot.telegram.sendMessage(chatId, text, { parse_mode: 'HTML' });
}
```
가 복붙되어 있음.

**수정 계획**  
dispatch table + 공통 send 헬퍼:

```javascript
// 공통 브로드캐스트
async function broadcast(bot, chatIds, text, options = {}) {
    for (const chatId of chatIds) {
        try {
            await bot.telegram.sendMessage(chatId, text, { parse_mode: 'HTML', ...options });
        } catch (err) {
            logger.error({ chatId, err: err.message }, 'sendMessage 실패');
        }
    }
}

// dispatch table
const TYPE_HANDLERS = {
    NEWS_ALERT:        (item) => formatter.formatNewsAlert(item),
    CALENDAR_ALERT:    (item) => formatter.formatCalendarAlert(item),
    SECTOR_OVERHEAT:   (item) => formatter.formatSectorOverheat(item),
    SYSTEM_ALERT:      (item) => formatter.formatSystemAlert(item),
    MARKET_OPEN_BRIEF: (item) => formatter.formatMarketOpenBrief(item),
    PRE_MARKET_BRIEF:  (item) => formatter.formatPreMarketBrief(item),
    MIDDAY_REPORT:     (item) => formatter.formatMiddayReport(item),
    SELL_SIGNAL:       (item) => formatter.formatSellSignal(item),
    OVERNIGHT_HOLD:    (item) => formatter.formatOvernightHold(item),
    DAILY_REPORT:      (item) => formatter.formatDailyReport(item),
    FORCE_CLOSE:       (item) => formatter.formatForceClose(item),
    ENTER:             (item) => formatter.formatSignal(item),
    HOLD:              (item) => formatter.formatSignal(item),
    CANCEL:            (item) => formatter.formatSignal(item),
};

async function processItem(item, bot, chatIds) {
    const type   = item.type ?? item.action;
    const handler = TYPE_HANDLERS[type];
    if (!handler) {
        logger.warn({ type }, '알 수 없는 타입 — 무시');
        return;
    }
    const text = handler(item);
    if (text) await broadcast(bot, chatIds, text);
}
```

결과: 180줄 → 50줄 (processItem)

---

### H-3. `formatNewsAlert` signals.js 내부 정의 → formatter.js 이동

**문제**  
`signals.js:490` 에 `formatNewsAlert()` 가 정의되어 있음. 모든 포매터는 `formatter.js` 에 있어야 함.

**수정**  
1. `formatter.js` 끝에 `formatNewsAlert(item)` 추가
2. `signals.js` 에서 해당 함수 삭제
3. `formatter.js` 의 `module.exports` 에 추가

---

### H-4. `strategy_runner.py` — 13개 내부 클로저 → 모듈 수준 함수

**문제**  
`_run_once()` 내부에 `_s1()`, `_s3()`, ..., `_s15()` 가 중첩 정의 (약 300줄). 단위 테스트 불가, 클로저 캡처 버그 위험.

**수정 계획**  
각 클로저를 모듈 수준 `async def _run_s1(rdb)` 함수로 격상. 공통 에러 래퍼 도입:

```python
# strategy_runner.py

async def _guarded(name: str, coro):
    """전략 실행 실패를 격리. 예외는 로그만 남기고 다른 전략에 영향 없음."""
    try:
        await coro
    except Exception as exc:
        logger.warning("[Scanner] %s 실패: %s", name, exc)

async def _run_s1(rdb):
    for market in MARKETS:
        items = await rdb.lrange(f"candidates:s1:{market}", 0, -1)
        # ... 기존 로직 ...

async def _run_once(rdb):
    tasks = [
        _guarded("S1",  _run_s1(rdb)),
        _guarded("S3",  _run_s3(rdb)),
        # ...
    ]
    await asyncio.gather(*tasks)
```

---

### H-5. `analyzer.py` `_build_user_message()` — 15분기 → 전략 템플릿 dict

**문제**  
`analyzer.py:_build_user_message()` 가 15개 `if/elif` 분기로 각 전략별 프롬프트를 구성 (~150줄). 새 전략 추가 시 이 함수도 수정 필요 (OCP 위반).

**수정 계획**  
전략별 프롬프트 빌더를 dict로 분리:

```python
# analyzer.py

_STRATEGY_PROMPTS: dict[str, Callable[[dict], str]] = {
    "S1_GAP_OPEN":   _build_s1_prompt,
    "S2_VI_PULLBACK": _build_s2_prompt,
    # ...
}

def _build_user_message(signal: dict, news_ctx: str) -> str:
    strategy = signal.get("strategy", "")
    builder  = _STRATEGY_PROMPTS.get(strategy, _build_default_prompt)
    return builder(signal) + (f"\n\n뉴스 컨텍스트:\n{news_ctx}" if news_ctx else "")
```

---

### H-6. `CandidateService.java` legacy `getCandidates()` / `getAllCandidates()` 제거

**문제**  
구형 키 `candidates:001`, `candidates:101` 를 읽는 `getCandidates()`, `getAllCandidates()` 메서드가 여전히 존재하며 `TradingScheduler.java` 에서 호출 중. CLAUDE.md에서 "점진적 제거 중"으로 표시.

**수정 계획**  
1. `TradingScheduler.java` 에서 `getCandidates()` 호출 → 전략별 `getS{N}Candidates()` 로 교체
2. `CandidateService.java` 에서 두 메서드 삭제
3. `parseSignedInt()` private helper도 `Integer.parseInt(s.replace("+", ""))` 인라인으로 교체 (단일 호출처)

---

## MEDIUM — 다음 스프린트

### M-1. `engine.py` `_run_health_server()` → 별도 `health_server.py`

**문제**  
280줄 engine.py 의 절반(68~160줄)이 HTTP 서버 로직. 4개 라우트 핸들러가 main 모듈에 내장.

**수정**  
`ai-engine/health_server.py` 생성, `_run_health_server` 이전. `engine.py` 는 `from health_server import run_health_server` 만 import.

---

### M-2. `scorer.py` `_time_bonus()` → `strategy_meta.py` 이동

**문제**  
`_time_bonus()` 가 `scorer.py` 내부에 있지만 시간별 전략 분류(`_SWING_STRATEGIES`, `_MIDDAY_STRATEGIES` 등) 는 `strategy_runner.py` 에도 있어 중복.

**수정**  
`ai-engine/strategy_meta.py` 신규:
```python
# strategy_meta.py
SWING_STRATEGIES   = {"S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S10_NEW_HIGH",
                      "S11_FRGN_CONT", "S13_BOX_BREAKOUT", "S14_OVERSOLD_BOUNCE",
                      "S15_MOMENTUM_ALIGN"}
DAY_STRATEGIES     = {"S1_GAP_OPEN", "S3_INST_FRGN", "S4_BIG_CANDLE",
                      "S5_PROG_FRGN", "S6_THEME_LAGGARD", "S7_AUCTION"}
MIDDAY_STRATEGIES  = {"S12_CLOSING"}

CLAUDE_THRESHOLDS = {
    "S10_NEW_HIGH": 65.0,
    # ...
    "_DEFAULT": 60.0,
}

def get_threshold(strategy: str) -> float:
    return CLAUDE_THRESHOLDS.get(strategy, CLAUDE_THRESHOLDS["_DEFAULT"])
```

`scorer.py`, `strategy_runner.py` 모두 여기서 import.

---

### M-3. `TradingScheduler.java` — 08:30 cron 충돌 해소

**문제**  
`preMarketNewsBrief()` 와 `preloadAuctionCandidates()` 가 모두 `@Scheduled(cron = "0 30 8 * * MON-FRI")`. Spring `@Scheduled` 은 단일 스레드 풀 기본값이므로 실행 순서 보장 안됨.

**수정**  
```java
// Before
@Scheduled(cron = "0 30 8 * * MON-FRI")
public void preMarketNewsBrief() { ... }

@Scheduled(cron = "0 30 8 * * MON-FRI")
public void preloadAuctionCandidates() { ... }

// After — 1분 차이
@Scheduled(cron = "0 28 8 * * MON-FRI")
public void preMarketNewsBrief() { ... }

@Scheduled(cron = "0 30 8 * * MON-FRI")
public void preloadAuctionCandidates() { ... }
```

---

### M-4. `redis_reader.py` Confirm Gate 함수 → 조건부 import

**문제**  
`redis_reader.py:120~158` 에 `push_human_confirm_queue()`, `pop_confirmed_queue()`, `push_confirmed_queue()` 가 항상 로드됨. ENABLE_CONFIRM_GATE=false 시 완전 사용 안 됨.

**수정**  
`confirm_gate_redis.py` 로 분리. `confirm_worker.py` 에서만 import. `redis_reader.py` 에서 제거.

---

### M-5. `queue_worker.py` — R:R 계산 인라인 제거

**문제**  
`queue_worker.py` 내부에서 직접 R:R 계산을 수행하는 코드가 있음. `tp_sl_engine.py` 와 중복.

**수정**  
`from tp_sl_engine import compute_rr` import 후 기존 인라인 계산 제거.

---

### M-6. `formatter.js` R:R 중복 계산 — `_effectiveRR` 단일화

**문제**  
`formatter.js` 의 `formatSignal()` 과 `formatSellSignal()` 에서 각각 R:R 계산 코드가 중복. `_effectiveRR()` 헬퍼가 정의되어 있으나 두 함수 모두 서로 다른 방식으로 R:R을 추가 계산.

**수정**  
`_effectiveRR()` 를 유일한 R:R 계산 경로로 지정, 모든 formatter 함수에서 이를 통해서만 R:R 표시.

---

### M-7. `TradingScheduler.java` — `buildTodayEventLine()` 인라인 빌더 → `MessageBuilder` 유틸

**문제**  
`TradingScheduler.java` 내부에 `StringBuilder` 를 이용한 메시지 조립 코드가 스케줄러 로직과 혼재. `saveMarketDailyContextMorning()` 같은 메서드가 mini-repository 역할 겸임.

**수정**  
`MarketMessageBuilder.java` 유틸 클래스 분리:
```java
public class MarketMessageBuilder {
    public static String buildPreMarketBrief(MarketContext ctx) { ... }
    public static String buildMiddayReport(MarketContext ctx) { ... }
}
```

---

### M-8. `candidates_builder.py` — `_post_with_retry()` 제거, `http_utils` 위임

**문제**  
`candidates_builder.py` 에 자체 `_post_with_retry()` 헬퍼가 있어 `http_utils.py` 의 `kiwoom_client()` + rate limiter 를 우회.

**수정**  
`candidates_builder.py` 에서 `_post_with_retry` 제거, `http_utils.kiwoom_client()` context manager 사용으로 교체. Rate limiter 자동 적용됨.

---

## LOW — 코드 품질·관례

### L-1. 모든 Python 모듈 `from __future__ import annotations` 통일

`db_writer.py` 에는 있고 `scorer.py`, `analyzer.py`, `queue_worker.py` 에는 없음. Python 3.10+ 호환성을 위해 모든 모듈에 추가.

### L-2. `RedisMarketDataService.java` — `java.time.LocalDate.now()` inline 제거

`incrementDailySignalCount()` 내부의 `java.time.LocalDate.now()` 를 static import 사용 또는 메서드 상단 변수로 분리.

### L-3. `signals.js` — `console.error/log` → `logger` 통일

`signals.js` 전체에서 `console.error()`, `console.log()` 호출이 `logger.error()`, `logger.info()` 와 혼재. CLAUDE.md 원칙: `console.log()` 직접 사용 금지.

```javascript
// Before
console.error('[Signals] 오류:', err);

// After
logger.error({ err: err.message }, '[Signals] 오류');
```

### L-4. `getAvgCntrStrength()` 명칭 일관성

`RedisMarketDataService.java:54` — `getAvgCntrStrength()` 는 buy/sell 비율이 아닌 체결강도 평균. `redis_reader.py` 의 `get_hoga_ratio()` 는 sell/buy 비율. 두 함수의 분자/분모가 반대이므로 주석으로 명확히 문서화.

### L-5. `engine.py` 환경변수 enable flags — `_bool_env()` 헬퍼 추출

```python
# Before (engine.py 에서 반복)
enable_confirm = os.getenv("ENABLE_CONFIRM_GATE", "false").lower() == "true"
enable_scanner = os.getenv("ENABLE_STRATEGY_SCANNER", "true").lower() == "true"

# After
def _bool_env(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() == "true"

enable_confirm = _bool_env("ENABLE_CONFIRM_GATE", False)
enable_scanner = _bool_env("ENABLE_STRATEGY_SCANNER", True)
```

---

## 실행 순서 (의존성 고려)

```
Phase 1 (Critical — 독립 작업, 병렬 가능)
  C-1: utils.py 생성 + 4개 파일 float parser 교체
  C-2: config.py 확장 + engine.py/http_utils.py/candidates_builder.py 교체
  C-3: db_writer.py import 정리
  C-4: confirmGate.js 분리

Phase 2 (High — C 완료 후)
  H-1: CandidateService.java 템플릿화 (Java)
  H-2 + H-3: signals.js dispatch table + formatNewsAlert 이동 (Node.js)  ← 같이
  H-4: strategy_runner.py 클로저 → 모듈 수준 (Python)
  H-5: analyzer.py 프롬프트 dict 분리 (Python)
  H-6: legacy getCandidates() 제거 (Java) — H-1 완료 후

Phase 3 (Medium — 독립적, 순서 무관)
  M-1: health_server.py 분리
  M-2: strategy_meta.py 신규
  M-3: TradingScheduler cron 충돌 해소
  M-4: confirm gate redis 분리
  M-5: queue_worker R:R 위임
  M-6: formatter R:R 단일화
  M-7: MarketMessageBuilder 분리
  M-8: candidates_builder http_utils 위임

Phase 4 (Low — 마지막)
  L-1 ~ L-5: 스타일·관례 정리
```

---

## 변경 영향도 매트릭스

| 파일 | Phase | 변경 규모 | 테스트 방법 |
|------|-------|-----------|------------|
| `ai-engine/utils.py` (신규) | 1 | - | `pytest utils.py` |
| `ai-engine/config.py` | 1 | 소 (13→60줄) | import 확인 |
| `ai-engine/db_writer.py` | 1 | 극소 (2줄) | 기존 동작 동일 |
| `ai-engine/scorer.py` | 1,2 | 소 | Docker 로그 점수 비교 |
| `ai-engine/candidates_builder.py` | 1,3 | 중 | `/candidates` API 확인 |
| `ai-engine/strategy_runner.py` | 2 | 대 (370→200줄) | 전략 스캔 로그 확인 |
| `ai-engine/analyzer.py` | 2 | 중 | 신호 처리 후 ai_reason 확인 |
| `api-orchestrator/CandidateService.java` | 2 | 대 (679→200줄) | `/candidates` Redis 키 확인 |
| `api-orchestrator/TradingScheduler.java` | 2,3 | 중 | cron 08:30 로그 순서 확인 |
| `telegram-bot/src/handlers/signals.js` | 1,2 | 대 (540→250줄) | 신호 수신 후 Telegram 메시지 확인 |
| `telegram-bot/src/utils/formatter.js` | 2,3 | 소 | 포맷 메시지 시각 확인 |

---

## 롤백 전략

각 Phase 는 독립 PR. 롤백 단위 = PR 단위 revert.
- Phase 1, 2 는 기능 변경 없으므로 redis 큐 재처리 테스트로 충분
- `CandidateService.java` 변경 시 Redis key 패턴 불변 확인 필수 (`candidates:s{N}:{market}` 유지)
- `signals.js` dispatch table 도입 전 타입 목록 전수 검증 필요 (`PAUSE_CONFIRM_REQUEST` 등 미등록 타입 확인)
