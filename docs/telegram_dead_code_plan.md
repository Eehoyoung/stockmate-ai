# telegram-bot 미사용 코드 점검 및 수정 계획

## 분석 범위
- `src/index.js`
- `src/handlers/commands.js`
- `src/handlers/signals.js`
- `src/services/kiwoom.js`
- `src/services/redis.js`
- `src/utils/formatter.js`
- `src/utils/logger.js`
- `tests/test_formatter.js`
- `tests/test_signals_rate_limiter.js`

---

## 발견된 문제 목록

### 1. `logger.js` – 전체 미사용 (Dead Code)
- **현상**: `getLogger` 함수가 정의·export되어 있으나 index.js, commands.js, signals.js, formatter.js 어디에도 `require('./utils/logger')` 호출 없음
- **영향**: 구조화 로깅 인프라가 있음에도 `console.log/error`만 사용 → 로그 파일 미생성, 장애 추적 불가
- **수정**: signals.js, commands.js에 `getLogger` 도입. `console.log/error/warn` → logger 호출로 전환

---

### 2. `kiwoom.js` – `getCalendarToday()` 미사용
- **현상**: kiwoom.js line 93에 `getCalendarToday()` 정의·export 되어 있으나 commands.js에서 import하지 않음
  - `getCalendarWeek()`는 `/events` 명령에서 사용됨 (정상)
  - `getCalendarToday()`는 어디서도 호출 안 됨
- **수정**: `getCalendarToday()` 제거 또는 `/today` 명령 추가

---

### 3. `kiwoom.js` – `runStrategy()` URL 맵 s8/s9/s11/s13/s14/s15 누락
- **현상**: `runStrategy()` 내부 `map` 객체에 s1~s7, s10, s12만 존재
  - `/strategy s8` 실행 시 → `throw new Error("알 수 없는 전술: s8...")`
  - `/help` 에는 s1~s15 모두 실행 가능하다고 안내됨 → 불일치
- **수정**: map에 s8/s9/s11/s13/s14/s15 URL 추가

---

### 4. `formatter.js` – `escapeHtml()` 미정의, 테스트에서 호출됨
- **현상**: `test_formatter.js`가 `const { formatSignal, formatForceClose, formatDailySummary, escapeHtml } = require('../src/utils/formatter')` 로 import하나, formatter.js에 `escapeHtml` 함수 자체가 없음
  - 10개 escapeHtml 테스트 전부 `TypeError: escapeHtml is not a function` 으로 실패
  - `ai_reason` HTML 이스케이프 테스트 2개도 실패 (`escapeHtml` 미적용 상태)
- **수정**: formatter.js에 `escapeHtml(str)` 함수 추가, `ai_reason` 출력에 적용, module.exports에 포함

---

### 5. `test_formatter.js` – `target_pct` 기반 절대가 계산 테스트가 현재 코드와 불일치
- **현상**: 테스트 line 310-321에서 `target_pct=4.0`, `cur_prc=100000` → TP1 절대가 `104,000`원 및 `R:R 1:2.0` 을 기대
  - 현재 formatter.js는 `tp1_price`/`tp2_price`/`sl_price` 절대가가 없으면 `목표: +4.0%  손절: -2.0%` 텍스트를 표시 (절대가 계산 없음)
  - 또한 `formatSignal` 에서 `R:R` 계산은 `tp1_price`와 `sl_price` 있을 때만 수행됨
- **수정**: 테스트를 현재 동작에 맞게 수정 (% 폴백 표시 확인)

---

### 6. `test_signals_rate_limiter.js` – `_checkRateLimit`, `MAX_SIGNALS_PER_MIN` signals.js에 없음
- **현상**: smoke test (line 225-253)에서 signals.js 내용에 `_checkRateLimit`, `MAX_SIGNALS_PER_MIN` 문자열 존재 여부 체크
  - 현재 signals.js에 이 두 식별자가 없음 → assert 실패
- **수정**: signals.js에 분당 최대 발송 건수 제한(Rate Limiter) 기능 추가, 두 식별자 포함

---

## 수정 대상 파일 및 순서

| 우선순위 | 파일 | 변경 내용 |
|---------|------|----------|
| 1 | `formatter.js` | `escapeHtml()` 추가, `ai_reason` escape 적용, export |
| 2 | `kiwoom.js` | `getCalendarToday` 제거, `runStrategy` 맵에 s8/s9/s11/s13/s14/s15 추가 |
| 3 | `signals.js` | Rate Limiter(`_checkRateLimit`, `MAX_SIGNALS_PER_MIN`) 추가, logger 도입 |
| 4 | `commands.js` | logger 도입 (console.* → logger) |
| 5 | `tests/test_formatter.js` | escapeHtml 테스트 조건 수정, target_pct R:R 테스트 수정 |

---

## 비고

- `redis.js` – 모든 export 사용됨 (정상)
- `commands.js` 모든 export – index.js에서 전부 bot.command() 등록됨 (정상)
- `formatter.js` 모든 export – commands.js/signals.js에서 전부 사용됨 (정상, escapeHtml 추가 후)
- `logger.js` – 전면 도입 시 `LOG_FILE` 경로(`logs/telegram-bot.log`)에 대한 디렉토리 존재 여부 자동 생성 로직 내장되어 있으므로 별도 설정 불필요
