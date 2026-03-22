# SMA (StockMate AI) 사용설명서

**버전**: 1.0.0
**작성일**: 2026-03-21
**대상**: 키움 API를 이용한 한국 주식 단기 매매 자동화 시스템 사용자

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [설치 및 환경 설정](#2-설치-및-환경-설정)
3. [7가지 매매 전략 상세 설명](#3-7가지-매매-전략-상세-설명)
4. [AI 스코어링 시스템](#4-ai-스코어링-시스템)
5. [Telegram Bot 사용법](#5-telegram-bot-사용법)
6. [실전 매매 가이드](#6-실전-매매-가이드)
7. [시스템 모니터링 및 운영](#7-시스템-모니터링-및-운영)
8. [고급 설정](#8-고급-설정)
9. [개발자 가이드](#9-개발자-가이드)
10. [법적 고지 및 면책사항](#10-법적-고지-및-면책사항)

---

## 1. 시스템 개요

### 1.1 SMA란?

**SMA (StockMate AI)**는 한국 주식 시장에 특화된 자동화 매매 신호 생성 시스템입니다. 키움증권 REST API 및 WebSocket API를 통해 실시간 시세 데이터를 수집하고, 7가지 독립적인 매매 전략을 동시에 실행하여 진입 신호를 탐지합니다. 탐지된 신호는 Claude AI(Anthropic)의 자연어 분석을 거쳐 최종 점수화되며, Telegram을 통해 사용자에게 실시간으로 전달됩니다.

SMA는 완전 자동화 매매 시스템이 아닙니다. SMA는 **매매 신호 추천 시스템**입니다. 최종 매매 결정은 항상 사용자가 직접 내립니다.

#### 주요 특징

- **실시간 신호**: 키움 WebSocket(0B 체결, 0H 예상체결, 0D 호가, 1h VI 이벤트)을 통한 밀리초 단위 데이터 수신
- **7가지 전략**: 갭상승, VI 눌림목, 기관/외인 순매수, 장대양봉, 프로그램매수, 테마모멘텀, 장전동시호가
- **이중 필터**: 규칙 기반 1차 스코어링 + Claude AI 2차 분석으로 오신호 최소화
- **비용 최적화**: 규칙 점수 미달 신호는 Claude API 호출 없이 자동 제거 (API 비용 절감)
- **Telegram 실시간 알림**: 모바일에서 즉시 신호 수신 및 명령어 기반 시스템 제어

### 1.2 핵심 가치 제안 (왜 SMA를 써야 하는가)

#### 기존 방법의 한계

| 항목 | 기존 수동 매매 | HTS/MTS 조건검색 | SMA |
|------|--------------|----------------|-----|
| 모니터링 범위 | 1~5개 종목 | 조건 설정된 종목 | KOSPI+KOSDAQ 전체 |
| 신호 속도 | 느림 (인간 반응) | 빠름 | 빠름 (WebSocket) |
| 전략 다양성 | 제한적 | 단일 조건 위주 | 7가지 복합 전략 |
| AI 분석 | 없음 | 없음 | Claude AI 정성 분석 |
| 리스크 평가 | 주관적 | 없음 | 규칙+AI 이중 평가 |
| 실시간 알림 | 없음 | 제한적 | Telegram 즉시 발송 |

#### SMA의 핵심 장점

1. **시장 전체 감시**: 단 한 명이 KOSPI·KOSDAQ 2,500개 이상의 종목을 동시에 모니터링할 수 있습니다.
2. **객관적 신호**: 감정 없는 규칙 기반 필터가 1차 스크리닝을 수행합니다.
3. **AI 정성 분석**: Claude AI가 시장 맥락을 고려하여 진입 적합성을 판단합니다.
4. **시간 절약**: 장 중 화면을 계속 보지 않아도 신호를 놓치지 않습니다.
5. **투명한 근거**: 모든 신호에 점수 + AI 분석 근거가 첨부됩니다.

### 1.3 시스템 아키텍처 전체 흐름도

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SMA (StockMate AI) Architecture                    │
└─────────────────────────────────────────────────────────────────────┘

  ┌──────────────────┐
  │  Kiwoom API      │  REST API + WebSocket
  │  (Korean Broker) │  (0B 체결, 0H 예상, 0D 호가, 1h VI)
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────────┐
  │  websocket-listener  │  Python asyncio
  │  (GRP 5–8)          │  - ws_client.py
  │                      │  - redis_writer.py
  │                      │  - health_server.py (:8081)
  └────────┬─────────────┘
           │  Redis HSET: ws:tick:{cd}, ws:hoga:{cd}
           │  Redis HSET: ws:expected:{cd}
           │  Redis LPUSH: vi_watch_queue
           ▼
  ┌────────────────────────────────────────────────────────┐
  │                    Redis (Central Broker)               │
  │                                                        │
  │  Keys:                                                 │
  │    ws:tick:{stk_cd}        ← WebSocket 체결 데이터    │
  │    ws:hoga:{stk_cd}        ← 호가 데이터              │
  │    ws:expected:{stk_cd}    ← 예상체결 데이터          │
  │    ws:strength:{stk_cd}    ← 체결강도 리스트          │
  │    vi:{stk_cd}             ← VI 이벤트 상태           │
  │    kiwoom:token            ← 액세스 토큰              │
  │    candidates:{market}     ← 후보 종목 코드 목록      │
  │                                                        │
  │  Queues:                                               │
  │    vi_watch_queue     ← websocket-listener → Java     │
  │    telegram_queue     ← Java → ai-engine              │
  │    ai_scored_queue    ← ai-engine → telegram-bot      │
  │    error_queue        ← 처리 실패 신호 보관           │
  └──────┬──────────────────────────┬──────────────────────┘
         │                          │
         ▼                          ▼
  ┌─────────────────────┐   ┌──────────────────────────────────┐
  │  api-orchestrator   │   │         ai-engine (Python)        │
  │  (Java Spring Boot) │   │                                   │
  │                     │   │  1. telegram_queue 폴링 (RPOP)    │
  │  Strategies:        │   │  2. rule_score() 1차 스코어링     │
  │  - S1 갭상승        │   │     (scorer.py, 0~100점)          │
  │  - S2 VI 눌림목     │──▶│  3. Claude AI 2차 분석            │
  │  - S3 기관/외인     │   │     (analyzer.py, claude-sonnet)  │
  │  - S4 장대양봉      │   │  4. ai_scored_queue LPUSH         │
  │  - S5 프로그램매수  │   │                                   │
  │  - S6 테마모멘텀    │   │  Health: http://localhost:8082/   │
  │  - S7 동시호가      │   │                                   │
  │                     │   └──────────────┬───────────────────┘
  │  Health: :8080      │                  │
  └─────────────────────┘                  ▼
                                  ┌────────────────────┐
                                  │   telegram-bot     │
                                  │   (Node.js)        │
                                  │                    │
                                  │  ai_scored_queue   │
                                  │  RPOP → 조건 판단  │
                                  │  → Telegram 발송   │
                                  └────────┬───────────┘
                                           │
                                           ▼
                                  ┌────────────────────┐
                                  │  사용자 Telegram   │
                                  │  (모바일/PC)       │
                                  │                    │
                                  │  신호 수신 + 명령어│
                                  └────────────────────┘
```

### 1.4 데이터 흐름 상세 설명

#### Phase 1: 실시간 데이터 수집 (websocket-listener)

키움 WebSocket에서 4가지 데이터 타입을 GRP 5~8을 통해 수신합니다:

- **0B (체결 데이터)**: 현재가, 등락률, 체결강도, 거래량 → `ws:tick:{stk_cd}` HSET
- **0H (예상체결)**: 장전 예상체결가, 예상등락률 → `ws:expected:{stk_cd}` HSET
- **0D (호가잔량)**: 매수/매도 호가 잔량 합계 → `ws:hoga:{stk_cd}` HSET
- **1h (VI 이벤트)**: 정적/동적 VI 발동·해제 → `vi_watch_queue` LPUSH

#### Phase 2: 전략 실행 및 신호 생성 (api-orchestrator)

Java Spring Boot가 스케줄러(`TradingScheduler`)를 통해 주기적으로 전략을 실행합니다:

- 각 전략은 키움 REST API를 호출하여 후보 종목을 탐색
- 조건 충족 종목을 `TradingSignalDto`로 직렬화하여 `telegram_queue`에 LPUSH
- 장전(08:30~09:05): S1, S7 / 장중(09:30~14:30): S2, S3, S4, S5, S6

#### Phase 3: AI 분석 (ai-engine)

Python asyncio 기반으로 `telegram_queue`를 2초 간격으로 폴링합니다:

1. **RPOP**: 신호 하나를 큐에서 꺼냄
2. **특수 타입 처리**: `FORCE_CLOSE`, `DAILY_REPORT`는 AI 없이 바로 전달
3. **1차 스코어링**: `rule_score()` - 전략별 규칙으로 0~100점 산정
4. **임계값 확인**: 전략별 기준 미달 시 CANCEL 처리 (Claude API 비용 0)
5. **2차 분석**: `analyze_signal()` - Claude API 호출로 JSON 응답 획득
6. **결과 발행**: enriched payload를 `ai_scored_queue`에 LPUSH

#### Phase 4: Telegram 발송 (telegram-bot)

Node.js가 `ai_scored_queue`를 폴링하여 조건에 맞는 신호를 발송합니다:

- `action == 'ENTER'` AND `ai_score >= MIN_AI_SCORE(기본 65)`: 발송
- `action == 'HOLD'` AND `ai_score >= 80`: 발송
- `action == 'CANCEL'`: 무시
- 분당 최대 `MAX_SIGNALS_PER_MIN(기본 10)` 건 발송 (Rate Limit)

### 1.5 기술 스택 및 의존성

| 모듈 | 언어/런타임 | 핵심 라이브러리 | 포트 |
|------|-----------|----------------|------|
| api-orchestrator | Java 25, Spring Boot 4.0 | Spring WebFlux, Spring Data Redis, OkHttp | 8080 |
| websocket-listener | Python 3.10+ | websockets 12.0, aiohttp 3.9.5, redis 5.x | 8081 |
| ai-engine | Python 3.10+ | anthropic 0.25.0, redis 5.x, aiohttp | 8082 |
| telegram-bot | Node.js 18+ | Telegraf 4.x, ioredis | - |
| Redis | 7.x | - | 6379 |
| PostgreSQL | 15.x | - | 5432 |

---

## 2. 설치 및 환경 설정

### 2.1 사전 요구사항

#### 소프트웨어 요구사항

```
Python     3.10 이상 (3.12 권장)
Java       21 이상 (25 권장, GraalVM 가능)
Node.js    18 이상 (20 LTS 권장)
Redis      7.0 이상
PostgreSQL 15 이상
Git        최신 버전
```

#### 외부 서비스 계정

1. **키움증권 API 계정**: Open API+ 신청 필요 (키움증권 공식 사이트)
2. **Anthropic Claude API 키**: https://console.anthropic.com 에서 발급
3. **Telegram Bot Token**: BotFather를 통해 발급 (방법은 2.4절 참조)

#### 시스템 리소스 권장 사항

```
CPU: 4코어 이상
RAM: 8GB 이상 (모든 모듈 동시 실행 기준)
SSD: 20GB 이상 (로그, DB 포함)
네트워크: 안정적인 인터넷 연결 (WebSocket 지속 연결 필요)
OS: Linux (Ubuntu 22.04 권장) 또는 Windows 10/11
```

### 2.2 Kiwoom API 계정 설정

#### 키움 Open API+ 신청 절차

1. 키움증권 홈페이지(kiwoom.com) 로그인
2. [Open API] → [Open API+ 신청] 메뉴 접근
3. 이용약관 동의 및 신청서 작성
4. 승인 완료 후 **앱 키(App Key)**와 **앱 시크릿(App Secret)** 발급
5. API 사용 한도 확인 (분당 요청 수, 일별 요청 수)

#### 키움 REST API 주요 엔드포인트

SMA에서 사용하는 키움 API 목록:

| API ID | 설명 | 전략 |
|--------|------|------|
| ka10029 | 예상체결등락률상위 | S1, S7 |
| ka10033 | 거래량순위 | S7 |
| ka10044 | 일별기관매매 | S5 |
| ka10046 | 체결강도추이시간별 | S1, S2 |
| ka10055 | 당일전일체결량 | S3 |
| ka10063 | 장중투자자별매매 | S3 |
| ka10080 | 주식분봉차트 | S4 |
| ka10131 | 기관외국인연속매매 | S3 |
| ka90001 | 테마그룹별상위 | S6 |
| ka90002 | 테마구성종목 | S6 |
| ka90003 | 프로그램순매수상위50 | S5 |
| ka90009 | 외국인기관매매상위 | S5 |

### 2.3 Claude AI API 키 설정

1. https://console.anthropic.com 접속 및 계정 생성
2. [API Keys] → [Create Key] 클릭
3. 키 이름 입력 (예: `sma-production`) 후 생성
4. 생성된 키 복사 (이후 다시 확인 불가)
5. 결제 정보 등록 (Pay-as-you-go 방식)

#### 비용 추정 (claude-sonnet-4 기준)

- 입력: $3 / 1M 토큰
- 출력: $15 / 1M 토큰
- SMA 신호 1건당 약 400~600 토큰 사용
- 일 100회 호출 기준: 약 $0.30~0.50 (월 $9~15)

#### API 사용량 모니터링

SMA는 `claude:daily_calls:{YYYYMMDD}`와 `claude:daily_tokens:{YYYYMMDD}` 키로 Redis에 사용량을 기록합니다. `/상태` Telegram 명령으로 실시간 확인 가능합니다.

### 2.4 Telegram Bot 설정 (BotFather 사용법)

#### 봇 생성 절차

1. Telegram에서 `@BotFather` 검색 및 채팅 시작
2. `/newbot` 명령어 입력
3. 봇 이름 입력 (예: `SMA StockMate AI`)
4. 봇 아이디 입력 (반드시 `bot`으로 끝나야 함, 예: `sma_stockmate_bot`)
5. 발급된 **HTTP API Token** 복사 (형식: `1234567890:AABBccDDeeFF...`)

#### Chat ID 확인 방법

1. 생성된 봇에게 아무 메시지 전송
2. 브라우저에서 다음 URL 접속:
   `https://api.telegram.org/bot{TOKEN}/getUpdates`
3. 응답의 `chat.id` 값 확인 (음수도 가능, 그룹 채팅의 경우)
4. 여러 사용자에게 신호를 보내려면 각 사람의 Chat ID를 쉼표로 구분

#### 봇 명령어 등록 (선택 사항)

BotFather에서 `/setcommands` 입력 후 다음 텍스트 붙여넣기:

```
ping - 봇 동작 확인
help - 명령어 목록
report - 오늘 신호 요약
filter - 전략 필터 설정
```

한국어 명령어는 BotFather에서 직접 등록이 제한될 수 있으므로 봇 코드에서 직접 처리됩니다.

### 2.5 환경 변수 전체 목록

#### api-orchestrator `.env`

```bash
# Kiwoom API
KIWOOM_APP_KEY=your_app_key_here
KIWOOM_APP_SECRET=your_app_secret_here
KIWOOM_BASE_URL=https://api.kiwoom.com
KIWOOM_WS_URL=wss://api.kiwoom.com:10000

# Claude AI
CLAUDE_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-sonnet-4-20250514

# Telegram (알림 전용, 선택)
TELEGRAM_BOT_TOKEN=1234567890:AABBccDDeeFF...
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=SMA
POSTGRES_USER=sma_user
POSTGRES_PASSWORD=your_password

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# 전략 설정
MAX_CLAUDE_CALLS_PER_DAY=100
AI_SCORE_THRESHOLD=60.0
```

#### ai-engine `.env`

```bash
# Claude AI
CLAUDE_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-sonnet-4-20250514

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# 동작 설정
LOG_LEVEL=INFO
POLL_INTERVAL_SEC=2.0
MAX_CLAUDE_CALLS_PER_DAY=100
AI_SCORE_THRESHOLD=60.0
ENABLE_STRATEGY_SCANNER=false
STRATEGY_SCAN_INTERVAL_SEC=60.0
MAX_CONCURRENT_STRATEGIES=3
AI_HEALTH_PORT=8082

# Kiwoom (Python 전략 스캐너 활성화 시 필요)
KIWOOM_BASE_URL=https://api.kiwoom.com
```

#### websocket-listener `.env`

```bash
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# 설정
HEALTH_PORT=8081
LOG_LEVEL=INFO
```

#### telegram-bot `.env`

```bash
# Telegram
TELEGRAM_BOT_TOKEN=1234567890:AABBccDDeeFF...
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# 신호 설정
MIN_AI_SCORE=65
MAX_SIGNALS_PER_MIN=10
POLL_INTERVAL_MS=2000

# API (Java api-orchestrator)
KIWOOM_API_BASE_URL=http://localhost:8080
```

### 2.6 Redis 설정

#### Redis 설치 (Linux)

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install redis-server

# 서비스 시작
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 동작 확인
redis-cli ping
# PONG 출력 확인
```

#### Redis 보안 설정 (production)

`/etc/redis/redis.conf` 수정:

```conf
# 비밀번호 설정
requirepass your_strong_password_here

# 외부 접근 제한 (로컬만 허용)
bind 127.0.0.1

# 최대 메모리 설정 (전체 RAM의 25~50%)
maxmemory 2gb
maxmemory-policy allkeys-lru

# 영속성 설정 (선택)
save 900 1
save 300 10
```

#### Windows에서 Redis 설치

Windows는 WSL2 또는 Docker를 통해 Redis 실행을 권장합니다:

```powershell
# Docker 사용
docker run -d --name sma-redis -p 6379:6379 redis:7-alpine

# 비밀번호 포함
docker run -d --name sma-redis -p 6379:6379 redis:7-alpine redis-server --requirepass "your_password"
```

### 2.7 PostgreSQL 초기화

#### 데이터베이스 생성

```sql
-- PostgreSQL 접속 후 실행
CREATE USER sma_user WITH PASSWORD 'your_password';
CREATE DATABASE "SMA" OWNER sma_user;
GRANT ALL PRIVILEGES ON DATABASE "SMA" TO sma_user;
```

#### 테이블 자동 생성

`application.yml`의 `hibernate.ddl-auto: create`로 설정 시 Spring Boot 최초 기동 시 테이블이 자동 생성됩니다.

**주의**: `create` 모드는 기존 데이터를 삭제합니다. 운영 환경에서는 반드시 `update` 또는 `validate`로 변경하십시오.

```yaml
# application.yml
spring:
  jpa:
    hibernate:
      ddl-auto: update  # 운영 환경에서는 update 사용
```

### 2.8 각 모듈 실행 순서 (의존성 고려)

모듈 간 의존성이 있으므로 반드시 다음 순서로 기동하십시오:

```
1단계: Redis & PostgreSQL 기동 (인프라)
2단계: api-orchestrator 기동 (토큰 발급 및 Redis 초기화)
3단계: websocket-listener 기동 (실시간 데이터 수집)
4단계: ai-engine 기동 (AI 분석)
5단계: telegram-bot 기동 (신호 발송)
```

#### 1단계: 인프라 기동

```bash
# Redis 상태 확인
redis-cli ping

# PostgreSQL 상태 확인
pg_isready -h localhost -p 5432
```

#### 2단계: api-orchestrator 기동

```bash
cd api-orchestrator
# .env 파일이 있는지 확인
cat .env

# Gradle 빌드 및 실행
./gradlew bootRun

# 또는 JAR 실행
./gradlew build
java -jar build/libs/api-orchestrator-*.jar

# 정상 기동 확인 (키움 토큰 발급 로그 확인)
curl http://localhost:8080/actuator/health
```

#### 3단계: websocket-listener 기동

```bash
cd websocket-listener
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

python main.py

# 헬스체크
curl http://localhost:8081/health
```

#### 4단계: ai-engine 기동

```bash
cd ai-engine
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python engine.py

# 헬스체크
curl http://localhost:8082/health
```

#### 5단계: telegram-bot 기동

```bash
cd telegram-bot
npm install
npm start

# 개발 모드 (자동 재시작)
npm run dev
```

### 2.9 Docker Compose 구성 가이드

전체 시스템을 Docker Compose로 한 번에 관리할 수 있습니다.

#### `docker-compose.yml` 예시

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: sma-redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: postgres:15-alpine
    container_name: sma-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: SMA
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  api-orchestrator:
    build: ./api-orchestrator
    container_name: sma-api
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    env_file: ./api-orchestrator/.env
    ports:
      - "8080:8080"

  websocket-listener:
    build: ./websocket-listener
    container_name: sma-ws
    restart: unless-stopped
    depends_on:
      - api-orchestrator
    env_file: ./websocket-listener/.env
    ports:
      - "8081:8081"

  ai-engine:
    build: ./ai-engine
    container_name: sma-ai
    restart: unless-stopped
    depends_on:
      - redis
    env_file: ./ai-engine/.env
    ports:
      - "8082:8082"

  telegram-bot:
    build: ./telegram-bot
    container_name: sma-bot
    restart: unless-stopped
    depends_on:
      - redis
      - api-orchestrator
    env_file: ./telegram-bot/.env

volumes:
  redis_data:
  postgres_data:
```

#### Docker Compose 실행

```bash
# 전체 기동
docker-compose up -d

# 로그 확인
docker-compose logs -f ai-engine

# 특정 서비스만 재시작
docker-compose restart ai-engine

# 전체 중지
docker-compose down
```

### 2.10 문제 해결 (FAQ)

#### Q1: Redis 연결 실패

**증상**: `ConnectionRefusedError: [Errno 111] Connection refused`

```bash
# Redis 실행 상태 확인
redis-cli ping
# 또는
sudo systemctl status redis-server

# 방화벽 확인
sudo ufw status
# 필요시: sudo ufw allow 6379
```

#### Q2: 키움 API 인증 실패

**증상**: `401 Unauthorized` 또는 토큰 발급 실패 로그

```bash
# .env 파일의 키 값 재확인
cat api-orchestrator/.env | grep KIWOOM

# 키움 API 상태 페이지 확인
# https://apiportal.kiwoom.com 접속
```

#### Q3: Claude API 키 오류

**증상**: `RuntimeError: CLAUDE_API_KEY 환경 변수 미설정` 또는 `AuthenticationError`

```bash
# 환경변수 확인
echo $CLAUDE_API_KEY
# 또는
cat ai-engine/.env | grep CLAUDE_API_KEY

# Python에서 직접 확인
python -c "import os; print(os.getenv('CLAUDE_API_KEY', 'NOT SET'))"
```

#### Q4: Telegram Bot이 응답하지 않음

**증상**: Telegram에서 봇에 메시지를 보내도 응답 없음

```bash
# 봇 토큰 검증
curl "https://api.telegram.org/bot{YOUR_TOKEN}/getMe"

# Chat ID 확인
curl "https://api.telegram.org/bot{YOUR_TOKEN}/getUpdates"

# 환경변수 확인
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_ALLOWED_CHAT_IDS
```

#### Q5: PostgreSQL 연결 실패

**증상**: `Connection to localhost:5432 refused`

```bash
# PostgreSQL 실행 여부 확인
pg_isready

# 접속 테스트
psql -h localhost -U sma_user -d SMA -c "SELECT 1"
```

#### Q6: ai-engine이 신호를 처리하지 않음

**증상**: `telegram_queue`에 항목이 쌓이지만 `ai_scored_queue`로 넘어가지 않음

```bash
# telegram_queue 크기 확인
redis-cli LLEN telegram_queue

# ai-engine 로그 확인
tail -f ai-engine/logs/ai-engine.log

# 헬스체크
curl http://localhost:8082/health
```

---

## 3. 7가지 매매 전략 상세 설명

### 3.1 S1 전략: 갭상승 + 체결강도 돌파

#### 전략 개요

전일 장마감 후 발생한 호재(실적 발표, 공시, 뉴스)나 수급 변화로 당일 아침 예상 시초가가 전일 종가보다 높게 형성되는 갭상승 종목을 매수하는 전략입니다. 한국 주식 시장에서 갭상승은 일반적으로 강한 매수 심리를 반영하며, 특히 3~5% 갭 구간은 '골든 갭'으로 불리며 과도하지 않으면서도 충분한 상승 모멘텀을 제공합니다.

#### 활성화 시간대

- 장전 동시호가 (08:30 ~ 09:05)
- Python 전략 스캐너에서 `ka10029` API를 통해 갭 후보 종목을 탐색

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| 갭상승률 | ≥ 3% | 전일 종가 대비 예상 시초가 |
| 체결강도 | ≥ 130% | 최근 5분 평균 (ka10046) |
| 호가잔량 비율 | ≥ 1.5배 | 매수 호가 / 매도 호가 |
| 갭상승률 상한 | ≤ 15% | 과도한 갭은 제외 |

#### 스코어 산정 로직 (rule_score)

```
갭 점수:
  3% ≤ gap < 5%   → +20점 (최적 구간)
  5% ≤ gap < 8%   → +15점
  8% ≤ gap < 15%  → +10점
  gap ≥ 15%       → -10점 (과열)

체결강도 점수:
  strength > 150  → +30점
  130 < strength ≤ 150 → +20점
  110 < strength ≤ 130 → +10점

호가비율 점수:
  bid_ratio > 2.0  → +25점
  1.5 < ratio ≤ 2.0 → +20점
  1.3 < ratio ≤ 1.5 → +10점

신호 내 체결강도 보너스:
  cntr_strength > 150 → +10점
  cntr_strength > 130 → +5점
```

#### 진입 가격 및 타이밍

- **진입 방식**: 시초가 시장가 매수
- **진입 시점**: 09:00 시초가 결정 직후
- **주의**: 장전 동시호가(08:30~09:00) 동안 체결이 이루어지지 않으므로 예상 가격으로만 신호 발생

#### 손절/익절 기준

| 구분 | 기준 | 설명 |
|------|------|------|
| 목표가(익절) | +4.0% | 시초가 기준 4% 상승 시 매도 |
| 손절가 | -2.0% | 시초가 기준 2% 하락 시 즉시 청산 |
| 리스크/리워드 | 1:2 | 손실 대비 이익 2배 |

#### 예상 승률 및 수익률 (추정)

- **승률**: 55~65% (추정, 실제 과거 데이터 기반 아님)
- **1회 수익 (승리 시)**: 평균 +3.5~4.0%
- **1회 손실 (패배 시)**: -2.0%

#### 적합한 시장 환경

- KOSPI 지수 상승 또는 보합 장세
- 미국 시장 전날 강세 마감 후 갭업 출발
- 뚜렷한 테마 또는 섹터 강세 장 (해당 종목이 선도주)
- 실적 호재, 대규모 공시, 해외 호재 등 뉴스 동반

#### 부적합한 시장 환경 (리스크)

- 전체 시장 하락 장세 (갭상승 후 하락 전환 위험)
- 갭상승 종목이 너무 많은 날 (희귀성 없음)
- 거래량이 전일 대비 크게 적은 경우 (가짜 갭)
- 시가총액 소형주의 갭상승 (조작 위험)

#### 실전 예시 시나리오

**종목**: 삼성전자(005930)
**상황**: 전일 미국 필라델피아 반도체 지수 +3% 상승 후
**예상 시초가**: 85,000원 (전일 종가 82,000원 대비 +3.66%)
**체결강도**: 143% (ka10046 최근 5분)
**호가잔량 비율**: 1.82 (매수/매도)

→ **신호 발생**: 갭(+3.66%: +20점) + 체결강도(143%: +20점) + 호가비율(1.82: +20점) = 60점
→ **Claude AI 분석 후 최종 점수**: 72점 → **진입(ENTER)** 신호 발송

---

### 3.2 S2 전략: VI 발동 후 눌림목 매수

#### 전략 개요

VI(Volatility Interruption, 변동성 완화장치)는 주식 가격이 짧은 시간 내 급등할 때 2분간 단일가 매매로 전환하는 한국 거래소의 가격 안정화 장치입니다. VI 발동은 매수 수급이 강하다는 신호이며, VI 해제 후 가격이 일시적으로 하락하는 '눌림목' 구간은 추가 매수의 좋은 기회가 됩니다.

#### 활성화 시간대

- 장 시작 직후부터 마감까지 (09:00~15:20)
- VI 이벤트 기반으로 실시간 트리거

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| VI 발동 타입 | 동적 VI 우선 | 정적 VI보다 동적 VI가 신뢰성 높음 |
| 눌림목 범위 | -1% ~ -3% | VI 발동가 대비 현재가 하락폭 |
| 체결강도 | ≥ 110% | VI 해제 후에도 매수 우위 유지 |
| 호가비율 | ≥ 1.3 | 매수 호가 우위 |

#### 스코어 산정 로직 (rule_score)

```
눌림목 점수:
  1% ≤ pullback < 2%  → +30점 (최적 눌림)
  2% ≤ pullback < 3%  → +20점
  그 외                → 0점

동적 VI 보너스:
  is_dynamic = True   → +15점

체결강도 점수:
  strength > 120      → +20점
  110 < strength ≤ 120 → +10점

호가비율 점수:
  bid_ratio > 1.5     → +20점
  1.3 < ratio ≤ 1.5  → +10점
```

#### VI 감시 메커니즘

1. WebSocket GRP 7 (1h 타입)을 통해 VI 발동 이벤트 수신
2. `vi:{stk_cd}` Redis Hash에 VI 발동가, 시간, 타입 저장
3. `vi_watch_queue`에 등록 (10분간 감시)
4. api-orchestrator의 `ViWatchService`가 현재가를 주기적으로 확인하여 눌림 감지

#### 진입 가격 및 타이밍

- **진입 방식**: 지정가 (VI 해제 후 눌림 구간)
- **진입 가격**: VI 발동가 대비 -1.5% 지점 (눌림 중간)
- **진입 시점**: VI 해제 후 2~5분 이내

#### 손절/익절 기준

| 구분 | 기준 | 설명 |
|------|------|------|
| 목표가(익절) | +3.0% | VI 발동가 회복 + 추가 상승 |
| 손절가 | -2.0% | 눌림 매수가 기준 |
| 리스크/리워드 | 1:1.5 | VI 특성상 비교적 빠른 회복 기대 |

#### 예상 승률 및 수익률 (추정)

- **승률**: 60~70% (추정)
- **1회 수익 (승리 시)**: 평균 +2.5~3.0%
- **1회 손실 (패배 시)**: -2.0%

#### 적합한 시장 환경

- 개장 후 30분~2시간 (오전 장, 매수 수급 활발)
- 테마 주도 종목의 VI 발동 (연속 상승 가능성)
- 전체 시장 지수 상승 중 발동

#### 부적합한 시장 환경

- 시장 전체 급락 장 (VI 후 추가 하락 위험)
- 오후 2시 이후 발동 (수급 소강 구간)
- 동일 종목 하루 3회 이상 VI 발동 (과열 종목, 청산 위험)

#### 실전 예시 시나리오

**종목**: SK하이닉스(000660)
**VI 발동**: 09:45 동적 VI 발동, 발동가 130,000원
**VI 해제**: 09:47
**현재가**: 128,700원 (발동가 대비 -1.0%)
**체결강도**: 118% (VI 해제 후 소폭 하락)
**호가비율**: 1.45

→ **신호 발생**: 눌림(1.0%: +30점) + 동적VI(+15점) + 체결강도(118%: +10점) + 호가비율(1.45: +10점) = 65점
→ **Claude 임계값**: 65점 → **Claude 분석 진행**
→ **최종 점수**: 71점 → **진입(ENTER)** 신호

---

### 3.3 S3 전략: 기관/외국인 순매수 연속

#### 전략 개요

기관투자자와 외국인 투자자가 동시에 특정 종목을 연속으로 순매수하는 경우, 이는 '스마트 머니'의 집중 유입을 의미합니다. 개인 투자자보다 정보력과 분석력이 뛰어난 기관/외인의 연속 매수는 해당 종목의 펀더멘털이나 향후 모멘텀에 대한 강한 확신을 나타냅니다.

#### 활성화 시간대

- 장중 (09:30 ~ 14:30)
- 30분마다 API 조회 업데이트

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| 동시 순매수 | 기관+외인 동시 | ka10063 smtm_netprps_tp=1 |
| 연속 순매수 일수 | ≥ 3일 | ka10131 기준 |
| 당일 거래량 | 전일 동시간 대비 ≥ 1.5배 | ka10055 기준 |

#### 스코어 산정 로직 (rule_score)

```
순매수 금액 점수 (최대 25점):
  min(25, net_buy_amt / 1,000,000 × 0.5)
  (예: 10억원 = 5점, 50억원 = 25점)

연속 순매수 일수 점수:
  cont_days ≥ 5일  → +30점
  cont_days ≥ 3일  → +20점
  cont_days ≥ 1일  → +10점

거래량 비율 점수:
  vol_ratio ≥ 3x   → +25점
  vol_ratio ≥ 2x   → +20점
  vol_ratio ≥ 1.5x → +10점
```

#### 진입 가격 및 타이밍

- **진입 방식**: 지정가 (최우선 매수 1호가)
- **진입 시점**: 신호 발생 즉시 또는 일시 하락 시
- **주의**: 이미 많이 오른 종목(flu_rt > 10%)은 패널티 적용

#### 손절/익절 기준

| 구분 | 기준 | 설명 |
|------|------|------|
| 목표가(익절) | +3.5% | 기관/외인 지속 매수 기대 |
| 손절가 | -2.0% | 수급 약화 신호 시 즉시 청산 |
| 리스크/리워드 | 1:1.75 | |

#### 예상 승률 및 수익률 (추정)

- **승률**: 50~60% (추정)
- **1회 수익 (승리 시)**: 평균 +3.0~4.0%
- **1회 손실 (패배 시)**: -2.0%

#### 적합한 시장 환경

- 기관/외인 동반 순매수 지속 구간
- 펀더멘털 개선이 있는 종목 (실적 개선, 수주 뉴스)
- 지수 반등 초기 단계 (기관 먼저 사고 개인 뒤따라 오르는 패턴)

#### 부적합한 시장 환경

- 시장 전체 패닉셀 구간 (기관도 손절 가능)
- 오후 2시 30분 이후 (마감 대비 포지션 조정)

---

### 3.4 S4 전략: 장대양봉 캔들 패턴

#### 전략 개요

5분봉 차트에서 강한 매수세로 형성된 장대양봉은 단기 모멘텀이 강하다는 신호입니다. 특히 전일 거래량 대비 5배 이상의 거래량을 동반한 장대양봉은 새로운 매수 세력의 진입 또는 이슈 발생을 의미합니다. 이 신호 직후의 추격 매수가 S4 전략입니다.

#### 활성화 시간대

- 장중 상시 (집중: 10:00 ~ 14:30)
- 후보 종목 상위 30개 순차 스캔

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| 양봉 여부 | 종가 > 시가 | 5분봉 기준 |
| 양봉 몸통 비율 | ≥ 70% | (종가-시가)/(고가-저가) |
| 상승폭 | ≥ 3% | 시가 대비 현재가 |
| 거래량 비율 | ≥ 5배 | 직전 5봉 평균 대비 |
| 체결강도 | ≥ 140% | 최근 3분 평균 |

#### 스코어 산정 로직 (rule_score)

```
거래량 비율 점수:
  vol_ratio > 10   → +25점
  vol_ratio > 5    → +20점
  vol_ratio > 3    → +10점

양봉 몸통 비율 점수:
  body_ratio ≥ 0.8 → +20점
  body_ratio ≥ 0.7 → +10점

신고가 보너스:
  is_new_high = True → +20점

체결강도 점수:
  strength > 150   → +20점
  strength > 140   → +15점
  strength > 120   → +5점
```

#### 진입 가격 및 타이밍

- **진입 방식**: 추격 시장가 (신호 발생 즉시)
- **주의**: 추격 매수이므로 슬리피지 위험 있음
- **손절**: 추격매수 특성상 일반 전략보다 넉넉하게 설정

#### 손절/익절 기준

| 구분 | 기준 | 설명 |
|------|------|------|
| 목표가(익절) | +4.0% | 모멘텀 지속 기대 |
| 손절가 | -2.5% | 추격매수 위험 보상 |
| 리스크/리워드 | 1:1.6 | |

#### 예상 승률 및 수익률 (추정)

- **승률**: 55~65% (추정)
- **1회 수익 (승리 시)**: 평균 +3.5~5.0%
- **1회 손실 (패배 시)**: -2.5%

---

### 3.5 S5 전략: 프로그램 매수 유입

#### 전략 개요

프로그램 매매는 지수 구성 종목들에 대한 기계적·대규모 매수를 의미합니다. 선물/ETF 차익거래와 연계된 프로그램 매수는 강한 상승 압력을 만들며, 외국인 동반 매수 시 더욱 강력한 신호가 됩니다. KOSPI200, KOSDAQ150 등 지수 편입 종목에서 주로 발생합니다.

#### 활성화 시간대

- 장중 (10:00 ~ 14:00)
- ka90003, ka90009 API로 상위 50종목 확인

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| 프로그램 순매수 상위 | 50위 이내 | ka90003 기준 |
| 외국인/기관 매매상위 | 동시 포함 | ka90009 기준 |

#### 스코어 산정 로직 (rule_score)

```
프로그램 순매수 금액 점수 (최대 40점):
  min(40, net_buy_amt / 1,000,000 × 0.4)

체결강도 점수:
  strength > 130   → +25점
  120 < strength ≤ 130 → +20점
  100 < strength ≤ 120 → +10점

호가비율 점수:
  bid_ratio > 2.0  → +20점
  1.5 < ratio ≤ 2.0 → +15점
  1.2 < ratio ≤ 1.5 → +8점
```

#### 예상 승률 및 수익률 (추정)

- **승률**: 45~55% (추정)
- **1회 수익 (승리 시)**: 평균 +2.5~3.5%
- **1회 손실 (패배 시)**: -2.0%
- **특징**: 프로그램 매수는 갑작스럽게 역전될 수 있어 상대적으로 낮은 승률

---

### 3.6 S6 전략: 테마/섹터 모멘텀

#### 전략 개요

특정 테마(예: AI 반도체, 2차전지, 바이오)의 선도주가 크게 오를 때, 같은 테마에 속한 후발주가 뒤따라 상승하는 패턴을 이용합니다. 선도주 대비 아직 덜 오른 종목(후발주)을 찾아 진입하는 전략입니다. 선도주의 상승률이 +2% 이상인 테마에서, 테마 내 하위 30% 수익률 종목을 선별합니다.

#### 활성화 시간대

- 오전 장 집중 (09:30 ~ 13:00)
- 테마 모멘텀이 오후에 소강될 수 있어 제한

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| 테마 등락률 | ≥ 2.0% | ka90001 테마 전체 상승 확인 |
| 개별 종목 등락률 | 0.5% ~ 테마 상위30% 미만 | 아직 덜 오른 후발주 |
| 개별 종목 등락률 상한 | < 5.0% | 이미 크게 오른 종목 제외 |
| 체결강도 | ≥ 120% | 매수 우위 |

#### 스코어 산정 로직 (rule_score)

```
갭/등락 점수:
  1% ≤ gap < 3%   → +25점
  3% ≤ gap < 5%   → +15점
  그 외             → 0점

체결강도 점수 (신호 내 값 우선):
  effective > 150 → +30점
  effective > 120 → +20점

호가비율 점수:
  bid_ratio > 1.5  → +20점
  1.2 < ratio ≤ 1.5 → +10점
```

#### 예상 승률 및 수익률 (추정)

- **승률**: 50~60% (추정)
- **1회 수익 (승리 시)**: 평균 +2.0~4.0% (테마 강도에 의존)
- **목표가**: `min(테마 등락률 × 0.6, 5.0%)` (테마 상승률의 60%, 최대 5%)
- **1회 손실 (패배 시)**: -2.0%

#### 적합한 시장 환경

- 특정 테마가 강하게 부각되는 장 (정책 발표, 글로벌 이슈)
- 오전 10시 이전 테마 흐름 명확히 확인된 경우

---

### 3.7 S7 전략: 장전 동시호가 급등

#### 전략 개요

장전 동시호가(08:00~09:00)에서 예상 시초가가 전일 종가보다 +2~10% 높게 형성되고, 매수 호가잔량이 압도적으로 많은 종목을 선별합니다. 동시호가는 체결이 이루어지지 않으므로 '예상' 수급을 기반으로 판단합니다. 시가총액이 충분히 크고(500억 이상), 예상 거래량이 많은 종목을 선별하여 조작 및 변동성 위험을 낮춥니다.

#### 활성화 시간대

- 장전 동시호가 (08:30 ~ 09:00)
- S1과 동시 실행되지만 선행 처리 (S7 → S1 순서)

#### 매수 신호 발생 조건

| 조건 | 기준값 | 의미 |
|------|--------|------|
| 예상 갭 | +2% ~ +10% | 과도한 갭 제외 |
| 매수/매도 호가잔량 비율 | ≥ 2.0 | 매수 압도적 우위 |
| 예상 거래량 순위 | 50위 이내 | ka10029 기준 |

#### 스코어 산정 로직 (rule_score)

```
갭 점수:
  2% ≤ gap < 5%   → +25점
  5% ≤ gap < 8%   → +15점
  그 외             → 0점

호가비율 점수:
  bid_ratio > 3.0  → +30점
  2.0 < ratio ≤ 3.0 → +25점
  1.5 < ratio ≤ 2.0 → +10점

거래량 순위 점수:
  vol_rank ≤ 10   → +20점
  vol_rank ≤ 20   → +15점
  vol_rank ≤ 30   → +5점
```

#### 예상 승률 및 수익률 (추정)

- **승률**: 65~75% (추정, 7가지 전략 중 가장 높음)
- **1회 수익 (승리 시)**: min(gap × 0.8, 5.0%)
- **1회 손실 (패배 시)**: -2.0%
- **특징**: 갭 소화 패턴이 예측 가능하여 상대적으로 높은 승률

---

### 3.8 전략 조합 및 복합 시그널 활용법

두 가지 이상의 전략에서 동시에 신호가 발생하는 종목은 특히 강한 매수 신호입니다.

#### 복합 신호 우선순위

| 조합 | 신뢰도 | 설명 |
|------|--------|------|
| S1 + S7 | 매우 높음 | 갭상승 + 동시호가 양호 → 장 시작 최강 신호 |
| S3 + S4 | 높음 | 기관/외인 매수 + 장대양봉 → 지속 상승 가능성 |
| S2 + S3 | 높음 | VI 눌림목 + 기관 순매수 → 반등 강도 강함 |
| S5 + S3 | 보통 | 프로그램 + 기관/외인 → 장기 수급 유입 신호 |
| S6 + S4 | 보통 | 테마 후발주 + 장대양봉 → 추격 가속 가능성 |

#### 중복 신호 처리

SMA는 동일 종목에 대해 일정 TTL(Time To Live) 내 중복 신호 발송을 방지합니다:

| 전략 | 중복 TTL |
|------|---------|
| S1_GAP_OPEN | 1800초 (30분) |
| S2_VI_PULLBACK | 3600초 (1시간) |
| S7_AUCTION | 7200초 (2시간) |
| 기타 | 기본 TTL |

### 3.9 전략별 적용 시간대 (장 시작/중간/마감)

```
08:30 ─── 09:00 ─── 09:30 ─── 10:00 ─── 13:00 ─── 14:00 ─── 14:30 ─── 15:30
  │           │          │          │          │          │          │          │
  ├── S7 ───┤           │          │          │          │          │          │
  ├──── S1 ──────────┤  │          │          │          │          │          │
                        ├─── S2 (장 전체, VI 이벤트 기반) ───────────────────┤
                        ├─── S3 ────────────────────────────┤                  │
                        ├─── S4 ──────────────────────────────────┤            │
                                   ├── S5 ─────────────────┤                   │
                        ├──── S6 ──────────────────┤                           │
```

**황금 시간대 (09:00~10:30)**: S1, S2, S7 신호에 집중
**낮 시간대 (10:30~14:00)**: S3, S4, S5, S6 신호 중심
**마감 전 (14:30~15:30)**: FORCE_CLOSE 신호 대기, 신규 진입 자제

---

## 4. AI 스코어링 시스템

### 4.1 Rule-Based Pre-Filter (analyzer.py)

AI 분석 전 규칙 기반으로 1차 필터링을 수행합니다. 이 단계에서 낮은 점수의 신호를 제거하여 Claude API 호출 비용을 절감합니다.

#### 전략별 Claude 호출 임계값

| 전략 | Claude 임계값 | 이유 |
|------|-------------|------|
| S1_GAP_OPEN | 70점 | 갭상승은 조건이 명확하므로 높은 기준 |
| S2_VI_PULLBACK | 65점 | VI 눌림목은 다양한 패턴 존재 |
| S3_INST_FRGN | 60점 | 기관/외인 데이터는 노이즈가 많음 |
| S4_BIG_CANDLE | 75점 | 장대양봉 추격은 높은 확신 필요 |
| S5_PROG_FRGN | 65점 | 프로그램 매수 데이터 신뢰성 |
| S6_THEME_LAGGARD | 60점 | 테마 후발주는 불확실성 높음 |
| S7_AUCTION | 70점 | 동시호가 데이터는 신뢰성 높음 |

#### 공통 패널티 규칙

```python
# 이미 많이 오른 종목 (과열 페널티)
if flu_rt > 15%:   score -= 20
elif flu_rt > 10%: score -= 10

# 하락 중인 종목
if flu_rt < -5%: score -= 15
```

### 4.2 Claude AI 스코어링 (scorer.py)

규칙 기반 점수가 전략별 임계값을 통과하면 Claude API를 호출합니다.

#### 분석 요청 형식

Claude에게 전달되는 정보:
- 종목 코드 및 이름
- 전략별 핵심 지표 (갭률, 체결강도, 호가비율 등)
- 규칙 기반 1차 점수 (0~100)
- 현재 등락률

#### Claude 응답 형식

```json
{
  "action": "ENTER",
  "ai_score": 78,
  "confidence": "HIGH",
  "reason": "강한 갭상승과 체결강도 지속. 호가비율 양호.",
  "adjusted_target_pct": 3.5,
  "adjusted_stop_pct": -2.0
}
```

#### 스코어별 해석 가이드

| AI 점수 | 의미 | 권장 행동 |
|---------|------|---------|
| 90점 이상 | 최강 신호 | 적극적 진입, 표준 포지션의 150% |
| 80~90점 | 강한 신호 | 일반 진입, 표준 포지션 |
| 70~80점 | 보통 신호 | 소규모 진입 또는 관망 후 진입 |
| 65~70점 | 약한 신호 | 관망 권장 (HOLD 또는 소량 진입) |
| 65점 미만 | 신호 없음 | 진입 안 함 (CANCEL) |

#### 신뢰도(confidence) 해석

| 신뢰도 | 의미 |
|--------|------|
| HIGH (🔴 높음) | Claude가 조건을 명확히 판단 |
| MEDIUM (🟡 보통) | 일부 불확실성 존재 |
| LOW (⚪ 낮음) | 데이터 부족 또는 폴백 결과 |

### 4.3 최종 신호 판단 로직

```
신호 수신
    │
    ├─ FORCE_CLOSE / DAILY_REPORT → 즉시 전달 (AI 분석 없음)
    │
    ├─ rule_score() 계산 (0~100점)
    │       │
    │       ├─ 전략별 임계값 미달 → CANCEL 처리 (Claude 미호출)
    │       │
    │       └─ 임계값 이상 → check_daily_limit() 확인
    │               │
    │               ├─ 일별 한도 초과 → _fallback(rule_score) 사용
    │               │
    │               └─ 한도 내 → analyze_signal() (Claude API 호출)
    │                               │
    │                               ├─ 성공 → JSON 파싱 결과 사용
    │                               └─ 실패(타임아웃/오류) → _fallback 사용
    │
    └─ 결과를 ai_scored_queue에 LPUSH
```

### 4.4 Claude AI 분석 비용 모니터링

#### Redis 키 구조

```
claude:daily_calls:{YYYYMMDD}   → 일별 호출 횟수 (숫자)
claude:daily_tokens:{YYYYMMDD}  → 일별 토큰 사용량 (입력+출력 합계)
```

#### Telegram 명령으로 확인

`/상태` 명령어 응답에서 확인:

```
🟢 시스템 상태
Java API: UP
서비스: stockmate-ai

📊 Claude AI 오늘 사용량
호출 횟수: 42 / 100
총 토큰: 18,720
```

#### 비용 초과 방지

`MAX_CLAUDE_CALLS_PER_DAY` 환경변수로 일별 최대 호출 수를 제한합니다 (기본: 100회). 초과 시 `_fallback()` 함수로 규칙 스코어만 사용합니다.

---

## 5. Telegram Bot 사용법

### 5.1 Bot 명령어 전체 목록

#### `/ping` – 봇 동작 확인

```
입력: /ping
응답: 🏓 pong! StockMate AI 작동 중
활용팁: 봇이 살아있는지 빠르게 확인
```

#### `/상태` – 시스템 헬스체크

```
입력: /상태
응답 예시:
  🟢 시스템 상태
  Java API: UP
  서비스: stockmate-api-orchestrator

  📊 Claude AI 오늘 사용량
  호출 횟수: 42 / 100
  총 토큰: 18,720

활용팁: 매일 장 시작 전 시스템 정상 여부 확인
```

#### `/신호` – 당일 신호 목록

```
입력: /신호
응답 예시:
  📋 당일 신호 (최근 10건)

  1. 005930 [S1_GAP_OPEN] ENTER | 스코어: 78
  2. 000660 [S2_VI_PULLBACK] ENTER | 스코어: 71
  3. 035720 [S4_BIG_CANDLE] HOLD | 스코어: 68
  ...

활용팁: 이미 발송된 신호 목록 확인. 놓친 신호 체크.
```

#### `/성과` – 당일 전략별 성과

```
입력: /성과
응답 예시:
  📊 당일 전략별 성과

  🚀 S1_GAP_OPEN: 3건 | 평균 +2.13%
  🎯 S2_VI_PULLBACK: 2건 | 평균 +1.85%
  💻 S5_PROG_FRGN: 1건 | 평균 N/A

활용팁: 어떤 전략이 오늘 잘 작동했는지 점검
```

#### `/후보 [market]` – 후보 종목 조회

```
입력: /후보       (전체 시장)
      /후보 001   (KOSPI)
      /후보 101   (KOSDAQ)
응답 예시:
  📋 후보 종목 [000]
  총 87개
  005930, 000660, 035720, 005380, 000270, ...

활용팁: 전략 스캔 대상 종목 수 확인
```

#### `/시세 {종목코드}` – 실시간 시세

```
입력: /시세 005930
응답 예시:
  📈 005930 실시간 시세
  현재가: 84,300원
  등락률: +1.32%
  체결강도: 118.5
  누적거래량: 8,420,351
  체결시간: 14:23:45

활용팁: 신호 수신 후 현재가 빠르게 확인
주의: 종목코드는 반드시 6자리 숫자
```

#### `/전술 {s1~s7}` – 전술 수동 실행

```
입력: /전술 s1
응답 예시:
  ✅ S1_GAP_OPEN 실행 완료
  발행 신호: 3건

사용 가능: s1, s2, s3, s4, s5, s6, s7
활용팁: 장 중 특정 전략만 수동으로 즉시 실행하고 싶을 때
```

#### `/토큰갱신` – 키움 토큰 수동 갱신

```
입력: /토큰갱신
응답 예시:
  🔑 토큰 갱신 성공 (만료: 24시간 후)

활용팁: 토큰 만료 오류 발생 시 사용. 보통은 자동 갱신됨.
```

#### `/ws시작` – WebSocket 구독 시작

```
입력: /ws시작
응답: 📡 WebSocket 구독 시작 완료

활용팁: 시스템 재시작 후 또는 연결 끊김 후 사용
```

#### `/ws종료` – WebSocket 구독 종료

```
입력: /ws종료
응답: 🔌 WebSocket 구독 종료

주의: 실행 후 실시간 데이터 수신이 중단됨
```

#### `/report` – 오늘 신호 요약

```
입력: /report
응답 예시:
  📊 오늘의 신호 리포트 (20260321)

  총 신호: 12건
  평균 스코어: 74.3점
  전략별:
    S1_GAP_OPEN: 3건
    S2_VI_PULLBACK: 2건
    S4_BIG_CANDLE: 4건
    S7_AUCTION: 3건
```

#### `/filter [s1~s7|all]` – 전략 필터 설정

```
입력: /filter s1 s4   → S1, S4 전략 신호만 수신
      /filter all     → 모든 전략 수신 (필터 해제)
      /filter         → 현재 필터 확인

활용팁: 선호하는 전략의 신호만 받고 싶을 때 유용
예시: 갭상승과 장대양봉에만 집중 → /filter s1 s4
```

#### `/help` – 명령어 목록

```
입력: /help
응답: 전체 명령어 목록 출력
```

### 5.2 매매 신호 메시지 해석

#### 신호 메시지 예시

```
🚀 [S1_GAP_OPEN] 005930 삼성전자
✅ 진입  |  신뢰도: 🔴 높음
AI 스코어: 78.0점  (규칙: 75.0점)
진입방식: 시초가_시장가
목표: +4.0%  손절: -2.0%
진입가: 84,300원
목표가: 87,672원 (+4.0%)  손절가: 82,614원 (-2.0%)
리스크/리워드: 1:2.0
갭/상승: 3.85%
체결강도: 143.0%
호가비율(매수/매도): 1.82

💬 강한 갭상승과 안정적인 체결강도. 호가잔량도 매수 우위로 시초가 매수 적합.

🕐 09:00:05
```

#### 각 필드 설명

| 필드 | 설명 |
|------|------|
| 이모지 + 전략 | 전략 코드 (🚀=S1, 🎯=S2, 🏦=S3, 📊=S4, 💻=S5, 🔥=S6, ⚡=S7) |
| 종목코드 + 종목명 | 신호 발생 종목 |
| 진입/관망/취소 | 최종 행동 (ENTER/HOLD/CANCEL) |
| 신뢰도 | AI 분석 확신도 (🔴높음/🟡보통/⚪낮음) |
| AI 스코어 | Claude AI 최종 점수 (0~100) |
| 규칙 스코어 | 규칙 기반 1차 점수 |
| 진입방식 | 시초가/지정가/추격 시장가 |
| 목표/손절 % | 익절·손절 퍼센트 |
| 진입가 | 현재 체결가 또는 시초가 |
| 목표가/손절가 | 계산된 절대 가격 |
| 리스크/리워드 | 손실 대비 수익 비율 |
| 전략별 지표 | 갭률, 체결강도, 호가비율 등 |
| AI 분석 | Claude의 진입 근거 (2문장 이내) |
| 시간 | 신호 발생 시각 |

### 5.3 알림 설정 최적화

#### Telegram 알림 조용히 보기

중요한 시간에 신호를 놓치지 않으면서 불필요한 알림을 줄이는 설정:

1. 봇 채팅방 → 오른쪽 상단 [···] 메뉴
2. [음소거] 선택
3. SMA 신호는 Telegram 알림이 아닌 직접 확인 방식으로 전환

#### 전략 필터 최적화

자신의 매매 스타일에 맞게 필터를 설정하세요:

| 스타일 | 권장 필터 | 이유 |
|--------|---------|------|
| 단기 스캘퍼 | `/filter s1 s7` | 갭상승·동시호가로 장 시작 집중 |
| 모멘텀 트레이더 | `/filter s2 s4 s6` | VI 눌림목·장대양봉·테마 모멘텀 |
| 기관 추종 | `/filter s3 s5` | 기관/외인·프로그램 매수 |
| 전략 없음 | `/filter all` | 모든 신호 수신 |

### 5.4 자주 묻는 질문

**Q: 신호가 오전에 집중되나요?**
A: 네. S1, S7 전략은 08:30~09:05에만 작동하며, S2, S4, S6은 오전 장(09:00~13:00)이 더 활발합니다. S3, S5는 오전 09:30 이후부터 14:30까지 균등하게 발생합니다.

**Q: 하루에 몇 개의 신호를 받을 수 있나요?**
A: 시장 상황에 따라 다르지만, 평균적으로 5~20건 사이입니다. 분당 최대 발송 수(`MAX_SIGNALS_PER_MIN=10`)로 제한되어 있어 대량 발송은 방지됩니다.

**Q: CANCEL 신호는 왜 안 오나요?**
A: CANCEL 신호는 Telegram으로 발송하지 않습니다. 점수 미달이라고 판단된 신호는 자동으로 제거됩니다. `/신호` 명령으로 발송된 신호만 확인 가능합니다.

**Q: 같은 종목에서 신호가 반복해서 오나요?**
A: 중복 TTL 설정으로 인해 일정 시간 내 동일 전략·동일 종목 신호는 중복 발송되지 않습니다.

---

## 6. 실전 매매 가이드

### 6.1 하루 매매 루틴 (시간대별)

#### 08:30 장전 준비

```
□ SMA 시스템 상태 확인 (/상태 명령어)
□ Redis 큐 비어있는지 확인
□ 전날 밤 미국 시장 동향 파악 (S1, S7 신호 예상)
□ S7 전략 동시호가 신호 대기 시작
```

#### 09:00 장 시작 직후

```
□ S1 갭상승 신호 수신 즉시 확인
□ S7 동시호가 신호로 시초가 매수 여부 결정
□ 신호의 AI 스코어 확인 (80점 이상 = 적극 고려)
□ /시세 명령어로 현재가 실시간 확인
```

#### 09:00~10:00 골든 타임

한국 주식 시장에서 가장 중요한 1시간입니다. 하루 거래량의 20~30%가 이 구간에 집중됩니다.

```
□ S1, S2 신호 적극 대응
□ 장 초반 강한 테마 파악 (S6 신호 예비 확인)
□ 진입 신호 수신 시 30초 이내 의사결정
□ 포지션 진입 후 목표가/손절가 주문 미리 설정
```

#### 10:00~14:30 유지 관리

```
□ S3, S4, S5, S6 신호 모니터링
□ 보유 포지션 손익 확인
□ 손절선 도달 시 즉시 매도 (절대 원칙)
□ 목표가 도달 시 분할 매도 고려
```

#### 14:30~15:30 마감 대응

```
□ 미달성 포지션 매도 결정
□ FORCE_CLOSE 신호 수신 시 즉시 청산
□ 15:00 이후 새로운 진입 자제
□ 익일을 위한 종목 예비 분석
```

#### 15:30 이후 정리

```
□ /report 명령으로 일일 성과 확인
□ /성과 명령으로 전략별 통계 확인
□ 매매 일지 작성 (진입 근거, 결과, 개선점)
□ 익일 장을 위한 시장 리뷰
```

### 6.2 신호 수신 후 행동 가이드

#### 단계별 의사결정 흐름

```
신호 수신
    │
    ├── AI 스코어 확인
    │       ├── 90점 이상: 즉시 진입 검토
    │       ├── 80~90점: 현재가 확인 후 진입
    │       ├── 70~80점: 추가 조건 확인 후 진입
    │       └── 65~70점: 관망 또는 소량 테스트
    │
    ├── 현재 시장 상황 확인 (/시세 명령)
    │       ├── 등락률이 신호 당시보다 +2% 이상 더 오름: 진입 포기 (슬리피지 과다)
    │       └── 신호 당시와 유사: 진입 검토
    │
    ├── 포지션 사이징 결정 (6.3절 참조)
    │
    └── 손절/목표가 주문 동시 설정 (필수)
```

#### 절대 하지 말아야 할 것들

1. **손절선을 임의로 낮추기**: "조금만 더 기다리면 오를 것 같다"는 생각은 금물
2. **스코어가 낮은 신호 무시하기**: HOLD나 낮은 점수의 신호는 시스템이 이미 걸러낸 것
3. **하나의 신호에 전 자금 투입**: 분산 투자 원칙 준수
4. **마감 30분 전 신규 진입**: 청산 시간 부족

### 6.3 포지션 사이징 권장

#### 기본 원칙

- 단일 포지션: 총 투자 자금의 **최대 20%**
- 동시 보유 포지션: **최대 5개**
- 일일 최대 손실 한도: 총 자금의 **3%** (초과 시 당일 거래 중단)

#### AI 스코어별 포지션 크기

| AI 스코어 | 표준 포지션 대비 | 예시 (총 자금 1000만원 기준) |
|---------|---------------|--------------------------|
| 90점 이상 | 100% | 200만원 |
| 80~90점 | 75% | 150만원 |
| 70~80점 | 50% | 100만원 |
| 65~70점 | 25% | 50만원 |

#### 손실 복구 원칙

연속 손실 발생 시 포지션을 줄이고 시스템을 점검하세요:

- 3연속 손실: 포지션 크기 50%로 축소
- 5연속 손실: 당일 거래 중단, 시스템 점검

### 6.4 리스크 관리 규칙

#### 절대적 규칙 (어기지 않는 원칙)

1. **손절은 반드시 실행**: AI가 ENTER 신호를 줬더라도 손절선 도달 시 즉시 청산
2. **한 종목 집중 금지**: 단일 종목에 총 자금의 20% 초과 투자 금지
3. **일별 손실 한도**: 일일 최대 손실이 총 자금의 3% 도달 시 당일 거래 종료
4. **주간 손실 한도**: 주 손실이 총 자금의 7% 도달 시 1주일 매매 휴식

#### 추가 위험 관리

- **레버리지 금지**: SMA 신호 기반 신용·미수 매수 절대 금지
- **평균단가 낮추기 금지**: 하락 중 추가 매수는 손실 확대 위험
- **감정적 거래 금지**: 큰 손실 직후 복수 매매 금지

### 6.5 예상 수익률 시뮬레이션

**중요**: 이 시뮬레이션은 가상의 추정 데이터입니다. 실제 수익을 보장하지 않으며, 과거 성과가 미래 수익을 담보하지 않습니다.

#### 전략별 기대 수익률 (추정)

| 전략 | 추정 승률 | 평균 수익(승) | 평균 손실(패) | 월 예상 거래 | 월 기대 수익률 |
|------|---------|------------|------------|----------|-------------|
| S1 | 60% | +3.5% | -2.0% | 15건 | +1.7% |
| S2 | 65% | +2.8% | -2.0% | 20건 | +1.5% |
| S3 | 55% | +3.2% | -2.0% | 10건 | +0.9% |
| S4 | 60% | +4.0% | -2.5% | 12건 | +1.5% |
| S5 | 50% | +3.0% | -2.0% | 8건 | +0.4% |
| S6 | 55% | +2.5% | -2.0% | 15건 | +0.9% |
| S7 | 70% | +3.2% | -2.0% | 10건 | +1.6% |

*승률 × 평균 수익 - 패률 × 평균 손실 = 기대값. 포지션 크기는 총 자금의 15% 기준.*

#### 월 수익률 시나리오 (100만원 단위)

| 시나리오 | 월 거래 수 | 평균 AI 스코어 | 예상 월 수익률 | 예상 월 수익액 |
|--------|---------|-------------|------------|------------|
| 낙관적 | 90건 | 78점 | +8~12% | +80~120만원 |
| 중립 | 60건 | 73점 | +3~6% | +30~60만원 |
| 보수적 | 40건 | 70점 | +1~3% | +10~30만원 |
| 불리 | 60건 | 68점 | -2~+1% | -20~+10만원 |

*시뮬레이션은 추정치이며 실제 결과는 크게 다를 수 있습니다.*

#### 리스크/리워드 기본 구조

SMA의 기본 R:R 비율은 1:2 (손실 2%, 수익 4%)로 설계되어 있습니다.

이 비율에서:
- 승률 40% 이상이면 손익분기점 달성
- 승률 50% = 월 약 +3~5% 기대 수익
- 승률 60% = 월 약 +6~10% 기대 수익

### 6.6 실패 케이스 및 대응

#### 케이스 1: 갭상승 후 즉시 하락 (Gap Fill)

**상황**: S1 신호로 진입했으나 시초가 직후 갭메우기 하락
**원인**: 과도한 선물 고평가, 기관 차익실현
**대응**:
- 손절선(-2%) 유지 (가장 중요)
- 이후 S1 신호에서 갭 5% 이상 필터 고려
- 시장 선물 현/선물 스프레드 확인 습관화

#### 케이스 2: VI 이후 급락

**상황**: S2 VI 눌림목 신호로 진입했으나 VI 해제 후 매물 폭발
**원인**: 시장 조성자 청산, 동적 VI임에도 강한 매도 압력
**대응**:
- 는 즉각적인 손절 실행
- 이후 VI 발동 후 거래량 조건을 더 엄격하게 적용

#### 케이스 3: 기관 매수 후 반전

**상황**: S3 신호로 진입했으나 기관이 연속 매도 전환
**원인**: 외부 악재 발생 또는 기관 포트폴리오 조정
**대응**:
- 기관 매도 전환 감지 즉시 청산
- S3 신호 수신 후 `/시세` 명령으로 현재 기관 동향 재확인

---

## 7. 시스템 모니터링 및 운영

### 7.1 Redis 큐 상태 확인

#### 주요 Redis 키 모니터링

```bash
# 현재 큐 크기 확인
redis-cli LLEN telegram_queue     # 처리 대기 신호
redis-cli LLEN ai_scored_queue    # 발송 대기 신호
redis-cli LLEN error_queue        # 처리 실패 신호

# 실시간 모니터링 (1초 간격)
watch -n 1 'redis-cli LLEN telegram_queue; redis-cli LLEN ai_scored_queue'

# 큐의 최근 항목 미리보기 (삭제 없이)
redis-cli LRANGE telegram_queue -1 -1
redis-cli LRANGE ai_scored_queue -1 -1
```

#### 정상 상태 기준

| 큐 | 정상 범위 | 주의 | 위험 |
|----|---------|------|------|
| telegram_queue | 0~5 | 5~20 | 20 이상 |
| ai_scored_queue | 0~3 | 3~10 | 10 이상 |
| error_queue | 0 | 1~5 | 5 이상 |

`telegram_queue`가 계속 쌓인다면 ai-engine이 처리를 못하고 있는 것입니다. ai-engine 로그를 즉시 확인하세요.

### 7.2 로그 분석

#### 로그 파일 위치

```
ai-engine/logs/ai-engine.log    ← AI 엔진 로그 (가장 중요)
websocket-listener/logs/ws.log  ← WebSocket 연결 상태
```

#### 중요 로그 패턴

```bash
# Claude API 호출 성공 확인
grep '"module": "analyzer"' ai-engine.log | tail -20

# 규칙 스코어 분포 확인
grep '"module": "scorer"' ai-engine.log | grep '"score"' | tail -50

# 오류 로그만 추출
grep 'ERROR\|CRITICAL' ai-engine.log | tail -30

# 처리된 신호 수 통계
grep '발행 완료' ai-engine.log | wc -l
```

#### 헬스체크 엔드포인트

```bash
# ai-engine 헬스체크
curl http://localhost:8082/health
# 정상: {"status":"UP","redis_connected":true,...}

# websocket-listener 헬스체크
curl http://localhost:8081/health

# api-orchestrator 헬스체크 (Spring Actuator)
curl http://localhost:8080/actuator/health
```

### 7.3 성과 추적

#### PostgreSQL 쿼리 – 오늘 신호 성과

```sql
-- 오늘 전략별 신호 수
SELECT strategy, signal_status, COUNT(*) as cnt
FROM trading_signals
WHERE DATE(created_at) = CURRENT_DATE
GROUP BY strategy, signal_status
ORDER BY cnt DESC;

-- 평균 스코어
SELECT strategy, AVG(signal_score) as avg_score
FROM trading_signals
WHERE DATE(created_at) = CURRENT_DATE
GROUP BY strategy;
```

#### Redis 일별 요약

```bash
# 오늘 날짜 형식 (YYYYMMDD)
TODAY=$(date +%Y%m%d)

# Claude 사용량 확인
redis-cli GET "claude:daily_calls:$TODAY"
redis-cli GET "claude:daily_tokens:$TODAY"
```

### 7.4 Claude API 사용량 모니터링

#### 일별 사용량 확인

Telegram에서 `/상태` 명령 사용 (가장 간단)
또는 Redis CLI:

```bash
TODAY=$(date +%Y%m%d)
echo "오늘 Claude 호출 수: $(redis-cli GET claude:daily_calls:$TODAY)"
echo "오늘 토큰 사용량: $(redis-cli GET claude:daily_tokens:$TODAY)"
```

#### 비용 계산

```
토큰 사용량 × $3/1M(입력) or $15/1M(출력) = 달러 비용
평균 입력:출력 비율 = 약 3:1
예) 20,000 토큰/일 = (15,000 × $3 + 5,000 × $15) / 1,000,000 ≈ $0.12/일
```

### 7.5 Kiwoom API 연결 상태 확인

```bash
# 토큰 유효 여부 확인
redis-cli GET kiwoom:token | head -c 20

# API 헬스체크 (api-orchestrator 통해)
curl http://localhost:8080/api/health

# 토큰 만료 시간 확인
redis-cli TTL kiwoom:token
```

### 7.6 장애 대응 절차

#### 장애 레벨 분류

| 레벨 | 증상 | 영향 |
|------|------|------|
| P1 (심각) | Redis 연결 실패 | 모든 신호 처리 중단 |
| P1 (심각) | Claude API 키 오류 | AI 분석 불가 |
| P2 (높음) | WebSocket 연결 끊김 | 실시간 데이터 없음 |
| P2 (높음) | telegram_queue 폭발 | 신호 지연 |
| P3 (보통) | 특정 전략 오류 | 해당 전략 신호 없음 |

#### P1 장애 대응

```bash
# 1. Redis 복구
sudo systemctl restart redis-server
# Docker: docker restart sma-redis

# 2. ai-engine 재시작 (Redis 연결 자동 재시도)
# ai-engine은 RedisConnectionManager로 자동 재연결을 시도하나,
# 장시간 연결 끊김 시 수동 재시작 권장
kill -9 $(pgrep -f engine.py)
cd ai-engine && python engine.py &
```

#### P2 장애 대응

```bash
# WebSocket 재연결 (Telegram 명령)
/ws종료
/ws시작

# 또는 websocket-listener 재시작
kill -9 $(pgrep -f "main.py")
cd websocket-listener && python main.py &
```

#### 전체 시스템 재시작 절차

```bash
# 역순으로 종료
pkill -f telegram-bot
pkill -f engine.py
pkill -f main.py
# api-orchestrator는 마지막에 종료 (토큰 등 정리)

# 순서대로 재시작
cd websocket-listener && python main.py &
cd ai-engine && python engine.py &
cd telegram-bot && npm start &
```

---

## 8. 고급 설정

### 8.1 전략 활성화/비활성화

Python 전략 스캐너(`ENABLE_STRATEGY_SCANNER=true`)를 사용하는 경우, 특정 전략을 비활성화하려면 `strategy_runner.py`에서 해당 전략 블록을 주석 처리합니다.

Java api-orchestrator에서는 `StrategyService.java`의 스케줄러 주석 처리 또는 `application.yml` 설정으로 제어합니다.

### 8.2 스코어 임계값 조정

#### MIN_SCORE (최소 신호 전달 점수)

```bash
# ai-engine/.env
AI_SCORE_THRESHOLD=60.0   # 기본값 (이 이상이어야 Claude 호출)
```

#### Claude 호출 전략별 임계값

`scorer.py`의 `CLAUDE_THRESHOLDS` 딕셔너리를 수정:

```python
CLAUDE_THRESHOLDS = {
    "S1_GAP_OPEN":      70,  # 높일수록 더 엄격한 필터
    "S2_VI_PULLBACK":   65,
    "S3_INST_FRGN":     60,
    "S4_BIG_CANDLE":    75,
    "S5_PROG_FRGN":     65,
    "S6_THEME_LAGGARD": 60,
    "S7_AUCTION":       70,
}
```

**주의**: 임계값을 올리면 Claude API 비용이 절감되지만 신호 수가 줄어듭니다. 내리면 반대입니다.

### 8.3 신호 중복 TTL 설정

#### Java api-orchestrator에서 설정

`application.yml`:
```yaml
trading:
  dedup:
    ttl:
      S1_GAP_OPEN: 1800      # 30분
      S2_VI_PULLBACK: 3600   # 1시간
      S7_AUCTION: 7200       # 2시간
      default: 3600           # 기본 1시간
```

### 8.4 동시 전략 실행 수 조정

```bash
# ai-engine/.env
MAX_CONCURRENT_STRATEGIES=3   # 기본값 (3개 전략 동시 실행)
```

높이면 병렬로 더 많은 전략이 실행되지만 API 요청이 집중될 수 있습니다. 낮추면 안정적이지만 스캔이 느려집니다.

### 8.5 Redis 재연결 설정

`redis_reader.py`의 `RedisConnectionManager` 클래스에서 지수 백오프 파라미터를 조정할 수 있습니다:

```python
class RedisConnectionManager:
    _BACKOFF_BASE = 1    # 초기 대기 시간 (초)
    _BACKOFF_MAX  = 60   # 최대 대기 시간 (초)
    # 재연결 순서: 1s → 2s → 4s → 8s → 16s → 32s → 60s(cap)
```

---

## 9. 개발자 가이드

### 9.1 새 전략 추가 방법

#### Step 1: 전략 파일 생성

`ai-engine/strategy_8_xxxxx.py` 형식으로 생성:

```python
"""전술 8: 설명
타이밍: HH:MM ~ HH:MM
진입 조건: ...
"""

async def scan_xxxxx(token: str, market: str = "000", rdb=None) -> list:
    """
    Returns:
        list of signals with fields:
          - stk_cd: str
          - strategy: "S8_XXXXX"
          - entry_type: str
          - target_pct: float
          - stop_pct: float
          - [전략별 지표 필드들]
    """
    results = []
    # 구현...
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
```

#### Step 2: scorer.py에 스코어링 로직 추가

`rule_score()` 함수의 `match strategy:` 블록에 추가:

```python
case "S8_XXXXX":
    # 점수 계산 로직
    score += ...
```

`CLAUDE_THRESHOLDS` 딕셔너리에도 추가:

```python
CLAUDE_THRESHOLDS = {
    ...
    "S8_XXXXX": 65,
}
```

#### Step 3: strategy_runner.py에 등록

```python
# 시간대 조건에 맞게 추가
if datetime.time(9, 30) <= now <= datetime.time(14, 0):
    async def _s8():
        try:
            from strategy_8_xxxxx import scan_xxxxx
            signals = await scan_xxxxx(token, "000", rdb=rdb)
            await _push_signals(rdb, signals, "S8_XXXXX")
        except Exception as e:
            logger.error("[Runner] S8 스캔 오류: %s", e)
    tasks.append(_run_strategy_with_semaphore("S8", _s8()))
```

#### Step 4: analyzer.py에 프롬프트 추가

`_build_user_message()` 함수에 전략 분기 추가:

```python
elif strategy == "S8_XXXXX":
    return (
        f"[전략명] 신호 평가:\n"
        f"종목: {stk_nm}({stk_cd}), [지표]: ..., 규칙점수: {rule_score}/100\n"
        f"진입 적합성을 JSON으로 답하세요."
    )
```

### 9.2 스코어링 로직 커스터마이징

#### 공통 패널티 조정

`scorer.py`의 `rule_score()` 함수 하단:

```python
# 현재 패널티
if flu_rt > 15:   score -= 20
elif flu_rt > 10: score -= 10
if flu_rt < -5:   score -= 15
```

추가 패널티 예시:
```python
# 거래량 급감 패널티
if ctx.get("vol_ratio", 1.0) < 0.3:
    score -= 10  # 거래량이 평소의 30% 미만이면 신뢰성 낮음
```

### 9.3 테스트 실행

#### Python 테스트 (ai-engine)

```bash
cd ai-engine

# 전체 테스트 실행
python -m pytest tests/ -v

# 특정 파일만
python -m pytest tests/test_scorer.py -v

# 커버리지 리포트
python -m pytest tests/ --cov=. --cov-report=html

# 빠른 테스트 (실패 즉시 중단)
python -m pytest tests/ -x
```

#### Node.js 테스트 (telegram-bot)

```bash
cd telegram-bot

# formatter 테스트
node tests/test_formatter.js

# signals 테스트
node tests/test_signals_rate_limiter.js
```

### 9.4 코드 구조 설명

#### ai-engine 의존성 그래프

```
engine.py
  ├── queue_worker.py
  │     ├── analyzer.py
  │     │     └── (anthropic SDK)
  │     ├── scorer.py
  │     └── redis_reader.py
  │           └── (redis.asyncio)
  └── strategy_runner.py
        ├── strategy_1_gap_opening.py
        ├── strategy_2_vi_pullback.py
        │     └── http_utils.py
        ├── strategy_3_inst_foreign.py
        ├── strategy_4_big_candle.py
        ├── strategy_5_program_buy.py
        ├── strategy_6_theme.py
        │     └── http_utils.py
        └── strategy_7_auction.py
```

#### 신호 데이터 스키마

`telegram_queue` 및 `ai_scored_queue`의 JSON 필드:

```python
{
    # 공통 필드 (모든 전략)
    "strategy": "S1_GAP_OPEN",   # 전략 코드
    "stk_cd": "005930",          # 종목 코드
    "stk_nm": "삼성전자",         # 종목명
    "entry_type": "시초가_시장가", # 진입 방식
    "target_pct": 4.0,           # 목표 수익률
    "stop_pct": -2.0,            # 손절 수익률
    "signal_time": "2026-03-21T09:00:05", # 신호 시각
    "cur_prc": 84300,            # 현재가

    # AI 분석 결과 (ai_scored_queue에 추가)
    "rule_score": 75.0,          # 규칙 기반 점수
    "ai_score": 78.0,            # Claude AI 점수
    "action": "ENTER",           # 행동 (ENTER/HOLD/CANCEL)
    "confidence": "HIGH",        # 신뢰도
    "ai_reason": "강한 갭상승...", # AI 분석 근거
    "adjusted_target_pct": 3.5,  # AI 조정 목표 수익률 (선택)
    "adjusted_stop_pct": -2.0,   # AI 조정 손절 수익률 (선택)

    # 전략별 추가 필드 (예: S1)
    "gap_pct": 3.85,
    "cntr_strength": 143.0,
}
```

---

## 10. 법적 고지 및 면책사항

### 10.1 투자 위험 고지

**SMA(StockMate AI)는 매매 신호를 제공하는 보조 도구일 뿐이며, 투자 자문 서비스가 아닙니다.**

주식 투자에는 원금 손실의 위험이 있습니다. SMA가 제공하는 신호는 AI와 규칙 기반의 판단이며, 시장 상황의 급변, 예기치 못한 뉴스, 시스템 오류 등으로 인해 손실이 발생할 수 있습니다.

**투자로 인한 모든 손익의 책임은 사용자 본인에게 있습니다.**

### 10.2 시스템 한계

1. **과거 데이터 부재**: SMA의 예상 수익률 및 승률은 추정치이며 과거 백테스트 결과가 아닙니다.
2. **데이터 지연**: WebSocket 데이터 또는 API 응답 지연으로 신호가 늦게 발생할 수 있습니다.
3. **API 장애**: 키움 API, Claude API, Redis 등 외부 시스템 장애 시 신호가 발생하지 않을 수 있습니다.
4. **모델 한계**: Claude AI는 주식 시장 전문가가 아니므로 분석이 부정확할 수 있습니다.

### 10.3 키움 API 이용 약관 준수

키움 Open API+를 이용하는 모든 사용자는 키움증권의 API 이용약관을 반드시 준수해야 합니다. SMA를 통한 과도한 API 요청은 이용 제한의 원인이 될 수 있습니다.

### 10.4 개인정보 처리

SMA는 사용자의 개인정보를 수집하지 않습니다. 단, Redis에 저장되는 거래 신호, 설정 데이터는 사용자의 관리 하에 있으며 적절한 보안 설정이 필요합니다.

### 10.5 오픈소스 라이선스

SMA는 다음 오픈소스 소프트웨어를 사용합니다:
- Spring Boot (Apache 2.0)
- Redis (BSD)
- Python anthropic SDK (MIT)
- Telegraf (MIT)
- ioredis (MIT)

### 10.6 지원 및 문의

- 버그 리포트: GitHub Issues
- 기능 요청: GitHub Discussions
- 긴급 장애: 시스템 관리자에게 직접 문의

---

*이 사용설명서는 SMA v1.0.0 기준으로 작성되었습니다.*
*최종 업데이트: 2026-03-21*
*작성: Claude Sonnet 4.6*
