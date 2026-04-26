# CRUD Flow Audit - 2026-04-26

대상: 최신 코드와 현재 Docker PostgreSQL `SMA.public` 스키마.

확인 방법:
- `docker compose ps`: 전체 서비스 healthy
- Flyway: v36까지 성공 적용
- 실제 테이블/뷰: `information_schema` 기준 재수집
- 실제 row count: `COUNT(*)`로 재검증
- 코드 참조: Java scheduler/service/repository, Python ai-engine/websocket-listener, Node telegram-bot 전수 검색

## 1. 현재 스키마 요약

Flyway는 v36까지 적용되어 있다.

최근 변경:
- V34: `trade_path_bars`, `strategy_bucket_stats`, `open_positions_legacy` 제거
- V35: `news_analysis.analyzed_at` NOT NULL 보강
- V36: `stock_master.market_cap` 추가

현재 base table은 23개, view는 3개다.

Views:
- `open_positions`: `trading_signals` 기반 호환 view
- `v_active_positions`
- `v_portfolio_risk_snapshot`

## 2. 실제 Row Count

| Table | Count | 비고 |
| --- | ---: | --- |
| `ai_cancel_signal` | 1 | AI 취소 감사 |
| `candidate_pool_history` | 14,202 | 후보 이력 |
| `daily_indicators` | 3,070 | 일봉 지표 |
| `daily_pnl` | 2 | 일별 집계 |
| `economic_events` | 0 | 자동 적재 비활성 |
| `human_confirm_requests` | 0 | 만료 cleanup 대상 |
| `kiwoom_tokens` | 60 | inactive cleanup 대상 |
| `market_daily_context` | 4 | 일일 시장 컨텍스트 |
| `news_analysis` | 0 | 기본 비활성 |
| `overnight_evaluations` | 0 | 아직 운영 기록 없음 |
| `portfolio_config` | 1 | singleton 정상 존재 |
| `position_state_events` | 18 | 포지션 이벤트 |
| `risk_events` | 0 | 리스크 차단 없음 |
| `rule_cancel_signal` | 24 | 룰 취소 감사 |
| `signal_score_components` | 89 | 점수 컴포넌트 |
| `stock_master` | 1,041 | `market_cap` 전부 NULL |
| `strategy_daily_stats` | 12 | 전략 일별 집계 |
| `strategy_param_history` | 82 | 전략 파라미터 이력 |
| `trade_outcomes` | 0 | 청산 성과 없음 또는 미발생 |
| `trade_plans` | 9 | 포지션 계획 |
| `trading_signals` | 92 | 핵심 원장 |
| `vi_events` | 2,941 | VI 이벤트 |
| `ws_tick_data` | 5,920,517 | 대량 tick/event 저장 |

## 3. 주요 Findings

### F1. 포지션 종료/만료 경로가 여전히 이원화되어 있음

`trading_signals`의 정식 포지션 lifecycle은 Python `ai-engine.db_writer`가 가장 완전하다.

Python 경로:
- `confirm_open_position()`: `position_status=ACTIVE`, `monitor_enabled=true`, `trade_plans` upsert, `POSITION_OPENED` 이벤트 기록
- `cancel_open_position_by_signal()`: `signal_status=CANCELLED`, `position_status=CLOSED`, `monitor_enabled=false`, `SIGNAL_CANCELLED` 이벤트 기록
- `close_open_position()`: `WIN/LOSS`, `exit_*`, `position_status=CLOSED`, `monitor_enabled=false`, `trade_outcomes`, `POSITION_CLOSED` 기록

반면 Java 경로:
- `SignalPerformanceScheduler.updatePerformance()`는 장중 10분마다 `SENT` 신호를 평가해 `closeSignal()`로 닫는다.
- `SignalPerformanceScheduler.expireSentSignals()`는 15:35에 `SENT`를 `EXPIRED`로만 바꾼다.
- `TradingSignal.closeSignal()`은 `position_status=CLOSED`, `signal_status=WIN/LOSS`, `realized_pnl`, `closed_at`만 설정한다.
- `TradingSignal.updateStatus(EXPIRED)`는 `position_status`, `monitor_enabled`, `exit_*`, lifecycle event를 정리하지 않는다.

실제 DB 검증:
- `CANCELLED`인데 `monitor_enabled=true`: 63건
- `EXPIRED`인데 `position_status=ACTIVE`, `monitor_enabled=true`: 1건
- terminal status인데 `monitor_enabled=true`: 총 64건

판정:
- 실제 데이터 불일치가 이미 존재한다.
- Java 만료/성과 경로가 Python lifecycle과 같은 보장 수준을 갖지 못한다.

권고:
- 실제 포지션 종료는 Python `close_open_position()`로 일원화한다.
- Java `SignalPerformanceScheduler`는 집계 전용으로 축소하거나, 최소한 `position_status IS NULL`인 비체결 신호만 평가하게 제한한다.
- `expireOldSignals()`와 `expireSentSignals()`는 `monitor_enabled=false`, `position_status=CLOSED` 또는 `NULL` 정리 정책을 명확히 가져야 한다.

### F2. `stock_master` 무결성이 아직 미완성

V33 이후에도 사용 종목 전체가 `stock_master`에 들어와 있지 않다.

실제 DB 검증:
- `trading_signals`, `candidate_pool_history`, `daily_indicators`, `ws_tick_data`, `vi_events` distinct code 중 `stock_master` 누락: 2,901개
- `stock_master.market_cap IS NULL`: 1,041건 전체

원인:
- `StockMasterScheduler`는 평일 09:10 Redis 후보 풀(`candidates:s*:{001,101}`) 기반으로만 upsert한다.
- 이미 쌓인 tick/VI/daily indicator 종목 전체를 백필하지 않는다.
- V36 컬럼 추가 후 시가총액 갱신 배치가 아직 실행되지 않았다.

판정:
- `stock_master` FK는 일부 테이블에만 적용되어 있고, 핵심 대량 테이블(`ws_tick_data`, `vi_events`, `daily_indicators`, `trading_signals`, `candidate_pool_history`)에는 종목 무결성이 강제되지 않는다.
- Python scorer가 `market_cap` 기반 소형주 패널티를 사용한다면 현재는 DB 기반으로는 전부 미확정 상태다.

권고:
- distinct 사용 종목 기준으로 `stock_master` 백필 job을 별도로 만든다.
- `market_cap` 백필 후 Redis `stock:mktcap:{stk_cd}` 캐시와 DB 값을 동기화한다.
- 이후 FK 적용 범위를 재검토한다.

### F3. `trade_plans`, `signal_score_components` 일부 누락

실제 DB 검증:
- `action='ENTER'`인데 `trade_plans`가 없는 신호: 1건
- `scored_at IS NOT NULL`인데 `signal_score_components`가 없는 신호: 3건
- `position_state_events` orphan: 0건

판정:
- Python 신규 lifecycle은 보강되어 있으나, 과거 데이터 또는 Java 생성 경로에서 보조 테이블이 누락될 수 있다.
- `trade_outcomes`는 0건이다. 실제 청산이 아직 없었다면 정상이나, 청산이 있었으면 결과 기록 누락이다.

권고:
- 누락 데이터 백필 SQL 또는 repair job을 별도로 만든다.
- 신규 Java `SignalService.processSignal()` 생성 시에도 `SIGNAL_CREATED` 이벤트와 primary `trade_plans` 생성 여부를 정책적으로 맞출지 결정한다.

### F4. `economic_events`는 테이블은 있지만 자동 스케줄러가 꺼져 있음

`EconomicCalendarScheduler` 파일에는 `@Scheduled` 메서드가 남아 있지만 클래스의 `@Component`가 주석 처리되어 Bean 등록되지 않는다.

실제 동작:
- 자동 조회/알림/`notified` 갱신 없음
- `EconomicCalendarService.addEvent()`로 수동 저장 가능
- 현재 row count 0

판정:
- 시장 컨텍스트나 리스크 플래그에서 경제 이벤트를 기대한다면 현재는 데이터가 없다.

### F5. `news_analysis`는 기본적으로 저장되지 않음

`NewsAlertScheduler`는 Bean으로 등록되어 있지만 `app.news.alert-scheduler-enabled:false` 기본값이면 즉시 return한다.

실제 동작:
- `news_alert_queue` 소비 및 `news_analysis` 저장은 기본 비활성
- 현재 row count 0
- 사용자-facing 뉴스 전달은 ai-engine scheduled brief가 소유한다는 주석과 일치

판정:
- DB에 뉴스 분석 이력을 남기려면 설정 활성화 또는 ai-engine writer가 필요하다.

### F6. `human_confirm_requests`는 DB 상태와 Redis queue 사이 보상 경로가 약함

플로우:
- Python `insert_human_confirm_request()`가 `PENDING` 요청 생성
- Telegram `confirmGate.js`가 `human_confirm_queue`를 소비해 사용자에게 메시지 발송
- Telegram `confirmStore.approveConfirmRequest()`가 DB를 `APPROVED`로 바꾸고 `last_enqueued_at=NOW()`
- Telegram handler가 Redis `confirmed_queue`에 push
- Python `confirm_worker`가 `confirmed_queue`를 처리하고 DB를 `COMPLETED` 또는 `FAILED`로 갱신
- Java `HumanConfirmCleanupScheduler`는 10분마다 `expires_at <= NOW()`인 row를 삭제

위험:
- DB `APPROVED` 갱신 후 Redis `confirmed_queue` push가 실패하면 승인 요청이 처리되지 않을 수 있다.
- 현재 cleanup은 상태와 무관하게 만료 row를 삭제한다. 장애 분석을 위한 승인/실패 이력도 만료 시 삭제된다.

권고:
- `APPROVED AND last_enqueued_at IS NOT NULL AND status <> COMPLETED` 재처리 job 또는 outbox 패턴을 둔다.
- cleanup은 `PENDING/EXPIRED`와 `COMPLETED/FAILED` 보관 기간을 분리한다.

### F7. 대량 테이블 정리 정책은 보강되었지만 `vi_events`는 보관 정책 없음

`DataCleanupScheduler`가 추가되어 매일 23:30 다음 데이터를 정리한다.

삭제 대상:
- `ws_tick_data`: 3일 초과
- `ai_cancel_signal`: 30일 초과
- `rule_cancel_signal`: 30일 초과
- `overnight_evaluations`: 90일 초과
- inactive `kiwoom_tokens`: 7일 초과

누락:
- `vi_events`는 현재 2,941건이고 삭제 정책이 없다.
- `candidate_pool_history`, `daily_indicators`, `position_state_events`, `strategy_param_history`도 장기 보관 정책이 명확하지 않다.

판정:
- `ws_tick_data`는 592만 건으로 가장 크므로 3일 cleanup은 필요하다.
- `vi_events`가 감사성 영구 보관인지, 운영 캐시성 데이터인지 결정이 필요하다.

## 4. Table-by-table CRUD

| Table | Create | Read | Update | Delete | 판정 |
| --- | --- | --- | --- | --- | --- |
| `trading_signals` | Java `SignalService`, Python `insert_python_signal` | Java repo/API, Python readers/monitors | Python score/open/cancel/close/overnight, Java performance/expire/monitor | 없음 | 핵심 원장. Java/Python 상태 전이 충돌 위험 |
| `signal_score_components` | Python `insert_score_components` | Python/Java 조회 | upsert 일부 필드 | 없음 | 일부 scored 신호에 누락 3건 |
| `trade_plans` | Python signal/open path | Python close path | Python upsert | 없음 | ENTER 신호 중 누락 1건 |
| `trade_outcomes` | Python `close_open_position` | Python `db_reader` | 없음 | 없음 | 현재 0건 |
| `position_state_events` | Python lifecycle | Python `db_reader` | 없음 | 없음 | orphan 0, Java 경로는 기록 누락 |
| `candidate_pool_history` | Java `CandidatePoolHistoryScheduler` | Java/API | Java `markLedToSignal` | 없음 | 정상 적재, FK 미완성 |
| `stock_master` | Java `StockMasterScheduler` | Java/Python scoring | Java upsert | 없음 | 누락 code 2,901, market_cap 전부 NULL |
| `ws_tick_data` | Python websocket event writer, Java fallback snapshot | 운영/진단 | 없음 | Java cleanup 3일 | 대량 정상 적재, event marker 의존 |
| `vi_events` | Python websocket event writer, Java fallback snapshot | 전략/진단 | 없음 | 없음 | 보관 정책 없음 |
| `daily_indicators` | Java `DataPersistenceScheduler`, Python `upsert_daily_indicators` | Python scorer/overnight | upsert | 없음 | 복수 writer 구조 유지 |
| `portfolio_config` | Java startup bootstrap/API | Java `SignalService`, Python reader | Java API | 없음 | 정확 count 1, 정상 |
| `daily_pnl` | Java `SignalPerformanceScheduler.aggregateDailyStats` | Python reader/API | upsert | 없음 | Java 집계 의존 |
| `strategy_daily_stats` | Java daily aggregate | Java/API | upsert | 없음 | Java 집계 의존 |
| `market_daily_context` | Java `TradingScheduler` | Python scorer/context | Java morning/end summary | 없음 | 정상 |
| `strategy_param_history` | Java startup/scheduler/service | Java threshold service | 없음 | 없음 | 누적 정책 필요 |
| `kiwoom_tokens` | Java startup/schedulers `TokenService` | Java API client | active flag/update | Java cleanup inactive 7일 | 정상 |
| `human_confirm_requests` | Python confirm request | Telegram/Python | Telegram/Python status updates | Java expired cleanup | Redis enqueue 보상 약함 |
| `overnight_evaluations` | Python overnight worker | Java verifier/Python | Java verification | Java cleanup 90일 | 아직 row 0 |
| `ai_cancel_signal` | Python queue/confirm worker | Python reader | 없음 | Java cleanup 30일 | 정상 |
| `rule_cancel_signal` | Python queue/confirm worker | Python reader | 없음 | Java cleanup 30일 | 정상 |
| `risk_events` | Java `SignalService` risk block | Java/API | 없음 | 없음 | row 0, `stock_master` FK 있음 |
| `news_analysis` | Java `NewsAlertScheduler` when enabled | Java/API | 없음 | 없음 | 기본 비활성 |
| `economic_events` | Java service manual add | Java service | markNotified if scheduler active, but scheduler not Bean | 없음 | 자동 플로우 없음 |

## 5. 실행 시점별 플로우

### Startup

- `ApplicationStartupRunner`
  - `portfolio_config` singleton 없으면 생성
  - `strategy_param_history` bootstrap snapshot
  - Kiwoom token refresh, `kiwoom_tokens` 저장

### 장 전

- 06:50, 07:20/07:25: token refresh 경로가 `TokenRefreshScheduler`와 `TradingScheduler` 양쪽에 있다.
- 07:05: `StrategyParamSnapshotScheduler`
- 07:30, 07:50, 09:00, 09:05~15:50: `TradingScheduler` 후보군 preload
- 07:55: `market_daily_context` morning 저장
- 08:45: 예상체결 preload
- 08:30: `OvernightRiskScheduler`

주의:
- token refresh 스케줄이 `TokenRefreshScheduler`와 `TradingScheduler`에 중복 존재한다. 토큰 저장은 기존 active 비활성화 후 새 active 저장 방식이라 치명적 충돌은 낮지만 불필요한 발급이 될 수 있다.

### 장중

- 전략 후보군: Redis `candidates:*`
- 후보 이력: Java `CandidatePoolHistoryScheduler`, 60초 주기
- 신호 생성: Java `SignalService` 또는 Python `strategy_runner`
- AI scoring: Python `queue_worker`
- 사람 승인: Python -> `human_confirm_queue` -> Telegram -> `confirmed_queue` -> Python `confirm_worker`
- tick/VI 저장: Python websocket-listener event writer
- tick/VI fallback: Java `DataPersistenceScheduler`, `ws:db_writer:event_mode` 없을 때만 저장
- 데이터 품질: Java `DataQualityScheduler`, 60초 주기, alert를 `ai_scored_queue`로 발행

### 장마감/야간

- 15:30/15:35: 신호 만료 및 일일 summary
- 15:45: `daily_pnl`, `strategy_daily_stats` 집계
- 23:30: cleanup

## 6. 우선 조치

1. `trading_signals` terminal 상태 정리 migration 또는 repair script 작성
   - `CANCELLED/EXPIRED/WIN/LOSS`이면 `monitor_enabled=false`
   - `EXPIRED + ACTIVE` 1건은 실제 보유 여부 확인 후 수동 보정

2. Java `SignalPerformanceScheduler`의 상태 변경 범위 제한
   - 집계는 유지하되 실제 포지션 close/expire는 Python lifecycle과 같은 방식으로 처리하거나 비체결 신호만 대상으로 제한

3. `stock_master` 백필
   - 2,901개 누락 code 보강
   - 1,041개 `market_cap` 보강
   - 백필 후 FK 적용 가능성 재검토

4. 보조 테이블 누락 repair
   - `ENTER`인데 `trade_plans` 없는 1건
   - `scored_at` 있는데 `signal_score_components` 없는 3건

5. `human_confirm_requests` outbox/retry 추가
   - DB `APPROVED`와 Redis `confirmed_queue` 사이 장애 보상

6. cleanup 정책 보강
   - `vi_events` 보관 기간 결정
   - `candidate_pool_history`, `strategy_param_history`, `position_state_events` 장기 보관 정책 문서화

## 7. 재검증 SQL

Terminal 상태 불일치:

```sql
SELECT id, stk_cd, signal_status, position_status, action, monitor_enabled
FROM trading_signals
WHERE signal_status IN ('CANCELLED','EXPIRED','WIN','LOSS')
  AND COALESCE(monitor_enabled, false) = true
ORDER BY id;
```

활성 포지션 후보:

```sql
SELECT id, stk_cd, signal_status, position_status, action, entry_at, exited_at, monitor_enabled
FROM trading_signals
WHERE position_status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT')
   OR monitor_enabled = true
ORDER BY created_at DESC;
```

`stock_master` 누락:

```sql
WITH used_codes AS (
    SELECT stk_cd FROM trading_signals
    UNION SELECT stk_cd FROM candidate_pool_history
    UNION SELECT stk_cd FROM daily_indicators
    UNION SELECT stk_cd FROM ws_tick_data
    UNION SELECT stk_cd FROM vi_events
)
SELECT u.stk_cd
FROM used_codes u
LEFT JOIN stock_master sm ON sm.stk_cd = u.stk_cd
WHERE sm.stk_cd IS NULL
ORDER BY u.stk_cd;
```

보조 테이블 누락:

```sql
SELECT s.id, s.stk_cd, s.strategy, s.action
FROM trading_signals s
LEFT JOIN trade_plans p ON p.signal_id = s.id
WHERE s.action = 'ENTER'
  AND p.id IS NULL;

SELECT s.id, s.stk_cd, s.strategy, s.scored_at
FROM trading_signals s
LEFT JOIN signal_score_components c ON c.signal_id = s.id
WHERE s.scored_at IS NOT NULL
  AND c.id IS NULL;
```
