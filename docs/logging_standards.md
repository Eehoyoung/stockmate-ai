# StockMate AI – 로깅 표준 (Logging Standards)

> **DoD**: 장애 1건 추적 시 4개 모듈(`websocket-listener` / `api-orchestrator` / `ai-engine` / `telegram-bot`) 상관 조회 5분 내 완료 가능.

---

## 1. JSON Lines 로그 공통 스키마

모든 모듈은 **1줄 = 1 JSON 객체** 형식으로 로그를 출력합니다.

```jsonc
{
  "ts":         "2026-03-24T09:53:00.123+09:00",  // KST ISO-8601, ms 단위 (필수)
  "level":      "INFO",                            // 레벨 (필수, 하단 기준 참조)
  "service":    "websocket-listener",              // 서비스 이름 (필수)
  "module":     "ws_client",                       // 모듈/클래스명 (필수)
  "request_id": "req-uuid-1234",                  // 요청 추적 ID (해당 시 필수)
  "signal_id":  "sig-uuid-5678",                  // 신호 추적 ID (해당 시 필수)
  "stk_cd":     "005930",                         // 종목 코드 (해당 시)
  "error_code": "KIWOOM_1700",                    // 오류 코드 (에러 시, error_codes.md 참조)
  "msg":        "Rate limit 초과 – 1초 대기 후 재시도", // 메시지 (필수)
  "exc":        "Traceback ..."                    // 스택트레이스 (예외 시)
}
```

### 1.1 추적 키 규칙 (request_id / signal_id)

| 키 | 생성 주체 | 전달 방향 | 형식 |
|----|----------|-----------|------|
| `request_id` | api-orchestrator (REST 요청 진입점) | → ai-engine → telegram-bot | `req-{UUIDv4}` |
| `signal_id`  | ai-engine (신호 생성 시점) | → telegram-bot → Redis 큐 payload | `sig-{UUIDv4}` |

- **websocket-listener**: 개별 틱 처리는 `request_id` 불필요. WS 연결 이벤트에만 `request_id` 부여.
- **api-orchestrator**: HTTP 요청 수신 시 MDC에 `request_id` 설정, 응답 반환 전 제거.
- **ai-engine**: 신호 생성 시 `signal_id` 생성, 이후 모든 처리 단계에 포함.
- **telegram-bot**: Redis 큐에서 꺼낸 payload의 `signal_id`를 로그에 포함.

---

## 2. 장애 레벨 분류 기준

### 2.1 레벨 정의

| 레벨 | 코드 | 의미 | 즉각 대응 필요 | 예시 |
|------|------|------|---------------|------|
| **DEBUG** | 10 | 개발/디버깅 전용. 운영 환경 비활성화 | ❌ | PING 송수신, 메시지 파싱 세부 |
| **INFO** | 20 | 정상 운영 흐름 기록 | ❌ | 연결 성공, 신호 생성, 메시지 발송 |
| **WARNING** | 30 | 비정상이지만 자동 복구 가능한 상황 | ❌ (모니터링) | Rate Limit, 일시적 연결 끊김, 재연결 시도 |
| **ERROR** | 40 | 기능 일부 실패. 자동 복구 불확실 | ✅ (15분 내) | 토큰 갱신 실패, 메시지 전송 실패, 스키마 오류 |
| **CRITICAL** | 50 | 시스템 전체 또는 핵심 기능 중단 위험 | ✅ (즉시, 5분 내) | Redis 연결 불가, 자격증명 만료, 프로세스 종료 |

### 2.2 레벨 판단 기준 (모듈별)

#### websocket-listener

| 상황 | 레벨 |
|------|------|
| WS 연결 성공 / LOGIN 성공 | INFO |
| 종목 구독 REG/UNREG 완료 | INFO |
| 재연결 시도 (1~10회) | WARNING |
| ConnectionClosed 수신 | WARNING |
| LOGIN 실패 / 응답 타임아웃 | ERROR |
| 네트워크 OSError | ERROR |
| 최대 재연결 초과 (장 중) | WARNING (5분 대기 후 재시도) |
| Redis 초기 연결 실패 → 프로세스 종료 | CRITICAL |
| 토큰 로드 완전 실패 | CRITICAL |

#### api-orchestrator

| 상황 | 레벨 |
|------|------|
| API 호출 성공 | INFO |
| Rate Limit (1700) | WARNING |
| 종목 없음 (1902) | WARNING |
| 필수 파라미터 오류 | ERROR |
| 토큰 유효하지 않음 (8005) | ERROR → 즉시 갱신 |
| App Key/Secret 검증 실패 (8001/8002) | CRITICAL |
| IP 불일치 (8010) | CRITICAL |
| 투자구분 불일치 (8030/8031) | CRITICAL |

#### ai-engine

| 상황 | 레벨 |
|------|------|
| 신호 생성 / 점수화 완료 | INFO |
| Claude API 응답 파싱 이상 | WARNING |
| Claude API 타임아웃 (재시도 예정) | WARNING |
| 전략 실행 예외 (단일 전략) | ERROR |
| Claude API 완전 실패 (재시도 소진) | ERROR |
| Redis 큐 읽기 실패 | ERROR |

#### telegram-bot

| 상황 | 레벨 |
|------|------|
| 신호 발송 성공 | INFO |
| 미인가 접근 차단 | WARNING |
| 텔레그램 Rate Limit | WARNING |
| 메시지 전송 실패 | ERROR |
| TELEGRAM_BOT_TOKEN 미설정 → 프로세스 종료 | CRITICAL |

---

## 3. 로그 파일 위치 규칙

| 서비스 | 로그 파일 | 롤링 정책 |
|--------|----------|-----------|
| websocket-listener | `logs/websocket-listener.log` | 수동 (logrotate 권장) |
| api-orchestrator | `logs/api-orchestrator.log` | 일별 롤링, 30일 보관 |
| ai-engine | `logs/ai-engine.log` | 수동 (logrotate 권장) |
| telegram-bot | `logs/telegram-bot.log` | 수동 (logrotate 권장) |

---

## 4. 상관 조회 방법 (5분 내 완료 기준)

### Step 1 — 장애 시각 특정 (1분)
```bash
# 최근 ERROR/CRITICAL 전체 조회
jq -r 'select(.level == "ERROR" or .level == "CRITICAL") | "\(.ts) [\(.service)] \(.error_code // "-") \(.msg)"' \
  logs/websocket-listener.log logs/api-orchestrator.log \
  logs/ai-engine.log logs/telegram-bot.log | sort | tail -50
```

### Step 2 — request_id / signal_id 로 전파 경로 추적 (2분)
```bash
# signal_id 기준 전체 모듈 추적
SIG="sig-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
jq -r "select(.signal_id == \"$SIG\")" \
  logs/websocket-listener.log logs/api-orchestrator.log \
  logs/ai-engine.log logs/telegram-bot.log | jq -s 'sort_by(.ts)'
```

### Step 3 — error_code 기준 동일 유형 집계 (2분)
```bash
# 동일 error_code 발생 빈도 집계
jq -r 'select(.error_code) | .error_code' logs/*.log | sort | uniq -c | sort -rn
```

---

## 5. 운영 환경 설정 가이드

| 환경변수 | 기본값 | 설명 |
|---------|--------|------|
| `LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `SERVICE_NAME` | 서비스별 기본값 | JSON 로그의 `service` 필드 값 |
| `LOG_FILE` | `logs/{service}.log` | 파일 출력 경로 (telegram-bot) |

---

## 6. 금지 사항

- ❌ `print()` / `console.log()` 직접 사용 — 반드시 logger 모듈 경유
- ❌ 비밀키·토큰·패스워드를 로그 메시지에 포함
- ❌ 한 줄에 JSON 객체 2개 이상 출력 (멀티라인 JSON 금지)
- ❌ 운영 환경에서 DEBUG 레벨 전체 활성화

---

*최종 수정: 2026-03-24 | 관리: Phase A1-4*
