# SMA (StockMate AI) 사용설명서

**버전**: 2.1.0
**작성일**: 2026-03-23
**대상**: 키움 API를 이용한 한국 주식 단기 매매 자동화 시스템 사용자

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [설치 및 환경 설정](#2-설치-및-환경-설정)
3. [13가지 매매 전략 상세 설명](#3-13가지-매매-전략-상세-설명)
4. [AI 스코어링 시스템](#4-ai-스코어링-시스템)
5. [Telegram Bot 사용법](#5-telegram-bot-사용법)
6. [뉴스 기반 매매 제어](#6-뉴스-기반-매매-제어)
7. [경제 캘린더 연동](#7-경제-캘린더-연동)
8. [신호 성과 추적](#8-신호-성과-추적)
9. [실전 매매 가이드](#9-실전-매매-가이드)
10. [시스템 모니터링 및 운영](#10-시스템-모니터링-및-운영)
11. [고급 설정](#11-고급-설정)
12. [개발자 가이드](#12-개발자-가이드)
13. [법적 고지 및 면책사항](#13-법적-고지-및-면책사항)

---

## 1. 시스템 개요

### 1.1 SMA란?

**SMA (StockMate AI)**는 한국 주식 시장에 특화된 자동화 매매 신호 생성 시스템입니다. 키움증권 REST API 및 WebSocket API를 통해 실시간 시세 데이터를 수집하고, 최대 13가지 독립적인 매매 전략을 동시에 실행하여 진입 신호를 탐지합니다. 탐지된 신호는 Claude AI(Anthropic)의 자연어 분석을 거쳐 최종 점수화되며, Telegram을 통해 사용자에게 실시간으로 전달됩니다.

SMA는 완전 자동화 매매 시스템이 아닙니다. SMA는 **매매 신호 추천 시스템**입니다. 최종 매매 결정은 항상 사용자가 직접 내립니다.

#### 주요 특징

- **실시간 신호**: 키움 WebSocket(0B 체결, 0H 예상체결, 0D 호가, 1h VI 이벤트)을 통한 밀리초 단위 데이터 수신
- **13가지 전략**: 갭상승·VI 눌림목·기관/외인·장대양봉·프로그램매수·테마·동시호가(데이트레이딩 7개) + 골든크로스·눌림목스윙·신고가돌파·외국인연속·종가강도·박스권돌파(스윙 6개)
- **이중 필터**: 규칙 기반 1차 스코어링 + Claude AI 2차 분석으로 오신호 최소화
- **비용 최적화**: 규칙 점수 미달 신호는 Claude API 호출 없이 자동 제거
- **뉴스 기반 매매 제어**: Claude AI가 30분마다 금융 뉴스를 분석하여 시장 심리 악화 시 자동 알림 및 사용자 컨펌 후 매매 중단
- **경제 캘린더 연동**: FOMC·한은 금통위·CPI 등 주요 이벤트 2시간 전 자동 경고 및 신중 매매 전환
- **신호 성과 추적**: 발행 신호의 가상 P&L(WIN/LOSS/EXPIRED)을 장 중 10분마다 자동 평가
- **Telegram 22개 명령**: 신호 조회부터 매매 제어·경제 캘린더·관심 종목까지 모바일 완전 제어

### 1.2 핵심 가치 제안

| 항목 | 기존 수동 매매 | HTS/MTS 조건검색 | SMA |
|------|--------------|----------------|-----|
| 모니터링 범위 | 1~5개 종목 | 조건 설정된 종목 | KOSPI+KOSDAQ 전체 |
| 신호 속도 | 느림 | 빠름 | 빠름 (WebSocket) |
| 전략 다양성 | 제한적 | 단일 조건 위주 | 13가지 복합 전략 |
| AI 분석 | 없음 | 없음 | Claude AI 정성 분석 |
| 리스크 평가 | 주관적 | 없음 | 규칙+AI 이중 평가 |
| 뉴스 연동 | 없음 | 없음 | 30분 주기 AI 뉴스 분석 |
| 실시간 알림 | 없음 | 제한적 | Telegram 즉시 발송 |

### 1.3 시스템 아키텍처 전체 흐름도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     SMA (StockMate AI) Architecture v2                    │
└─────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────┐
  │  Kiwoom API      │  REST API + WebSocket
  │  (Korean Broker) │  (0B 체결, 0H 예상, 0D 호가, 1h VI)
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────────┐
  │  websocket-listener  │  Python asyncio
  │  (GRP 5–8)          │  ws_client.py / redis_writer.py
  │                      │  health_server.py (:8081)
  └────────┬─────────────┘
           │  Redis: ws:tick, ws:hoga, ws:expected, vi_watch_queue
           ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                      Redis (Central Broker)                       │
  │                                                                  │
  │  실시간 데이터:  ws:tick, ws:hoga, ws:expected, vi:*             │
  │  제어 큐:       vi_watch_queue, telegram_queue, ai_scored_queue  │
  │  뉴스 제어:     news:trading_control, news:prev_control          │
  │               news:analysis, news:sector_recommend               │
  │  뉴스 큐:       news_alert_queue                                 │
  │  신호 제어:     signal:stock:{cd}, signal:daily_count:{date}     │
  │               signal:sector:{sector}                             │
  │  캘린더:        calendar:pre_event                               │
  │  모니터링:      monitor:ws_reconnect_count, error_queue          │
  └───────┬──────────────────────────┬──────────────────────────────┘
          │                          │
          ▼                          ▼
  ┌─────────────────────┐   ┌───────────────────────────────────────┐
  │  api-orchestrator   │   │          ai-engine (Python)            │
  │  (Java Spring Boot) │   │                                       │
  │                     │◄──┤  1. telegram_queue 폴링               │
  │  전략 S1~S7 (Java)  │   │  2. 뉴스 PAUSE 확인 → CANCEL         │
  │  성과 추적 스케쥴러  │   │  3. rule_score() 1차 스코어링          │
  │  경제 캘린더 스케쥴러│   │  4. Claude AI 2차 분석                │
  │  뉴스 알림 스케쥴러  │   │  5. ai_scored_queue LPUSH             │
  │  데이터 품질 스케쥴러│   │                                       │
  │                     │   │  [선택] strategy_runner.py            │
  │  REST API :8080      │   │   └─ S1~S7, S10, S11, S12 Python 실행│
  └──────────┬──────────┘   │                                       │
             │              │  [선택] news_scheduler.py             │
             │              │   └─ 30분마다 뉴스 수집·AI 분석        │
             │              │                                       │
             │              │  [선택] monitor_worker.py             │
             │              │   └─ 60초 시스템 메트릭 감시           │
             │              │                                       │
             │              │  Health: http://localhost:8082/health  │
             │              └──────────────┬────────────────────────┘
             │                             │
             └──────────────┬──────────────┘
                            │  ai_scored_queue →
                            ▼
                   ┌────────────────────┐
                   │   telegram-bot     │
                   │   (Node.js)        │
                   │                   │
                   │  신호 타입별 처리:  │
                   │  - 매매 신호        │
                   │  - PAUSE_CONFIRM   │
                   │  - NEWS_ALERT      │
                   │  - CALENDAR_ALERT  │
                   │  - SECTOR_OVERHEAT │
                   │  - SYSTEM_ALERT    │
                   │  - MARKET_OPEN     │
                   │  - MIDDAY_REPORT   │
                   │  - DAILY_REPORT    │
                   └────────┬───────────┘
                            │
                            ▼
                   ┌────────────────────┐
                   │  사용자 Telegram   │
                   │  (모바일/PC)       │
                   │                   │
                   │  신호 수신 + 22개  │
                   │  명령어 제어       │
                   └────────────────────┘
```

### 1.4 데이터 흐름 상세

#### Phase 1: 실시간 데이터 수집 (websocket-listener)

키움 WebSocket GRP 5~8에서 4가지 데이터 타입 수신:

- **0B (체결)**: 현재가, 등락률, 체결강도, 거래량 → `ws:tick:{stk_cd}` (TTL 30초)
- **0H (예상체결)**: 예상체결가, 예상등락률 → `ws:expected:{stk_cd}` (TTL 60초)
- **0D (호가잔량)**: 매수/매도 호가잔량 합계 → `ws:hoga:{stk_cd}` (TTL 10초)
- **1h (VI 이벤트)**: 정적/동적 VI 발동·해제 → `vi_watch_queue` LPUSH

#### Phase 2: 전략 실행 및 신호 생성 (api-orchestrator)

Java TradingScheduler가 스케줄에 따라 S1~S7을 실행합니다:

- 각 전략은 키움 REST API를 호출하여 후보 종목 탐색
- 조건 충족 종목을 `telegram_queue`에 LPUSH
- 종목 쿨다운(30분), 섹터 과열 제어(1시간 3건), 일일 상한(기본 30건) 자동 적용
- 신호 발행 시 `signal:stock:{stk_cd}`, `signal:sector:{sector}` Redis 키 설정

#### Phase 3: AI 분석 (ai-engine)

`telegram_queue`를 2초 간격으로 폴링:

1. RPOP으로 신호 꺼냄
2. `news:trading_control == "PAUSE"` 확인 → PAUSE 시 즉시 CANCEL
3. `FORCE_CLOSE`, `DAILY_REPORT` 특수 타입은 AI 없이 통과
4. `rule_score()` 1차 스코어링 (0~100점)
5. 전략별 임계값 미달 → CANCEL (Claude API 비용 0)
6. `analyze_signal()` → Claude API 호출
7. 결과를 `ai_scored_queue`에 LPUSH

#### Phase 4: Telegram 발송 (telegram-bot)

`ai_scored_queue`를 폴링하여 타입별 처리:

- 매매 신호: `action == 'ENTER'` AND `ai_score >= MIN_AI_SCORE(기본 65)` → 발송
- 특수 타입(NEWS_ALERT, CALENDAR_ALERT 등): 즉시 발송
- PAUSE_CONFIRM_REQUEST: 인라인 키보드 메시지 발송

### 1.5 기술 스택 및 의존성

| 모듈 | 언어/런타임 | 핵심 라이브러리 | 포트 |
|------|-----------|----------------|------|
| api-orchestrator | Java 25, Spring Boot 4.0 | Spring WebFlux, Spring Data Redis, OkHttp | 8080 |
| websocket-listener | Python 3.10+ | websockets 12.0, aiohttp 3.9.5, redis 5.x | 8081 |
| ai-engine | Python 3.10+ | anthropic 0.25.0, redis 5.x, aiohttp | 8082 |
| telegram-bot | Node.js 18+ | Telegraf 4.x, ioredis, axios | - |
| Redis | 7.x | - | 6379 |
| PostgreSQL | 15.x | - | 5432 |

---

## 2. 설치 및 환경 설정

### 2.1 사전 요구사항

#### 소프트웨어 요구사항

```
Python     3.10 이상 (3.12 권장)
Java       21 이상 (25 권장)
Node.js    18 이상 (20 LTS 권장)
Redis      7.0 이상
PostgreSQL 15 이상
```

#### 외부 서비스 계정

1. **키움증권 API 계정**: Open API+ 신청 (키움증권 공식 사이트)
2. **Anthropic Claude API 키**: console.anthropic.com 에서 발급
3. **Telegram Bot Token**: BotFather를 통해 발급

#### 시스템 리소스 권장

```
CPU: 4코어 이상
RAM: 8GB 이상 (모든 모듈 동시 실행 기준)
SSD: 20GB 이상 (로그, DB 포함)
OS: Linux (Ubuntu 22.04 권장) 또는 Windows 10/11
```

### 2.2 환경 변수 전체 목록

#### api-orchestrator `.env`

```bash
# Kiwoom API
KIWOOM_APP_KEY=your_app_key_here
KIWOOM_APP_SECRET=your_app_secret_here
KIWOOM_BASE_URL=https://api.kiwoom.com
KIWOOM_WS_URL=wss://api.kiwoom.com:10000

# Claude AI
CLAUDE_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-sonnet-4-6

# Telegram (알림 전용)
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

# 신호 제어 (Feature 4)
MAX_DAILY_SIGNALS=30               # 일일 전체 신호 상한
SECTOR_OVERHEAT_THRESHOLD=3        # 섹터 과열 임계값 (1시간 내)
STOCK_COOLDOWN_MINUTES=30          # 종목 크로스-전략 쿨다운
```

#### ai-engine `.env`

```bash
# Claude AI
CLAUDE_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-sonnet-4-6

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# 동작 설정
LOG_LEVEL=INFO
POLL_INTERVAL_SEC=2.0
MAX_CLAUDE_CALLS_PER_DAY=100
AI_SCORE_THRESHOLD=60.0

# Python 전략 스캐너 (S1~S7, S10~S12 직접 실행)
ENABLE_STRATEGY_SCANNER=false
STRATEGY_SCAN_INTERVAL_SEC=60.0
MAX_CONCURRENT_STRATEGIES=3

# 뉴스 스케쥴러 (Feature: 뉴스 기반 매매 제어)
NEWS_ENABLED=true
NEWS_INTERVAL_MIN=30               # 뉴스 수집 주기 (분)
NEWS_MARKET_ONLY=false             # 장 중에만 실행 여부

# 모니터링 (Feature 5)
ENABLE_MONITOR=true
MONITOR_INTERVAL_SEC=60

# Kiwoom (전략 스캐너 활성화 시 필요)
KIWOOM_BASE_URL=https://api.kiwoom.com

# 헬스체크 포트
AI_HEALTH_PORT=8082
```

#### websocket-listener `.env`

```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password
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
POLL_INTERVAL_MS=2000

# API (Java api-orchestrator)
KIWOOM_API_BASE_URL=http://localhost:8080
```

### 2.3 PostgreSQL 초기화

```sql
CREATE USER sma_user WITH PASSWORD 'your_password';
CREATE DATABASE "SMA" OWNER sma_user;
GRANT ALL PRIVILEGES ON DATABASE "SMA" TO sma_user;
```

Spring Boot 최초 기동 시 `hibernate.ddl-auto: create` 설정으로 테이블 자동 생성됩니다.

**운영 환경에서는 반드시 `update`로 변경하십시오.**

생성되는 테이블:
- `trading_signals` – 모든 발행 신호 및 가상 P&L
- `kiwoom_token` – API 토큰
- `vi_events` – VI 이벤트 이력
- `ws_tick_data` – WebSocket 체결 데이터 (일별 배치 저장)
- `economic_events` – 경제 캘린더 이벤트
- `news_analysis` – AI 뉴스 분석 결과

### 2.4 각 모듈 실행 순서

#### 권장: stockmate.sh 통합 실행 (PM2)

```bash
# PM2 최초 설치 (한 번만)
npm install -g pm2

# 전체 시작 – api-orchestrator 기동 후 Java /health 확인 → PM2 서비스 자동 시작
./stockmate.sh

# 기타 명령
./stockmate.sh stop     # 전체 중지
./stockmate.sh restart  # 재시작
./stockmate.sh status   # 상태 확인
./stockmate.sh logs     # PM2 통합 로그

# 서버 재부팅 자동 시작 등록 (최초 1회)
pm2 startup && pm2 save
```

#### 수동 실행 순서 (개발·디버깅용)

모듈 간 의존성 → 반드시 아래 순서로 기동:

```
1단계: Redis & PostgreSQL (인프라)
2단계: api-orchestrator (토큰 발급, 전략 실행, 스케쥴러)
3단계: websocket-listener (실시간 데이터)
4단계: ai-engine (AI 분석, 뉴스 스케쥴러)
5단계: telegram-bot (신호 발송, 명령어 처리)
```

```bash
# 2단계: api-orchestrator
cd api-orchestrator && ./gradlew bootRun
curl http://localhost:8080/api/trading/health

# 3단계: websocket-listener
cd websocket-listener && python main.py

# 4단계: ai-engine
cd ai-engine && python engine.py

# 5단계: telegram-bot
cd telegram-bot && npm start
```

### 2.5 경제 캘린더 초기 데이터 입력

시스템 기동 후 2026년 주요 경제 이벤트를 등록합니다:

```bash
# FOMC 금리 결정 (예시)
curl -X POST http://localhost:8080/api/trading/calendar/event \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"FOMC 금리결정","event_type":"FED","event_date":"2026-03-19","event_time":"03:00","expected_impact":"HIGH"}'

# 한은 금통위
curl -X POST http://localhost:8080/api/trading/calendar/event \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"한은 금통위","event_type":"BOK","event_date":"2026-04-17","event_time":"10:00","expected_impact":"HIGH"}'

# 미국 CPI
curl -X POST http://localhost:8080/api/trading/calendar/event \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"미국 CPI","event_type":"CPI","event_date":"2026-04-10","event_time":"21:30","expected_impact":"HIGH"}'
```

---

## 3. 13가지 매매 전략 상세 설명

### 전략 분류 개요

| 분류 | 전략 | 유형 | 활성화 시간 | 상태 |
|------|------|------|------------|------|
| 데이트레이딩 | S1 갭상승 시초가 | 스캘핑 | 08:30~09:10 | ✅ 활성 |
| 데이트레이딩 | S2 VI 눌림목 | 단기 | 09:00~15:20 (이벤트) | ✅ 활성 |
| 데이트레이딩 | S3 기관/외인 순매수 | 단기 | 09:30~14:30 | ✅ 활성 |
| 데이트레이딩 | S4 장대양봉 | 추격 | 09:30~14:30 | ✅ 활성 |
| 데이트레이딩 | S5 프로그램+외인 | 단기 | 10:00~14:00 | ✅ 활성 |
| 데이트레이딩 | S6 테마 후발주 | 모멘텀 | 09:30~13:00 | ✅ 활성 |
| 데이트레이딩 | S7 장전 동시호가 | 스캘핑 | 08:30~09:00 | ✅ 활성 |
| 스윙 | S8 골든크로스 스윙 | 3~7일 | 09:30~14:30 | ⏳ HTS 조건검색 설정 후 활성 |
| 스윙 | S9 눌림목 지지 반등 | 3~5일 | 09:30~14:30 | ⏳ HTS 조건검색 설정 후 활성 |
| 스윙 | S10 52주 신고가 돌파 | 5~10일 | 09:30~14:30 | ✅ 활성 |
| 스윙 | S11 외국인 연속 순매수 | 5~7일 | 09:30~14:30 | ✅ 활성 |
| 스윙 | S12 종가 강도 확인 매수 | 2~5일 | 14:30~14:50 | ✅ 활성 |
| 스윙 | S13 거래량 폭발 박스권 돌파 | 3~7일 | 09:30~14:30 | ⏳ HTS 조건검색 설정 후 활성 |

**주의**: S8, S9, S13은 HTS(영웅문) 조건검색 기능을 통한 종목 선정이 필요합니다. `COND_NM`/`COND_ID` 설정 전까지 자동으로 건너뜁니다.

S1~S7은 Java api-orchestrator가 메인으로 실행합니다. Python 전략 스캐너(`ENABLE_STRATEGY_SCANNER=true`)를 활성화하면 S1~S7, S10~S12를 Python에서도 실행할 수 있습니다.

---

### 3.1 S1 전략: 갭상승 + 체결강도 돌파

#### 전략 개요

전일 장마감 후 발생한 호재나 수급 변화로 당일 아침 예상 시초가가 전일 종가보다 높게 형성되는 갭상승 종목을 매수하는 전략입니다. 3~5% 갭 구간은 '골든 갭'으로 불리며 과도하지 않으면서도 충분한 상승 모멘텀을 제공합니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| 갭상승률 | 3~15% |
| 체결강도 | ≥ 130% |
| 호가잔량 비율 | ≥ 1.5 |

#### 스코어 산정

```
갭:  3~5% → +20점 / 5~8% → +15점 / 8~15% → +10점 / 15% 초과 → -10점
체결강도: >150 → +30 / >130 → +20 / >110 → +10
호가비율: >2.0 → +25 / >1.5 → +20 / >1.3 → +10
신호 내 체결강도 보너스: >150 → +10 / >130 → +5
```

#### 손절/익절 기준

| 구분 | 기준 |
|------|------|
| 목표가 | +4.0% |
| 손절가 | -2.0% |
| R:R | 1:2 |

---

### 3.2 S2 전략: VI 발동 후 눌림목 매수

#### 전략 개요

VI(Volatility Interruption) 해제 후 가격이 일시적으로 하락하는 '눌림목' 구간을 매수하는 전략입니다. VI 발동은 매수 수급이 강하다는 신호이며, 눌림목 구간은 추가 매수의 기회입니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| VI 발동 타입 | 동적 VI 우선 |
| 눌림목 범위 | -1% ~ -3% |
| 체결강도 | ≥ 110% |
| 호가비율 | ≥ 1.3 |

#### VI 감시 메커니즘

1. WebSocket GRP 7 (1h 타입)에서 VI 이벤트 수신
2. `vi:{stk_cd}` Redis Hash에 저장 (TTL 1시간)
3. `vi_watch_queue`에 등록 (10분 감시)
4. `ViWatchService`가 눌림목 감지 시 신호 발행

#### 손절/익절

| 목표가 | +3.0% | 손절가 | -2.0% |
|--------|-------|--------|-------|

---

### 3.3 S3 전략: 기관/외국인 순매수 연속

#### 전략 개요

기관·외국인이 동시에 특정 종목을 연속으로 순매수하는 경우 '스마트 머니' 집중 유입 신호입니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| 동시 순매수 | 기관+외인 동시 (ka10063) |
| 연속 순매수 일수 | ≥ 3일 (ka10131) |
| 당일 거래량 | 전일 동시간 대비 ≥ 1.5배 |

#### 손절/익절

| 목표가 | +3.5% | 손절가 | -2.0% |
|--------|-------|--------|-------|

---

### 3.4 S4 전략: 장대양봉 캔들 패턴

#### 전략 개요

5분봉 차트에서 강한 매수세로 형성된 장대양봉 직후의 추격 매수 전략입니다. 전일 거래량 대비 5배 이상 거래량 동반이 핵심 조건입니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| 양봉 몸통 비율 | ≥ 70% |
| 상승폭 | ≥ 3% |
| 거래량 비율 | ≥ 5배 |
| 체결강도 | ≥ 140% |

#### 손절/익절

| 목표가 | +4.0% | 손절가 | -2.5% |
|--------|-------|--------|-------|

---

### 3.5 S5 전략: 프로그램 매수 유입

#### 전략 개요

프로그램 매매(차익거래 연계 기계적 대규모 매수)와 외국인 동반 매수를 탐지하는 전략입니다. KOSPI200, KOSDAQ150 편입 종목에서 주로 발생합니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| 프로그램 순매수 상위 | 50위 이내 (ka90003) |
| 외국인/기관 동시 포함 | ka90009 교차 확인 |

#### 손절/익절

| 목표가 | +3.0% | 손절가 | -2.0% |
|--------|-------|--------|-------|

---

### 3.6 S6 전략: 테마/섹터 모멘텀 후발주

#### 전략 개요

특정 테마(AI 반도체, 2차전지 등)의 선도주가 강하게 오를 때, 같은 테마의 아직 덜 오른 후발주를 매수하는 전략입니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| 테마 등락률 | ≥ 2.0% (ka90001) |
| 개별 종목 등락률 | 0.5% ~ 테마 상위 30% 미만 |
| 체결강도 | ≥ 120% |

#### 손절/익절

| 목표가 | min(테마 등락률 × 0.6, 5.0%) | 손절가 | -2.0% |
|--------|------------------------------|--------|-------|

---

### 3.7 S7 전략: 장전 동시호가 급등

#### 전략 개요

장전 동시호가(08:00~09:00)에서 예상 시초가가 전일 종가 대비 +2~10% 높고 매수 호가잔량이 압도적인 종목을 선별합니다.

#### 매수 신호 조건

| 조건 | 기준값 |
|------|--------|
| 예상 갭 | +2% ~ +10% |
| 매수/매도 호가비율 | ≥ 2.0 |
| 예상 거래량 순위 | 50위 이내 (ka10029) |

#### 사전 필터링 (3중 교집합)

1. ka10029: 갭 2~10% 종목
2. ka10030: 거래대금 10억 이상 종목
3. 호가 매수비율 200% 이상 종목

#### 손절/익절

| 목표가 | min(gap × 0.8, 5.0%) | 손절가 | -2.0% |
|--------|----------------------|--------|-------|

---

### 3.8 S8 전략: 20일선 골든크로스 스윙 (HTS 조건검색 필요)

#### 전략 개요

5일 이동평균이 20일 이동평균을 상향 돌파하는 '골든크로스' 당일, 거래량 증가 및 RSI 적정 구간을 확인하여 진입하는 스윙 전략입니다.

#### 진입 조건

- 5일 MA가 20일 MA 상향 돌파 (당일 골든크로스)
- 당일 거래량 ≥ 20일 평균 거래량 × 1.5
- RSI(14) 40~65 구간
- 현재가가 60일 MA 기준 -5% 이내
- 시가총액 500억 이상

#### 활성화 방법

HTS(영웅문) 조건검색기에서 위 조건으로 조건식 생성 후 `strategy_8_golden_cross.py`의 `COND_NM` / `COND_ID` 환경변수 설정.

| 목표 보유기간 | 3~7거래일 | 목표가 | +8.0% | 손절가 | -4.0% |
|------------|----------|--------|-------|--------|-------|

---

### 3.9 S9 전략: 눌림목 지지 반등 스윙 (HTS 조건검색 필요)

#### 전략 개요

정배열(5일>20일>60일 MA) 상태에서 5일선 근처까지 눌림이 발생하고, 거래량 감소 후 반등 조짐을 보이는 종목을 매수하는 스윙 전략입니다.

#### 진입 조건

- 5일 MA > 20일 MA > 60일 MA (정배열)
- 현재가가 5일 MA 기준 -3% ~ +2% (눌림 구간)
- 당일 양봉 + 거래량이 전일 대비 120% 이상
- 최근 3일 평균 거래량 ≤ 최근 10일 평균 × 80%

#### 활성화 방법

HTS 조건검색기에서 위 조건으로 조건식 생성 후 `strategy_9_pullback.py`의 `COND_NM` / `COND_ID` 설정.

| 목표 보유기간 | 3~5거래일 | 목표가 | +7.0% | 손절가 | -3.5% |
|------------|----------|--------|-------|--------|-------|

---

### 3.10 S10 전략: 52주 신고가 돌파 스윙

#### 전략 개요

52주(약 250거래일) 신고가를 갱신하는 종목 중, 거래량 급증이 동반된 경우 진입하는 스윙 전략입니다. 신고가 돌파는 매도 대기 물량(수급 저항)이 사라졌음을 의미하여 추가 상승 가능성이 높습니다.

#### 진입 조건

| 조건 | 기준값 |
|------|--------|
| 52주 신고가 기록 | ka10016 신고저가요청 |
| 전일 대비 거래량 급증률 | ≥ 100% (ka10023) |
| 당일 등락률 | 2% ~ 15% |

#### 스코어 산정

```
거래량 급증: ≥300% → +30 / ≥200% → +20 / ≥100% → +10
등락률: 2~8% → +20 / 8~15% → +10 / 15% 초과 → -10
체결강도: >130 → +30 / >110 → +20 / >100 → +10
```

| 목표 보유기간 | 5~10거래일 | 목표가 | +12.0% | 손절가 | -5.0% |
|------------|----------|--------|--------|--------|-------|

#### API 사용

- `ka10016`: 신고저가요청 (52주 신고가 종목 리스트)
- `ka10023`: 거래량급증요청 (전일 대비 급증률)

---

### 3.11 S11 전략: 외국인 연속 순매수 스윙

#### 전략 개요

외국인 투자자가 3거래일 연속으로 순매수를 지속하는 종목을 매수하는 스윙 전략입니다. 외국인의 지속적 매수는 글로벌 투자 자금의 유입을 의미합니다.

#### 진입 조건

| 조건 | 기준값 |
|------|--------|
| D-1, D-2, D-3 모두 순매수 양수 | ka10035 (for_cont_nettrde_upper) |
| 누적 순매수(tot) | > 0 |
| 당일 등락률 | > 0%, ≤ 10% |
| 체결강도 | ≥ 100% |

#### 스코어 산정

```
연속 3일 모두 양수: +30 / 2일: +20 / 0일: 0
당일 양봉: +20 / 하락(-3% 미만): -10
체결강도: >120 → +30 / >100 → +20
```

| 목표 보유기간 | 5~7거래일 | 목표가 | +8.0% | 손절가 | -4.0% |
|------------|----------|--------|-------|--------|-------|

#### API 사용

- `ka10035`: 외인연속순매매상위요청 (dm1, dm2, dm3, tot 필드)

---

### 3.12 S12 전략: 종가 강도 확인 매수 (종가매매)

#### 전략 개요

당일 오후 14:30~14:50에 등락률 4% 이상, 체결강도 110% 이상, 기관 순매수가 확인된 종목을 14:50~15:00 동시호가 시장가로 매수하는 종가매매 전략입니다. 다음 날 갭 상승 기대를 이용합니다.

#### 진입 조건

| 조건 | 기준값 |
|------|--------|
| 당일 등락률 | 4% ~ 15% (ka10027) |
| 체결강도 | ≥ 110% (응답에 포함) |
| 기관 순매수 | 당일 확인 (ka10063) |

#### 스코어 산정

```
등락률: 4~10% → +30 / 10~15% → +15 / 15% 초과 → -10
체결강도: ≥130 → +35 / ≥110 → +25 / ≥100 → +10
호가비율: >1.5 → +20 / >1.2 → +10
```

#### 진입 타이밍

- **확인 시간**: 14:30~14:50
- **매수 시간**: 14:50~15:00 동시호가 시장가
- **보유 기간**: 2~5거래일

| 목표가 | +6.0% | 손절가 | -3.0% |
|--------|-------|--------|-------|

---

### 3.13 S13 전략: 거래량 폭발 박스권 돌파 스윙 (HTS 조건검색 필요)

#### 전략 개요

최근 10~30거래일 박스권(등락폭 8% 이하)에서 거래량 3배 이상 폭발과 함께 박스 상단을 돌파하는 종목을 매수하는 스윙 전략입니다.

#### 진입 조건

- 최근 15거래일 고가-저가 변동폭 ≤ 8% (박스권)
- 당일 박스 상단(최근 N일 최고가) 상향 돌파
- 당일 거래량 ≥ 20일 평균 × 3.0
- 당일 양봉 + 종가가 당일 고가의 80% 이상
- 체결강도 ≥ 130%
- 시가총액 300억 이상

#### 활성화 방법

HTS 조건검색기에서 위 조건으로 조건식 생성 후 `strategy_13_box_breakout.py`의 `COND_NM` / `COND_ID` 설정.

| 목표 보유기간 | 3~7거래일 | 목표가 | +10.0% | 손절가 | -4.0% |
|------------|----------|--------|--------|--------|-------|

---

### 3.14 전략별 활성화 시간대

```
08:30 ─── 09:00 ─── 09:30 ─── 10:00 ─── 13:00 ─── 14:00 ─── 14:30 ─── 15:30
  │           │          │          │          │          │          │          │
  ├─ S7 ───┤           │          │          │          │          │          │
  ├──── S1 ───────────┤           │          │          │          │          │
                       ├─── S2 (VI 이벤트 기반, 장 전체) ──────────────────────┤
                       ├─── S3 ──────────────────────────────────────────┤
                       ├─── S4 ──────────────────────────────────────────────┤
                                  ├── S5 ─────────────────────────────────┤
                       ├──── S6 ──────────────────────┤
                       ├─── S10 ──────────────────────────────────────────┤
                       ├─── S11 ──────────────────────────────────────────┤
                                                              ├── S12 ──┤
```

---

### 3.15 신호 중복·과열 제어 (Feature 4)

SMA는 과도한 신호 발행을 방지하는 3중 제어 시스템을 갖추고 있습니다:

| 제어 | 설명 | Redis 키 | TTL |
|------|------|---------|-----|
| 종목 쿨다운 | 동일 종목, 다른 전략도 30분 내 재발행 방지 | `signal:stock:{stk_cd}` | 30분 |
| 섹터 과열 | 1시간 내 동일 섹터 3건 이상 → SECTOR_OVERHEAT 알림 | `signal:sector:{sector}` | 1시간 |
| 일일 상한 | 전체 30건/일 하드캡 | `signal:daily_count:{date}` | 25시간 |

지원 섹터: 반도체, 2차전지, 바이오, 방산, 조선, 자동차, AI, 에너지

---

## 4. AI 스코어링 시스템

### 4.1 전략별 Claude 호출 임계값

규칙 점수가 임계값 미달 시 Claude API를 호출하지 않고 CANCEL 처리합니다:

| 전략 | 임계값 | 이유 |
|------|-------|------|
| S1_GAP_OPEN | 70점 | 갭상승 조건이 명확 |
| S2_VI_PULLBACK | 65점 | 다양한 패턴 존재 |
| S3_INST_FRGN | 60점 | 데이터 노이즈 많음 |
| S4_BIG_CANDLE | 75점 | 추격 매수는 높은 확신 필요 |
| S5_PROG_FRGN | 65점 | 프로그램 매수 신뢰성 |
| S6_THEME_LAGGARD | 60점 | 불확실성 높음 |
| S7_AUCTION | 70점 | 동시호가 데이터 신뢰성 높음 |
| S10_NEW_HIGH | 65점 | 신고가 돌파 확인 필요 |
| S11_FRGN_CONT | 60점 | 연속 매수 노이즈 보정 |
| S12_CLOSING | 65점 | 종가 매수 시간 제약 |

### 4.2 최종 신호 판단 로직

```
신호 수신 (telegram_queue)
    │
    ├─ news:trading_control == "PAUSE" → 즉시 CANCEL
    │
    ├─ 특수 타입 (FORCE_CLOSE, DAILY_REPORT) → AI 없이 통과
    │
    ├─ rule_score() 계산 (0~100점)
    │       ├─ 전략별 임계값 미달 → CANCEL (Claude 미호출)
    │       └─ 임계값 이상 → check_daily_limit()
    │               ├─ 일별 한도 초과 → _fallback(rule_score)
    │               └─ 한도 내 → analyze_signal() (Claude API)
    │                               ├─ 성공 → JSON 파싱 결과 사용
    │                               └─ 실패 → _fallback 사용
    │
    └─ 결과를 ai_scored_queue에 LPUSH
```

### 4.3 Claude 응답 형식

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

### 4.4 AI 스코어 해석 가이드

| AI 점수 | 의미 | 권장 행동 |
|---------|------|---------|
| 90점 이상 | 최강 신호 | 적극적 진입, 표준 포지션의 150% |
| 80~90점 | 강한 신호 | 일반 진입, 표준 포지션 |
| 70~80점 | 보통 신호 | 소규모 진입 또는 관망 후 진입 |
| 65~70점 | 약한 신호 | 관망 권장 |
| 65점 미만 | 신호 없음 | 진입 안 함 (CANCEL) |

### 4.5 API 사용량 모니터링

Redis 키:
- `claude:daily_calls:{YYYYMMDD}` – 일별 호출 횟수
- `claude:daily_tokens:{YYYYMMDD}` – 일별 토큰 합계

Telegram `/상태` 명령으로 실시간 확인 가능:

```
📊 Claude AI 오늘 사용량
호출 횟수: 42 / 100
총 토큰: 18,720
```

---

## 5. Telegram Bot 사용법

### 5.1 명령어 전체 목록 (26개)

#### 조회 명령어

| 명령어 | 설명 |
|--------|------|
| `/ping` | 봇 동작 확인 |
| `/status` | Java API 상태 + Python WS 상태 + Claude 사용량 |
| `/signals` | 당일 신호 목록 (최근 10건) |
| `/perf` | 당일 전략별 성과 통계 |
| `/track` | 오늘의 가상 P&L WIN/LOSS 현황 |
| `/analysis` | 전략별 가상 승률·수익률 |
| `/history {종목코드}` | 종목별 최근 7일 신호 이력 |
| `/quote {종목코드}` | 실시간 시세 (WebSocket) |
| `/score {종목코드}` | 오버나잇 점수 조회 (개인 보유 종목 수동 확인) |
| `/candidates [market]` | 후보 종목 조회 |
| `/news` | 최근 뉴스 분석 결과 + 매매 제어 상태 |
| `/sector` | 추천 섹터 + 시장 심리 + 전략별 신호 수 |
| `/events` | 이번 주 경제 캘린더 |
| `/errors` | 시스템 에러 현황 (큐 깊이·오류 건수) |
| `/report` | 오늘 신호 요약 (Redis 기반) |

#### 설정 명령어

| 명령어 | 설명 |
|--------|------|
| `/filter [s1~s7\|all]` | 전략 수신 필터 설정 |
| `/watchAdd {종목코드}` | 특정 종목만 알림 수신 |
| `/watchRemove {종목코드}` | 관심 종목 제거 |
| `/settings` | 내 필터·관심 종목 조회 |

#### 제어 명령어

| 명령어 | 설명 |
|--------|------|
| `/pause` | 매매 PAUSE 컨펌 요청 (인라인 키보드) |
| `/resume` | 매매 CONTINUE로 즉시 복귀 |
| `/strategy {s1~s7}` | 전술 수동 실행 |
| `/token` | 키움 토큰 수동 갱신 |
| `/wsStart` | WebSocket 구독 시작 (Java WS) |
| `/wsStop` | WebSocket 구독 종료 |

### 5.2 자동 알림 타입

SMA는 사용자가 명령하지 않아도 자동으로 다음 알림을 발송합니다:

| 타입 | 트리거 | 시간 |
|------|--------|------|
| `MARKET_OPEN_BRIEF` | 장시작 브리핑 (매매 상태·심리·이벤트·후보 수) | 09:01 |
| `MIDDAY_REPORT` | 오전 중간 보고 (신호 건수·TOP 신호·섹터) | 12:30 |
| `DAILY_REPORT` | 가상 P&L 포함 향상된 일일 리포트 | 15:35 |
| `NEWS_ALERT` | 뉴스 기반 매매 제어 변경 (CONTINUE↔CAUTIOUS) | 뉴스 분석 후 |
| `PAUSE_CONFIRM_REQUEST` | AI 뉴스 분석 결과 PAUSE 권고 | 뉴스 분석 후 |
| `CALENDAR_ALERT` | 경제 이벤트 2시간 전 경고 | 이벤트 전 |
| `SECTOR_OVERHEAT` | 1시간 내 동일 섹터 3건+ 과열 경고 | 실시간 |
| `SYSTEM_ALERT` | 큐 적체·Redis 메모리·에러 누적 경고 | 실시간 |

### 5.3 매매 신호 메시지 해석

```
🚀 [S1_GAP_OPEN] 005930 삼성전자
✅ 진입  |  신뢰도: 🔴 높음
AI 스코어: 78.0점  (규칙: 75.0점)
진입방식: 시초가_시장가
목표: +4.0%  손절: -2.0%
진입가: 84,300원
목표가: 87,672원 (+4.0%)  손절가: 82,614원 (-2.0%)
리스크/리워드: 1:2.0
갭/상승: 3.85%  체결강도: 143.0%  호가비율: 1.82

💬 강한 갭상승과 안정적인 체결강도. 호가잔량도 매수 우위로 시초가 매수 적합.

🕐 09:00:05
```

전략 이모지: 🚀S1 / 🎯S2 / 🏦S3 / 📊S4 / 💻S5 / 🔥S6 / ⚡S7 / 📈S10 / 🌍S11 / 🌙S12

### 5.4 매매 중단 컨펌 플로우

AI가 PAUSE를 권고하거나 사용자가 `/매매중단`을 실행하면 인라인 키보드가 발송됩니다:

```
⚠️ [매매 중단 권고 / 확인]

AI 뉴스 분석 결과 매매 중단이 권고되었습니다.
시장 심리: 약세 📉
요약: [AI 분석 요약]
리스크:
• [리스크 요인 1]
• [리스크 요인 2]

매매를 중단하시겠습니까?

[✅ 확인 (중단)]  [❌ 취소]
```

- **확인**: `POST /api/trading/control/PAUSE` 호출 → 즉시 매매 중단
- **취소**: 현재 상태 유지, 메시지 "취소됨"으로 수정

**중요**: PAUSE 권고는 30분마다 중복 발송되지 않습니다. 한 번 컨펌 요청 후 AI 분석 결과가 바뀌기 전까지 재요청하지 않습니다.

### 5.5 전략 필터 설정

```
/filter s1 s4     → S1, S4 전략 신호만 수신
/filter all       → 모든 전략 수신 (필터 해제)
/filter           → 현재 필터 확인
```

스윙 전략 포함 필터 예시:

| 매매 스타일 | 권장 필터 |
|-----------|---------|
| 단기 스캘퍼 | `/filter s1 s7` |
| 모멘텀 트레이더 | `/filter s2 s4 s6` |
| 기관 추종 | `/filter s3 s5` |
| 스윙 트레이더 | `/filter s10 s11 s12` |
| 전략 없음 | `/filter all` |

**주의**: 필터에는 현재 S1~S7만 지정 가능합니다. S10~S12는 `all` 또는 필터 없음 시 수신됩니다.

---

## 6. 뉴스 기반 매매 제어

### 6.1 개요

ai-engine의 `news_scheduler.py`가 30분마다 한국 금융 뉴스를 수집하고 Claude AI로 분석합니다. 분석 결과에 따라 매매 제어 상태를 자동으로 전환합니다.

### 6.2 매매 제어 상태

| 상태 | 의미 | 동작 |
|------|------|------|
| `CONTINUE` | 정상 매매 | 모든 신호 허용 |
| `CAUTIOUS` | 신중 매매 | 신호 허용, 고위험 섹터 필터링 강화 |
| `PAUSE` | 매매 중단 | ai-engine에서 모든 신호 즉시 CANCEL |

### 6.3 자동 상태 전환 흐름

```
30분마다: news_collector → 뉴스 수집
          news_analyzer → Claude AI 분석 (trading_control, market_sentiment, sectors, risk_factors)
          _save_to_redis → 결과 저장
               │
               ├─ CONTINUE↔CAUTIOUS 전환: NEWS_ALERT → news_alert_queue → Java → ai_scored_queue → Telegram
               │
               └─ PAUSE 권고: PAUSE_CONFIRM_REQUEST → ai_scored_queue → Telegram (인라인 키보드)
```

### 6.4 PAUSE 컨펌 후 복귀

PAUSE 상태에서 복귀하려면:
1. 텔레그램 `/매매재개` 명령 실행
2. 또는 Java API 직접 호출: `POST /api/trading/control/CONTINUE`

### 6.5 Redis 키 구조

| 키 | TTL | 내용 |
|----|-----|------|
| `news:trading_control` | 1시간 | CONTINUE\|CAUTIOUS\|PAUSE |
| `news:prev_control` | 2시간 | 이전 상태 (중복 알림 방지용) |
| `news:analysis` | 1시간 | Claude 분석 전체 JSON |
| `news:latest` | 2시간 | 수집된 뉴스 JSON 배열 |
| `news:sector_recommend` | 1시간 | 추천 섹터 배열 |
| `news:market_sentiment` | 1시간 | BULLISH\|NEUTRAL\|BEARISH |
| `news_alert_queue` | 12시간 | Python → Java 뉴스 알림 큐 |

### 6.6 환경변수

| 변수 | 기본값 | 설명 |
|------|-------|------|
| `NEWS_ENABLED` | true | 뉴스 스케쥴러 활성화 |
| `NEWS_INTERVAL_MIN` | 30 | 뉴스 수집 주기 (분) |
| `NEWS_MARKET_ONLY` | false | 장 중에만 실행 |

---

## 7. 경제 캘린더 연동

### 7.1 개요

FOMC·한은 금통위·CPI 등 주요 경제 이벤트를 DB에서 관리합니다. 발표 2시간 전 자동으로 CAUTIOUS 모드 전환 및 텔레그램 경고를 발송합니다.

### 7.2 지원 이벤트 타입

| 타입 | 설명 |
|------|------|
| FED | 미국 FOMC 금리 결정 |
| BOK | 한국은행 금통위 |
| CPI | 미국 소비자물가지수 |
| PPI | 미국 생산자물가지수 |
| GDP | GDP 발표 |
| NFP | 미국 비농업고용 |
| CUSTOM | 사용자 정의 이벤트 |

### 7.3 스케줄러 동작

| 스케줄 | 시간 | 동작 |
|--------|------|------|
| 매시간 정각 | 평일 | HIGH 임팩트 이벤트 2시간 이내 여부 확인 |
| 임박 감지 시 | - | `calendar:pre_event` Redis 키 설정 (TTL 2시간) → NewsControlService가 CAUTIOUS 전환 |
| 매일 08:00 | 평일 | 오늘 예정 이벤트 모닝 브리핑 발송 |

### 7.4 이벤트 관리 API

```bash
# 이벤트 등록
curl -X POST http://localhost:8080/api/trading/calendar/event \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"FOMC","event_type":"FED","event_date":"2026-04-30","event_time":"03:00","expected_impact":"HIGH"}'

# 이번 주 이벤트 조회
curl http://localhost:8080/api/trading/calendar/week

# 오늘 이벤트 조회
curl http://localhost:8080/api/trading/calendar/today
```

텔레그램 `/이벤트` 명령으로도 확인 가능합니다.

---

## 8. 신호 성과 추적

### 8.1 개요

`SignalPerformanceScheduler`가 장 중 10분마다 SENT 상태의 신호에 대해 가상 P&L을 평가합니다.

### 8.2 평가 로직

| 결과 | 조건 |
|------|------|
| WIN | 현재가가 목표가에 도달 |
| LOSS | 현재가가 손절가 이하 |
| EXPIRED | 장마감(15:35)까지 미결 신호 |
| SENT | 평가 중 |

### 8.3 성과 조회

```bash
# 오늘 신호 + 가상 P&L 목록
curl http://localhost:8080/api/trading/signals/performance

# 전략별 승률·수익률 요약
curl http://localhost:8080/api/trading/signals/performance/summary
```

텔레그램 `/성과추적`, `/전략분석` 명령으로도 확인 가능합니다.

---

## 9. 실전 매매 가이드

### 9.1 하루 매매 루틴

#### 08:30 장전 준비

```
□ /상태 명령으로 시스템 정상 여부 확인
□ /뉴스 명령으로 AI 뉴스 분석 확인 (매매 제어 상태 확인)
□ /이벤트 명령으로 오늘 경제 일정 확인
□ S7 동시호가 신호 대기
```

#### 09:00 장시작 직후

```
□ MARKET_OPEN_BRIEF 자동 브리핑 수신 확인
□ S1 갭상승 신호 수신 즉시 확인
□ S7 동시호가 신호로 시초가 매수 여부 결정
□ /시세 명령으로 현재가 실시간 확인
```

#### 09:00~10:00 골든 타임

```
□ S1, S2 신호 적극 대응
□ 장 초반 강한 테마 파악 (S6 신호 예비 확인)
□ 진입 신호 수신 시 30초 이내 의사결정
□ 포지션 진입 후 목표가/손절가 주문 미리 설정
```

#### 10:00~14:30 장중 관리

```
□ S3, S4, S5, S6 단기 신호 모니터링
□ S10, S11 스윙 신호 확인 (보유 목적)
□ 보유 포지션 손익 확인
□ SECTOR_OVERHEAT 알림 수신 시 해당 섹터 신규 진입 자제
```

#### 14:30~14:50 종가매매 시간

```
□ S12 종가 강도 확인 신호 대기
□ S12 신호 수신 시 14:50~15:00 동시호가 시장가 매수 고려
```

#### 15:30 이후 정리

```
□ DAILY_REPORT 자동 수신 (15:35)
□ /성과추적 명령으로 가상 P&L 확인
□ /전략분석 명령으로 전략별 승률 확인
□ 익일 스윙 포지션 보유 여부 결정
```

### 9.2 신호 수신 후 의사결정 흐름

```
신호 수신
    │
    ├── 매매 제어 상태 확인
    │       ├── PAUSE: 신호 무시 (시스템이 이미 CANCEL)
    │       ├── CAUTIOUS: 고위험 섹터 신중 대응
    │       └── CONTINUE: 정상 판단
    │
    ├── AI 스코어 확인
    │       ├── 90점 이상: 즉시 진입 검토
    │       ├── 80~90점: 현재가 확인 후 진입
    │       ├── 70~80점: 추가 조건 확인 후 진입
    │       └── 65~70점: 관망 또는 소량 테스트
    │
    ├── 경제 이벤트 확인
    │       └── CALENDAR_ALERT 수신 시: 매매 규모 축소
    │
    └── 손절/목표가 주문 동시 설정 (필수)
```

### 9.3 포지션 사이징 권장

- 단일 포지션: 총 투자 자금의 **최대 20%**
- 동시 보유 포지션: **최대 5개**
- 일일 최대 손실 한도: 총 자금의 **3%**

| AI 스코어 | 포지션 크기 |
|---------|-----------|
| 90점 이상 | 200만원 (기준 1,000만원) |
| 80~90점 | 150만원 |
| 70~80점 | 100만원 |
| 65~70점 | 50만원 |

### 9.4 리스크 관리 절대 원칙

1. **손절은 반드시 실행**: AI 신호와 무관하게 손절선 도달 시 즉시 청산
2. **한 종목 집중 금지**: 단일 종목에 총 자금의 20% 초과 투자 금지
3. **일별 손실 한도**: 일일 손실 3% 도달 시 당일 거래 종료
4. **레버리지 금지**: 신용·미수 매수 절대 금지

---

## 10. 시스템 모니터링 및 운영

### 10.1 헬스체크 엔드포인트

```bash
curl http://localhost:8080/api/trading/health         # Java API
curl http://localhost:8081/health                     # WebSocket listener
curl http://localhost:8082/health                     # AI engine

# 종합 헬스 (Telegram /에러 명령 동일)
curl http://localhost:8080/api/trading/monitor/health
```

응답 예시:
```json
{
  "status": "UP",
  "trading_control": "CONTINUE",
  "calendar_pre_event": false,
  "telegram_queue": 2,
  "error_queue": 0,
  "daily_signals": 12,
  "ws_reconnect_today": 0
}
```

### 10.2 Redis 큐 상태 확인

```bash
redis-cli LLEN telegram_queue     # 처리 대기 신호 (정상: 0~5)
redis-cli LLEN ai_scored_queue    # 발송 대기 신호 (정상: 0~3)
redis-cli LLEN error_queue        # 처리 실패 신호 (정상: 0)
redis-cli LLEN news_alert_queue   # 뉴스 알림 대기 (정상: 0~2)

# 뉴스 제어 상태 확인
redis-cli GET news:trading_control
redis-cli GET news:market_sentiment

# 캘린더 이벤트 임박 여부
redis-cli GET calendar:pre_event

# 오늘 신호 카운터
redis-cli GET "signal:daily_count:$(date +%Y-%m-%d)"
```

### 10.3 로그 분석

```bash
# AI 분석 결과 확인
grep '"module": "analyzer"' ai-engine/logs/ai-engine.log | tail -20

# 뉴스 스케쥴러 상태
grep '\[NewsScheduler\]' ai-engine/logs/ai-engine.log | tail -10

# 오류 로그
grep 'ERROR\|CRITICAL' ai-engine/logs/ai-engine.log | tail -30

# 처리된 신호 수
grep '발행 완료' ai-engine/logs/ai-engine.log | wc -l
```

### 10.4 자동 알림 확인 방법 (장 시작 전 체크리스트)

```
□ /status  → Java API UP, Python WS 상태, Claude 사용량 확인
□ /errors  → error_queue=0, telegram_queue 정상
□ /news    → 매매 제어 CONTINUE, 시장 심리 확인
□ /events  → 오늘 HIGH 임팩트 이벤트 유무 확인
```

### 10.5 장애 대응

#### P1: Redis 연결 실패
```bash
sudo systemctl restart redis-server
kill -9 $(pgrep -f engine.py) && cd ai-engine && python engine.py &
```

#### P2: WebSocket 연결 끊김
```
/wsStop  →  /wsStart
```

또는 PM2로 ws-listener 재시작:
```bash
pm2 restart ws-listener
```

#### P3: 뉴스 스케쥴러 오류 시 수동 복구
```bash
# 매매 제어 상태 강제 복귀
curl -X POST http://localhost:8080/api/trading/control/CONTINUE
```

---

## 11. 고급 설정

### 11.1 전략 활성화/비활성화

Python 전략 스캐너를 사용하는 경우 `strategy_runner.py`에서 원하는 전략 블록을 주석 처리합니다.

Java api-orchestrator의 전략은 `TradingScheduler.java`의 스케줄러 어노테이션을 주석 처리하여 비활성화합니다.

### 11.2 스코어 임계값 조정

`scorer.py`의 `CLAUDE_THRESHOLDS`:

```python
CLAUDE_THRESHOLDS = {
    "S1_GAP_OPEN":      70,   # 높일수록 더 엄격한 필터
    "S2_VI_PULLBACK":   65,
    "S3_INST_FRGN":     60,
    "S4_BIG_CANDLE":    75,
    "S5_PROG_FRGN":     65,
    "S6_THEME_LAGGARD": 60,
    "S7_AUCTION":       70,
    "S10_NEW_HIGH":     65,
    "S11_FRGN_CONT":    60,
    "S12_CLOSING":      65,
}
```

### 11.3 신호 과열 제어 조정

`api-orchestrator/.env`:
```bash
MAX_DAILY_SIGNALS=30              # 일일 전체 신호 상한
SECTOR_OVERHEAT_THRESHOLD=3       # 섹터 과열 임계값
STOCK_COOLDOWN_MINUTES=30         # 종목 크로스-전략 쿨다운
```

### 11.4 HTS 조건검색 전략 활성화 (S8, S9, S13)

1. 영웅문HTS 조건검색기에서 전략 조건 입력
2. 저장 후 `ka10171` API로 `cond_id` 확인
3. 해당 Python 파일의 `COND_NM` / `COND_ID` 상수 수정
4. `strategy_runner.py`의 해당 전략 블록 주석 해제

### 11.5 뉴스 스케쥴러 세부 조정

```bash
NEWS_INTERVAL_MIN=30     # 뉴스 수집 주기
NEWS_MARKET_ONLY=false   # 장외 시간 건너뜀 여부
```

---

## 12. 개발자 가이드

### 12.1 새 전략 추가 방법

#### Step 1: 전략 파일 생성 (`ai-engine/strategy_N_xxxxx.py`)

```python
async def scan_xxxxx(token: str, market: str = "000", rdb=None) -> list:
    """
    Returns: list of signals with:
      - stk_cd, strategy ("SN_XXXXX"), entry_type
      - target_pct, stop_pct, score
      - [전략별 지표 필드]
    """
    results = []
    # 구현...
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
```

#### Step 2: `scorer.py` 스코어링 추가

```python
CLAUDE_THRESHOLDS = {
    ...
    "SN_XXXXX": 65,
}

# rule_score() 의 match 블록에:
case "SN_XXXXX":
    score += ...
```

#### Step 3: `strategy_runner.py` 등록

```python
if datetime.time(9, 30) <= now <= datetime.time(14, 0):
    async def _sN():
        from strategy_N_xxxxx import scan_xxxxx
        signals = await scan_xxxxx(token, "000", rdb=rdb)
        await _push_signals(rdb, signals, "SN_XXXXX")
    tasks.append(_run_strategy_with_semaphore("SN", _sN()))
```

#### Step 4: `analyzer.py` 프롬프트 추가

```python
elif strategy == "SN_XXXXX":
    return (
        f"[전략명] 신호 평가:\n"
        f"종목: {stk_nm}({stk_cd}), [지표]: ..., 규칙점수: {rule_score}/100\n"
        f"진입 적합성을 JSON으로 답하세요."
    )
```

### 12.2 신호 데이터 스키마

`telegram_queue` / `ai_scored_queue` JSON 필드:

```python
{
    # 공통 필드
    "strategy": "S1_GAP_OPEN",
    "stk_cd": "005930",
    "stk_nm": "삼성전자",
    "entry_type": "시초가_시장가",
    "target_pct": 4.0,
    "stop_pct": -2.0,
    "signal_time": "2026-03-22T09:00:05",
    "cur_prc": 84300,

    # AI 분석 결과 (ai_scored_queue에 추가)
    "rule_score": 75.0,
    "ai_score": 78.0,
    "action": "ENTER",        # ENTER / HOLD / CANCEL
    "confidence": "HIGH",     # HIGH / MEDIUM / LOW
    "ai_reason": "...",
    "adjusted_target_pct": 3.5,
    "adjusted_stop_pct": -2.0,

    # 전략별 추가 필드 (예: S1)
    "gap_pct": 3.85,
    "cntr_strength": 143.0,
}
```

### 12.3 ai-engine 의존성 그래프

```
engine.py
  ├── queue_worker.py
  │     ├── analyzer.py        (Claude API 호출, S1~S7, S10~S12 프롬프트)
  │     ├── scorer.py          (규칙 기반 스코어링, S1~S7, S10~S12)
  │     └── redis_reader.py
  ├── strategy_runner.py       (ENABLE_STRATEGY_SCANNER=true 시 활성화)
  │     ├── strategy_1_gap_opening.py
  │     ├── strategy_2_vi_pullback.py
  │     ├── strategy_3_inst_foreign.py
  │     ├── strategy_4_big_candle.py
  │     ├── strategy_5_program_buy.py
  │     ├── strategy_6_theme.py
  │     ├── strategy_7_auction.py
  │     ├── strategy_10_new_high.py    (✅ 등록됨)
  │     ├── strategy_11_frgn_cont.py   (✅ 등록됨)
  │     └── strategy_12_closing.py     (✅ 등록됨)
  ├── news_scheduler.py        (NEWS_ENABLED=true 시 활성화)
  │     ├── news_collector.py
  │     └── news_analyzer.py
  └── monitor_worker.py        (ENABLE_MONITOR=true 시 활성화)
```

### 12.4 Redis 큐 플로우 전체 맵

| 큐/키 | 생산자 | 소비자 | TTL |
|-------|--------|--------|-----|
| `telegram_queue` | Java SignalService | Python queue_worker | 12h |
| `ai_scored_queue` | Python queue_worker, Java | Node.js signals.js | 12h |
| `news_alert_queue` | Python news_scheduler | Java NewsAlertScheduler | 12h |
| `vi_watch_queue` | Java RedisMarketDataService | Java ViWatchService | 2h |
| `error_queue` | Python queue_worker (dead-letter) | (수동 확인) | 24h |

### 12.5 테스트 실행

```bash
# Python ai-engine
cd ai-engine
python -m pytest tests/ -v
python -m pytest tests/test_scorer.py -v

# Node.js telegram-bot
cd telegram-bot
node tests/test_formatter.js
```

---

## 13. 법적 고지 및 면책사항

### 13.1 투자 위험 고지

**SMA(StockMate AI)는 매매 신호를 제공하는 보조 도구이며, 투자 자문 서비스가 아닙니다.**

주식 투자에는 원금 손실의 위험이 있습니다. SMA가 제공하는 신호는 AI와 규칙 기반의 판단이며, 시장 상황의 급변, 예기치 못한 뉴스, 시스템 오류 등으로 인해 손실이 발생할 수 있습니다.

**투자로 인한 모든 손익의 책임은 사용자 본인에게 있습니다.**

### 13.2 시스템 한계

1. **과거 데이터 부재**: 예상 수익률·승률은 추정치이며 백테스트 결과가 아닙니다.
2. **데이터 지연**: WebSocket·API 응답 지연으로 신호가 늦게 발생할 수 있습니다.
3. **API 장애**: 키움 API·Claude API·Redis 장애 시 신호가 발생하지 않을 수 있습니다.
4. **뉴스 분석 한계**: Claude AI의 뉴스 분석은 시장 전문가 수준이 아닐 수 있습니다.
5. **HTS 전략 미활성화**: S8·S9·S13은 HTS 조건검색 설정 전까지 자동으로 비활성화됩니다.

### 13.3 키움 API 이용 약관 준수

키움 Open API+를 이용하는 모든 사용자는 키움증권의 API 이용약관을 준수해야 합니다. SMA를 통한 과도한 API 요청은 이용 제한의 원인이 될 수 있습니다.

### 13.4 오픈소스 라이선스

- Spring Boot (Apache 2.0)
- Redis (BSD)
- Python anthropic SDK (MIT)
- Telegraf (MIT)
- ioredis (MIT)

---

*SMA StockMate AI v2.0.0 – 2026-03-22*
