# SESSION 종료 및 작업 보고서

**브랜치:** `claude/news-scheduler-trading-KSQiX`
**병합 대상:** `master`
**작성일:** 2026-03-22
**커밋 수:** 4개 (머지 포함)

---

## 개요

이번 세션에서는 StockMate AI의 분석·운영 완성도를 높이기 위해 **5개 핵심 기능** 및 **텔레그램 인터페이스 확장**, 그리고 **매매 중단 안전장치** 를 구현하였습니다.

---

## 구현 완료 목록

### Feature 1: 신호 성과 추적 (Signal Performance Tracker)

신호 발행 후 실제 주가 변화를 추적하여 가상 수익률(WIN/LOSS/EXPIRED)을 계산합니다.

| 파일 | 변경 내용 |
|------|---------|
| `scheduler/SignalPerformanceScheduler.java` | **신규** – 장중 10분마다 SENT 신호의 가상 P&L 평가. 목표가 도달 시 WIN, 손절가 이하 시 LOSS. 장마감(15:35) 미결 → EXPIRED |
| `TradingController.java` | `GET /api/trading/signals/performance` (오늘 신호 + P&L 목록), `GET /api/trading/signals/performance/summary` (전략별 승률/수익률) 추가 |
| `TradingSignalRepository.java` | `getStrategyPerformanceStats()` 집계 쿼리 추가 |
| `kiwoom.js` | `getSignalPerformance()`, `getPerformanceSummary()` 추가 |
| `formatter.js` | `formatPerformanceDetail()`, `formatPerformanceSummary()` 추가 |

---

### Feature 2: 경제 캘린더 연동 (Economic Calendar)

FOMC·한은 금통위·CPI 등 주요 경제 이벤트를 DB에 관리하고, 발표 2시간 전 자동 CAUTIOUS 전환 및 텔레그램 알림을 전송합니다.

| 파일 | 변경 내용 |
|------|---------|
| `domain/EconomicEvent.java` | **신규** – 경제 이벤트 엔티티 (FED/BOK/CPI/PPI/GDP 등 EventType, HIGH/MEDIUM/LOW ImpactLevel) |
| `repository/EconomicEventRepository.java` | **신규** – `findUnnotifiedHighImpactToday()` 등 쿼리 |
| `service/EconomicCalendarService.java` | **신규** – 이번 주/오늘 이벤트 조회, N분 내 HIGH 이벤트 여부 확인 |
| `scheduler/EconomicCalendarScheduler.java` | **신규** – 매시간 HIGH IMPACT 이벤트 체크, 08:00 모닝 브리핑, `calendar:pre_event` Redis 키(TTL 2h) 설정 |
| `service/NewsControlService.java` | **수정** – `calendar:pre_event` 키 존재 시 CONTINUE → CAUTIOUS 자동 격상 |
| `TradingController.java` | `GET /api/trading/calendar/week`, `GET /api/trading/calendar/today`, `POST /api/trading/calendar/event` 추가 |
| `formatter.js` | `formatCalendarWeek()` 추가 |

---

### Feature 3: 텔레그램 명령어 확장

기존 10개 명령에서 **12개 신규 명령**을 추가하여 총 22개 명령을 지원합니다.

| 신규 명령 | 설명 |
|----------|------|
| `/뉴스` | 최근 뉴스 분석 결과 + 매매 제어 상태 |
| `/섹터` | 추천 섹터 + 시장 심리 + 전략별 신호 수 |
| `/신호이력 {종목코드}` | 종목별 최근 7일 신호 이력 |
| `/전략분석` | 전략별 가상 승률·수익률 |
| `/에러` | 시스템 에러 현황 (큐 깊이·오류 건수) |
| `/매매중단` | 매매 중단 **컨펌 요청** (인라인 키보드) |
| `/매매재개` | 매매 재개 즉시 적용 |
| `/이벤트` | 이번 주 경제 캘린더 |
| `/성과추적` | 오늘의 가상 P&L WIN/LOSS 현황 |
| `/관심등록 {종목코드}` | 특정 종목만 알림 수신 설정 |
| `/관심해제 {종목코드}` | 관심 종목 제거 |
| `/설정` | 내 전략 필터·관심 종목 조회 |

추가된 자동 알림 타입:

| 타입 | 트리거 |
|------|--------|
| `MARKET_OPEN_BRIEF` | 09:01 장시작 브리핑 (매매 상태·심리·이벤트·후보 수) |
| `MIDDAY_REPORT` | 12:30 오전 중간 보고 (신호 건수·TOP 신호·섹터) |
| `CALENDAR_ALERT` | 경제 이벤트 2시간 전 경고 |
| `SECTOR_OVERHEAT` | 1시간 내 동일 섹터 3건+ 과열 경고 |
| `SYSTEM_ALERT` | 큐 적체·Redis 메모리·에러 누적 경고 |
| `DAILY_REPORT` | 15:35 가상 P&L 포함 향상된 일일 리포트 |

---

### Feature 4: 신호 중복·과열 제어

| 제어 항목 | 내용 |
|----------|------|
| **종목 쿨다운** | 동일 종목이 다른 전략으로도 30분 내 재발행 방지 (`signal:stock:{stkCd}` TTL 30분) |
| **섹터 과열** | 1시간 내 동일 섹터 3건 이상 시 SECTOR_OVERHEAT 알림 발행 (`signal:sector:{sector}` TTL 1h) |
| **일일 상한** | 전체 신호 30건/일 하드캡 (`signal:daily_count:{date}` TTL 25h) |

설정 환경변수:
```
MAX_DAILY_SIGNALS=30
SECTOR_OVERHEAT_THRESHOLD=3
STOCK_COOLDOWN_MINUTES=30
```

---

### Feature 5: 데이터 품질 모니터링

| 파일 | 변경 내용 |
|------|---------|
| `ai-engine/monitor_worker.py` | **신규** – asyncio 60초 루프: 큐 깊이·에러 큐·Redis 메모리 체크 → SYSTEM_ALERT 발행 |
| `ai-engine/engine.py` | `run_monitor(rdb)` asyncio 태스크 등록 (`ENABLE_MONITOR` 환경변수로 ON/OFF) |
| `scheduler/DataQualityScheduler.java` | **신규** – 1분마다 WebSocket tick 커버리지 체크, 30% 이상 누락 시 자동 재연결 + SYSTEM_ALERT 발행 |
| `TradingController.java` | `GET /api/trading/monitor/health` (큐·에러·일일 신호 수·WS 재연결 수 종합) 추가 |

---

### 매매 중단 안전장치 (PAUSE Confirmation Flow)

**핵심 변경:** 시스템이 자동으로 매매를 중단하지 않고, 사용자의 텔레그램 컨펌을 받은 후 중단합니다.

#### 흐름

```
AI 뉴스 분석 → PAUSE 권고
     ↓
news_scheduler.py: PAUSE_CONFIRM_REQUEST를 ai_scored_queue에 발행
(Redis news:trading_control 은 변경하지 않음)
     ↓
signals.js: 인라인 키보드 메시지 발송
 ┌─────────────────────────────────────────┐
 │ ⚠️ [매매 중단 권고]                       │
 │ AI 뉴스 분석 결과 매매 중단이 권고되었습니다. │
 │ ...시장 심리·요약·리스크...                │
 │ [✅ 확인 (중단)]  [❌ 취소]                │
 └─────────────────────────────────────────┘
     ↓ 사용자 선택
confirm_pause → kiwoom.setTradingControl('PAUSE') 호출
cancel_pause  → 메시지 수정 "취소됨", 상태 유지
```

#### 수정 파일

| 파일 | 변경 내용 |
|------|---------|
| `ai-engine/news_scheduler.py` | PAUSE 전환 시 `PAUSE_CONFIRM_REQUEST`를 `ai_scored_queue`에 발행. CONTINUE/CAUTIOUS는 기존대로 즉시 적용. `prev_control`은 컨펌 전 업데이트하지 않음 |
| `telegram-bot/src/handlers/signals.js` | `PAUSE_CONFIRM_REQUEST` 타입 처리 추가 – 인라인 키보드 메시지 발송 |
| `telegram-bot/src/handlers/commands.js` | `/매매중단` 핸들러가 즉시 PAUSE 하지 않고 확인 키보드 표시로 변경 |
| `telegram-bot/src/index.js` | `bot.action('confirm_pause', ...)` / `bot.action('cancel_pause', ...)` 콜백 핸들러 추가. `kiwoom` 서비스 임포트 추가 |

---

## 신규 Redis 키 목록

| 키 | TTL | 용도 |
|----|-----|------|
| `signal:stock:{stkCd}` | 30분 | 종목 크로스-전략 쿨다운 |
| `signal:daily_count:{date}` | 25시간 | 일일 전체 신호 카운터 |
| `signal:sector:{sector}` | 1시간 | 섹터별 신호 카운터 |
| `calendar:pre_event` | 2시간 | 임박 HIGH 이벤트 플래그 |
| `monitor:ws_reconnect_count` | 24시간 | WS 재연결 횟수 |
| `watchlist:{chatId}` | 영구 | 사용자 관심 종목 Set |

---

## 신규 파일 목록

### Java (api-orchestrator)
- `scheduler/SignalPerformanceScheduler.java`
- `domain/EconomicEvent.java`
- `repository/EconomicEventRepository.java`
- `service/EconomicCalendarService.java`
- `scheduler/EconomicCalendarScheduler.java`
- `scheduler/DataQualityScheduler.java`
- `domain/NewsAnalysis.java` *(뉴스 분석 결과 엔티티)*
- `repository/NewsAnalysisRepository.java`
- `scheduler/NewsAlertScheduler.java` *(news_alert_queue 폴링)*
- `service/NewsControlService.java` *(뉴스 기반 매매 제어)*

### Python (ai-engine)
- `monitor_worker.py`
- `news_scheduler.py`
- `news_collector.py`
- `news_analyzer.py`
- `prompts/news_analysis.txt`

---

## 커밋 이력

```
a54a90b feat: require user confirmation before trading pause (PAUSE_CONFIRM_REQUEST)
a94e5db feat: 텔레그램 자동 알림 3종 + 명령어 7개 추가
808b0ad feat: 5개 기능 확장 - 성과추적/경제캘린더/텔레그램명령/과열제어/데이터모니터링
6bd7c75 feat: queue_worker에 뉴스 기반 PAUSE 조기 차단 로직 추가
c345907 feat: 뉴스 스케쥴러 + Claude 기반 매매 제어 기능 추가
```

---

## 검증 방법 (메인 세션 인수인계)

```bash
# 1. 매매 중단 컨펌 플로우 검증
# news_scheduler에서 PAUSE 권고 시 텔레그램으로 인라인 키보드 수신 확인
# /매매중단 명령 → 확인 키보드 표시 확인

# 2. 경제 캘린더
curl -X POST http://localhost:8080/api/trading/calendar/event \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"TEST_EVENT","event_date":"2026-03-22","expected_impact":"HIGH"}'
redis-cli get calendar:pre_event

# 3. 섹터 과열 제어
redis-cli get signal:sector:반도체   # 1시간 내 카운터 확인
redis-cli get signal:daily_count:20260322

# 4. 성과 추적
curl http://localhost:8080/api/trading/signals/performance
curl http://localhost:8080/api/trading/signals/performance/summary

# 5. 모니터링 헬스
curl http://localhost:8080/api/trading/monitor/health

# 6. 텔레그램 명령
/뉴스, /섹터, /이벤트, /성과추적, /관심등록 005930, /설정
```

---

## 남은 작업 (권고사항)

1. **경제 이벤트 초기 데이터 입력**: 2026년 FOMC(8회), 한은 금통위(8회), 미국 CPI(월 1회), 비농업 고용(매월 첫 번째 금요일) DB 입력
2. **DB 마이그레이션**: `economic_events` 테이블 DDL 적용 필요
3. **Python 의존성**: `ai-engine/requirements.txt`에 `anthropic` 패키지 추가 확인
4. **환경변수 설정**: `NEWS_ENABLED=true`, `ENABLE_MONITOR=true`, `MAX_DAILY_SIGNALS=30` 운영 환경 반영
