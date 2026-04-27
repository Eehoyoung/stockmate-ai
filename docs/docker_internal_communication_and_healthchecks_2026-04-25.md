# Docker Internal Communication And Healthchecks

## 목적

이 문서는 `stockmate-ai`의 도커 내부 통신 구조와 서비스 간 의존성, 실제 데이터 플로우, 그리고 2026-04-25 기준 healthcheck/readiness 보강 사항을 운영 관점에서 정리한다.

핵심 목표는 다음과 같다.

- 서비스 간 내부 통신 주소 체계를 고정한다.
- 컨테이너 시작 순서를 `process started`가 아니라 `service healthy` 기준으로 맞춘다.
- 장애 발생 시 어떤 경로를 먼저 확인해야 하는지 빠르게 판단할 수 있게 한다.

## 네트워크 구조

모든 서비스는 compose 기본 브리지 네트워크 `stockmate-ai_default` 위에서 통신한다.

서비스명은 내부 DNS 호스트명으로 그대로 사용한다.

- `redis`
- `postgres`
- `api-orchestrator`
- `ai-engine`
- `websocket-listener`
- `telegram-bot`

즉, 컨테이너 내부에서는 `localhost`가 아니라 아래와 같이 접근한다.

- Redis: `redis:6379`
- Postgres: `postgres:5432`
- API: `http://api-orchestrator:8080`
- AI Engine: `http://ai-engine:8082`

## 서비스별 내부 의존성

### 1. api-orchestrator

역할:

- Spring Boot API
- Flyway 마이그레이션
- Redis 기반 시장데이터/큐 활용
- Postgres 원장 관리

내부 의존:

- `postgres:5432`
- `redis:6379`

readiness 기준:

- `/actuator/health`가 `200 OK`

### 2. ai-engine

역할:

- `telegram_queue` 소비
- Redis 시장데이터 조회
- AI 분석/전략 스캐닝
- Postgres 결과 기록
- `ai_scored_queue` 발행
- `/health`, `/candidates`, `/analyze/{stk_cd}`, `/score/{stk_cd}`, `/news/brief` 제공

내부 의존:

- `redis:6379`
- `postgres:5432`
- `http://api-orchestrator:8080`

readiness 기준:

- `http://127.0.0.1:8082/health`

### 3. websocket-listener

역할:

- 외부 키움 WebSocket 수신
- Redis에 `ws:tick:*`, `ws:hoga:*`, `ws:expected:*` 기록
- Postgres 이벤트 직접 적재
- `/health` 제공

내부 의존:

- `redis:6379`
- `postgres:5432`
- 운영 정책상 `api-orchestrator` healthy 이후 시작

readiness 기준:

- `http://127.0.0.1:8081/health`

### 4. telegram-bot

역할:

- `ai_scored_queue` 소비
- 사용자 명령 처리
- `api-orchestrator`, `ai-engine`, Redis, Postgres를 함께 사용하는 운영 진입점

내부 의존:

- `redis:6379`
- `postgres:5432`
- `http://api-orchestrator:8080`
- `http://ai-engine:8082`

readiness 기준:

- Redis ping
- Postgres `SELECT 1`
- `api-orchestrator /actuator/health`
- `ai-engine /health`

위 4개가 모두 성공해야 healthy 처리된다.

## 실제 데이터 플로우

### A. 시장데이터 플로우

1. `websocket-listener`
2. Redis:
   - `ws:tick:{stk_cd}`
   - `ws:hoga:{stk_cd}`
   - `ws:expected:{stk_cd}`
3. `api-orchestrator` / `ai-engine`가 Redis 데이터 소비
4. 일부 이벤트는 Postgres에도 직접 적재

### B. 신호 생성 및 분석 플로우

1. `api-orchestrator` 또는 `ai-engine strategy_runner`
2. Redis `telegram_queue` 적재
3. `ai-engine queue_worker` 소비
4. 점수화 / AI 분석 / TP-SL 계산
5. Postgres `trading_signals` 저장
6. Redis `ai_scored_queue` 적재
7. `telegram-bot` 소비 및 알림 발송

### C. 포지션 모니터링 플로우

1. `ai-engine position_monitor`
2. Redis `ws:tick:*`, `ws:hoga:*` 조회
3. Postgres `trading_signals`, `trade_plans`, `position_state_events`, `trade_outcomes` 갱신
4. 필요 시 Redis `ai_scored_queue`에 `SELL_SIGNAL` 발행
5. `telegram-bot` 전송

### D. 보조 HTTP 플로우

`telegram-bot` → `api-orchestrator`

- `/api/trading/health`
- `/api/trading/candidates`
- `/api/trading/score/{stkCd}`
- `/api/trading/monitor/health`

`telegram-bot` → `ai-engine`

- `/health`
- `/candidates`
- `/analyze/{stk_cd}`
- `/score/{stk_cd}`
- `/news/brief`

## 2026-04-25 보강 사항

### 1. healthcheck 추가

추가 대상:

- `api-orchestrator`
- `ai-engine`
- `websocket-listener`
- `telegram-bot`

현 상태:

- `api-orchestrator`: healthy
- `ai-engine`: healthy
- `websocket-listener`: healthy
- `telegram-bot`: healthy

### 2. depends_on 강화

기존 일부 서비스는 `service_started`만 사용했다.

이 방식은 프로세스가 뜬 직후에도 애플리케이션 준비가 안 된 상태일 수 있어서 race condition이 발생할 수 있다.

현재는 아래 기준으로 정리했다.

- `ai-engine` → `api-orchestrator`, `postgres`, `redis` 모두 `service_healthy`
- `websocket-listener` → `api-orchestrator`, `postgres`, `redis` 모두 `service_healthy`
- `telegram-bot` → `api-orchestrator`, `ai-engine`, `postgres`, `redis` 모두 `service_healthy`

### 3. api-orchestrator Dockerfile 보강

`api-orchestrator`는 런타임 이미지에 `curl`이 없어서 Docker healthcheck를 수행할 수 없었다.

따라서 Dockerfile에 `curl` 설치를 추가했다.

## 운영 점검 절차

### 1차 확인

```powershell
docker compose ps
```

확인 기준:

- `postgres`, `redis`는 `healthy`
- `api-orchestrator`, `ai-engine`, `websocket-listener`, `telegram-bot`도 `healthy`

### 2차 확인

```powershell
docker inspect --format "{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}" `
  stockmate-ai-api-orchestrator-1 `
  stockmate-ai-ai-engine-1 `
  stockmate-ai-websocket-listener-1 `
  stockmate-ai-telegram-bot-1
```

### 3차 확인

```powershell
docker compose logs --tail=100 api-orchestrator ai-engine websocket-listener telegram-bot
```

로그에서 우선 확인할 키워드:

- `healthy`
- `Redis connected`
- `PostgreSQL pool created`
- `Started ApiOrchestratorApplication`
- `AI Engine health server started`
- `WebSocket Listener start`
- `Telegram Bot start`

## 장애 시 우선 판단 기준

### 케이스 1. telegram-bot만 unhealthy

우선 확인:

1. `redis:6379`
2. `postgres:5432`
3. `api-orchestrator /actuator/health`
4. `ai-engine /health`

현재 bot healthcheck가 이 네 가지를 모두 점검하므로, 봇이 unhealthy면 대개 bot 자체 문제보다는 upstream 의존 중 하나가 깨졌을 가능성이 높다.

### 케이스 2. ai-engine unhealthy

우선 확인:

1. Redis 접속
2. Postgres 접속
3. Claude API 키/외부 API 오류
4. `/health` 응답 지연

### 케이스 3. websocket-listener unhealthy

우선 확인:

1. Redis 접속
2. Postgres 접속
3. 외부 키움 WS 연결 상태

### 케이스 4. api-orchestrator unhealthy

우선 확인:

1. Flyway 마이그레이션 실패 여부
2. Postgres 세션 생성 여부
3. Redis 연결 설정
4. `/actuator/health` 응답 지연

## 현재 판단

2026-04-25 기준, 도커 내부 통신 구조는 다음 조건을 만족한다.

- 서비스명 기반 내부 DNS가 일관되다.
- 실제 내부 HTTP/TCP 연결이 정상 확인되었다.
- 핵심 서비스 전부가 health 기반 readiness를 갖는다.
- 주요 소비자 서비스는 upstream healthy 이후에만 시작한다.

즉, 현재 구성은 단순 실행 기준이 아니라 운영 기준에서도 충분히 방어적인 구조로 올라왔다.

## 후속 개선 후보

1. `docker compose config` 기준으로 불필요한 `.env` 전체 주입 축소
2. 서비스별 healthcheck 실패 원인을 더 짧게 식별할 수 있도록 운영 스크립트 추가
3. `/health` 응답에 upstream dependency 상세 상태를 더 노출
4. 장애 복구용 `make health` 또는 PowerShell 점검 스크립트 추가
