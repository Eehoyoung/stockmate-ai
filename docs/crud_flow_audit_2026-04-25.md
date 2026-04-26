# CRUD Flow Audit - 2026-04-25

대상: `stockmate-ai` 전체 서비스에서 실제 사용하는 PostgreSQL `public` 스키마 테이블/뷰.

점검 기준:
- 서비스가 의도한 시점에 데이터를 생성/수정/조회/삭제하는지
- 동일 테이블에 복수 작성자가 있어 충돌 가능성이 있는지
- 생명주기 이벤트, 집계, 감사 테이블이 누락 없이 기록되는지
- 현재 DB 상태와 코드가 서로 같은 모델을 보고 있는지

## 1. 결론

현재 컨테이너는 `docker compose up -d --build` 기준 정상 기동했고, Flyway는 `public` 스키마를 `33 - schema relationship consolidation`까지 적용했다.

핵심 원장은 `trading_signals`다. V33 이후 `open_positions`는 쓰기 대상 테이블이 아니라 `trading_signals` 기반 호환 뷰이며, 실제 포지션 상태는 `trading_signals.position_status`, `entry_*`, `exit_*`, `monitor_enabled` 컬럼으로 관리된다.

가장 큰 위험은 포지션 종료/성과 반영 경로가 둘로 나뉜 점이다. Python `ai-engine`의 `close_open_position()`은 `trading_signals`, `trade_outcomes`, `position_state_events`를 함께 갱신하지만, Java `SignalPerformanceScheduler`는 `TradingSignal.closeSignal()`만 호출해 일부 컬럼만 닫는다. 이 경우 실제 포지션이 조기 종료되거나, 감사/성과 테이블이 누락될 수 있다.

두 번째 위험은 `stock_master` 참조 무결성이 아직 완성되지 않은 점이다. V33 기동 로그에서 일부 FK 추가가 기존 데이터 누락 때문에 스킵되었다. 현재 `stock_master`는 후보군 기반으로만 채워져 전체 신호/지표 종목을 보장하지 못한다.

세 번째 위험은 종결 상태와 모니터링 상태가 불일치하는 실제 데이터가 있다는 점이다. 현재 `trading_signals`에는 `CANCELLED`이지만 `monitor_enabled=true`인 건이 63건, `EXPIRED`이면서 `position_status=ACTIVE`이고 `monitor_enabled=true`인 건이 1건 있다.

네 번째 위험은 테이블은 있으나 런타임 작성자가 없는 테이블이 존재한다는 점이다. `strategy_bucket_stats`, `trade_path_bars`, `open_positions_legacy`는 현재 운영 코드에서 실질 CRUD가 없다.

## 2. 실제 DB 테이블 현황

2026-04-25 현재 `pg_stat_user_tables` 기준 주요 row count:

| 테이블 | Row 수 | 상태 |
| --- | ---: | --- |
| `ws_tick_data` | 5,907,477 | 대량 적재 중 |
| `candidate_pool_history` | 14,202 | 적재 중 |
| `daily_indicators` | 3,070 | 적재 중 |
| `vi_events` | 2,941 | 적재 중 |
| `stock_master` | 1,041 | 적재 중이나 FK 완성 전 |
| `trading_signals` | 92 | 핵심 원장 |
| `signal_score_components` | 89 | AI 점수 세부 |
| `strategy_param_history` | 82 | 파라미터 이력 |
| `kiwoom_tokens` | 57 | 토큰 이력 |
| `rule_cancel_signal` | 24 | 취소 감사 |
| `position_state_events` | 18 | 포지션 이벤트 |
| `trade_plans` | 9 | 진입/청산 계획 |
| `trade_outcomes` | 0 | 아직 청산 성과 없음 또는 누락 |
| `strategy_bucket_stats` | 0 | 작성자 없음 |
| `trade_path_bars` | 0 | 작성자 없음 |
| `open_positions_legacy` | 0 | 레거시 |

뷰:
- `open_positions`: `trading_signals` 기반 호환 뷰
- `v_active_positions`: 활성 포지션 조회 뷰
- `v_portfolio_risk_snapshot`: 포트폴리오 리스크 조회 뷰

## 3. 주요 CRUD 플로우

### `trading_signals`

역할: 신호와 포지션 생명주기의 핵심 원장.

생성:
- Java `SignalService.processSignal()`이 전략 신호 수신 시 저장한다.
- Python `ai-engine.db_writer.insert_python_signal()`도 signal id가 없는 입력에 대해 생성한다.

수정:
- Java `SignalService`는 생성 직후 `signal_status=SENT`, 진입가가 있으면 `position_status=ACTIVE`, `entry_at=now`, `monitor_enabled=true`로 저장한다.
- Python `update_signal_score()`는 AI 점수, 액션, 지표, RR 필드를 갱신한다.
- Python `confirm_open_position()`은 `action=ENTER`, `position_status=ACTIVE`, 진입/TP/SL 정책을 확정한다.
- Python `cancel_open_position_by_signal()`은 취소 시 `signal_status=CANCELLED`, `position_status=CLOSED`로 닫는다.
- Python `close_open_position()`은 청산 시 `signal_status=WIN/LOSS`, `position_status=CLOSED`, `exit_*`, `monitor_enabled=false`를 갱신하고 `trade_outcomes`, `position_state_events`도 함께 기록한다.
- Java `PositionMonitorScheduler`도 활성화 시 손절/익절 조건에서 `recordExit()`를 호출한다. 기본값은 `JAVA_POSITION_MONITOR_ENABLED=false`.
- Java `SignalPerformanceScheduler`는 장중 10분마다 `SENT` 신호를 평가하고 `closeSignal()`로 닫을 수 있다.
- Java `TradingSignalRepository.expireOldSignals()`는 TTL이 지난 `PENDING/SENT` 신호를 `EXPIRED`로 바꾼다.

삭제:
- 런타임 삭제 없음.

판정:
- 위험 높음. `SignalPerformanceScheduler`가 실제 포지션 원장을 닫으면 Python 청산 플로우와 충돌한다.
- `closeSignal()`은 `exit_type`, `exit_price`, `exit_pnl_pct`, `exited_at`, `monitor_enabled=false`, `trade_outcomes`, `position_state_events`를 보장하지 않는다.
- 실제 DB에 `CANCELLED`이지만 `monitor_enabled=true`인 신호가 63건, `EXPIRED`이지만 `position_status=ACTIVE`인 신호가 1건 있다. 이는 종결 상태와 모니터링 상태가 서로 맞지 않는 데이터다.

권고:
- 실제 포지션 청산 소유자를 Python `ai-engine.close_open_position()` 하나로 고정한다.
- Java 성과 스케줄러는 포지션이 아닌 신호 품질 통계 전용으로 제한하거나 비활성화한다.
- 최소 조건으로 `position_status IS NULL` 또는 `action <> 'ENTER'` 대상만 평가하도록 막아야 한다.
- `CANCELLED`, `EXPIRED`, `WIN`, `LOSS` 상태 전환 시 항상 `monitor_enabled=false`, 비활성 포지션 상태 정리를 함께 수행한다.

### `signal_score_components`

역할: AI 점수 산출 세부 컴포넌트.

생성/수정:
- Python `insert_score_components()`가 upsert한다.

조회:
- Java API/DB 조회 계층에서 신호 상세 또는 진단용으로 사용 가능하다.

삭제:
- 없음.

판정:
- 단일 작성자라 안정적이다.

### `trade_plans`

역할: 진입/TP/SL/트레일링 계획.

생성/수정:
- Python `insert_python_signal()` 및 `confirm_open_position()`에서 upsert한다.

조회:
- Python `close_open_position()`이 청산 성과 기록 시 plan id를 참조한다.

삭제:
- 없음.

판정:
- Python 포지션 플로우를 탈 때는 정상이다.
- Java 청산 경로를 타면 plan/outcome/event 연결이 빠질 수 있다.

### `trade_outcomes`

역할: 최종 청산 성과.

생성:
- Python `close_open_position()`만 기록한다.

조회:
- 현재 코드상 핵심 운영 조회는 제한적이다.

삭제:
- 없음.

판정:
- 현재 row 수가 0이다. 실제 청산이 있었는데도 0이면 Java 청산 또는 수동 상태 변경으로 성과 기록이 누락된 것이다.

### `position_state_events`

역할: 포지션 생명주기 감사 로그.

생성:
- Python `insert_python_signal()`: `SIGNAL_CREATED`
- Python `confirm_open_position()`: `POSITION_OPENED`
- Python `cancel_open_position_by_signal()`: `SIGNAL_CANCELLED`
- Python `record_overnight_eval()`: overnight 관련 이벤트
- Python `close_open_position()`: `POSITION_CLOSED`

삭제:
- 없음.

판정:
- Python 경로는 감사 로그가 남는다.
- Java `SignalService`, `SignalPerformanceScheduler`, `PositionMonitorScheduler`는 동일 수준의 이벤트 보장을 하지 않는다.

### `candidate_pool_history`

역할: 전략별 후보군 출현 이력.

생성/수정:
- Java `CandidatePoolHistoryScheduler`가 장중 60초 주기로 Redis `candidates:s{n}:{market}`를 읽어 upsert한다.
- Java `SignalService.processSignal()`이 신호 생성 후 `led_to_signal=true`, `signal_generated_at=now`를 표시한다.

삭제:
- 없음.

판정:
- 후보 이력 적재는 정상 동작 중이다.
- `SignalService`가 사용하는 market 값과 후보 Redis 키의 market 값이 다르면 `led_to_signal` 마킹이 누락될 수 있다.
- V33에서 `stock_master` FK가 일부 스킵되어 종목 기준 무결성이 아직 강제되지 않는다.

### `stock_master`

역할: 종목 마스터.

생성/수정:
- Java `StockMasterScheduler`가 평일 09:10 후보 Redis 목록을 기반으로 Kiwoom `ka10001`을 조회해 upsert한다.

조회:
- 신호, 후보군, 지표, UI/API에서 종목명/시장/상태 참조.

삭제:
- 없음.

판정:
- 후보 기반 적재라 전체 universe를 보장하지 않는다.
- V33 로그상 `trading_signals`, `candidate_pool_history`, `daily_indicators` 일부 종목이 `stock_master`에 없어 FK 추가가 실패/스킵되었다.

권고:
- `trading_signals`, `candidate_pool_history`, `daily_indicators`, `ws_tick_data`, `vi_events`의 distinct `stk_cd`를 기준으로 `stock_master` 백필 작업을 먼저 수행한다.
- 백필 후 follow-up migration에서 FK를 재시도한다.

### `ws_tick_data`

역할: 실시간 체결/호가/예상체결 이벤트 저장.

생성:
- Python `websocket-listener.db_writer.insert_tick_event()`가 주 작성자다.
- Java `DataPersistenceScheduler.persistWsSnapshots()`는 Redis `ws:db_writer:event_mode`가 없을 때만 60초 스냅샷 fallback 저장을 수행한다.

삭제:
- Java `DataPersistenceScheduler.cleanupOldData()`가 23:30에 3일 초과 데이터를 삭제한다.

판정:
- row 수가 590만 건으로 가장 크다.
- Python event writer와 Java fallback의 역할 분리가 되어 있으나, Redis marker TTL/갱신 실패 시 중복성 스냅샷이 들어갈 수 있다.

권고:
- `ws:db_writer:event_mode` TTL과 갱신 주기를 운영 지표로 노출한다.
- 대량 테이블이므로 보관 기간, 파티셔닝, 인덱스 비용을 별도 점검해야 한다.

### `vi_events`

역할: VI 발동/해제 이벤트 저장.

생성:
- Python `websocket-listener.db_writer.insert_vi_event()`가 주 작성자다.
- Java `DataPersistenceScheduler.persistViSnapshots()`는 event mode가 없을 때 fallback 저장한다.

삭제:
- 런타임 삭제 정책 없음.

판정:
- 적재 중이나 보관 정책이 없다.

권고:
- 보관 기간이 필요한 운영 데이터인지, 영구 감사 데이터인지 결정해야 한다.

### `daily_indicators`

역할: 일봉 기반 기술 지표.

생성/수정:
- Java `DataPersistenceScheduler.persistDailyIndicators()`가 09:20, 13:20에 후보/오늘 신호/활성 포지션/활성 종목을 대상으로 upsert한다.
- Python `ai-engine.db_writer.upsert_daily_indicators()`도 동일 테이블에 upsert 경로를 가진다.

삭제:
- 없음.

판정:
- 복수 작성자 구조다. 같은 `(date, stk_cd)`에 대해 Java와 Python이 다른 산식/시점으로 갱신할 수 있다.

권고:
- 단일 작성자를 정한다. Java가 Kiwoom 원천 적재자라면 Python은 read-only로 두는 쪽이 단순하다.

### `portfolio_config`

역할: 포트폴리오 제한, 일일 손실 한도, 최대 포지션 수.

생성/수정:
- Java 설정 서비스/API가 기본값 생성 및 수정.

조회:
- Java `SignalService`가 신규 신호 저장 전 `active`, `maxConcurrentPositions`, `dailyLossLimit` 등을 확인한다.

삭제:
- 없음.

판정:
- 현재 DB row 수는 1건으로 기본 설정은 존재한다.
- 설정 row가 삭제되거나 비활성화될 경우 `SignalService`의 리스크 체크가 의도보다 느슨해질 수 있으므로 유지보수 API에서 삭제/비활성 처리를 제한하는 편이 안전하다.

### `daily_pnl`

역할: 일별 PnL 집계.

생성/수정:
- Java `SignalPerformanceScheduler.calculateDailyPnl()`가 15:45에 생성한다.

조회:
- AI/대시보드 조회에서 사용.

삭제:
- 없음.

판정:
- 집계 소유자가 Java `SignalPerformanceScheduler`다.
- 같은 스케줄러가 실시간 신호 종료도 담당하므로, 이 스케줄러를 제한할 때 일별 집계 기능은 분리해야 한다.

### `strategy_daily_stats`

역할: 전략별 일별 성과.

생성/수정:
- Java `SignalPerformanceScheduler.updateStrategyStats()`가 15:45에 upsert한다.

삭제:
- 없음.

판정:
- `daily_pnl`과 같은 의존성을 가진다.

### `market_daily_context`

역할: 시장 일일 컨텍스트와 성과 요약.

생성/수정:
- Java `TradingScheduler.saveMorningMarketContext()`가 07:55에 생성/갱신한다.
- Java `TradingScheduler`가 15:35 성과 요약 후 갱신한다.

조회:
- AI scoring/context 계층에서 참조.

삭제:
- 없음.

판정:
- 단일 작성자에 가깝고 정상적이다.

### `strategy_param_history`

역할: 전략 파라미터 이력.

생성:
- Java 스케줄러/API가 파라미터 snapshot을 저장한다.

조회:
- 전략/임계값 서비스에서 최근 파라미터를 참조한다.

삭제:
- 없음.

판정:
- 정상. 다만 row가 누적되므로 장기 보관 정책은 필요하다.

### `kiwoom_tokens`

역할: Kiwoom 접근 토큰 이력 및 활성 토큰 관리.

생성/수정:
- Java `TokenService`가 06:50, 07:25 등 토큰 발급/갱신 시 기존 활성 토큰을 비활성화하고 새 토큰을 저장한다.

조회:
- Java `TokenService`와 외부 API 호출 계층이 사용한다.

삭제:
- 없음.

판정:
- 기능상 정상.
- row가 계속 누적되므로 만료 토큰 정리 정책은 필요하다.

### `human_confirm_requests`

역할: 사람 승인 요청 상태 저장.

생성:
- Python `insert_human_confirm_request()`가 승인 요청 생성.

수정:
- Telegram bot `confirmStore.js`가 조회, sent 표시, approve/reject를 수행한다.
- Python `update_human_confirm_request_status()`도 상태 변경 경로를 가진다.
- Java `HumanConfirmCleanupScheduler`가 만료/완료된 요청을 정리한다.

삭제:
- Java cleanup scheduler가 조건부 삭제한다.

판정:
- DB 상태와 Redis queue가 분리되어 있다.
- Telegram approve가 DB를 `APPROVED`로 바꾼 뒤 Redis `confirmed_queue` enqueue에 실패하면 승인 상태는 남지만 실제 체결 플로우가 진행되지 않을 수 있다.

권고:
- `APPROVED`인데 `confirmed_queue`에 반영되지 않은 요청을 재전송하는 보상 작업 또는 outbox 패턴이 필요하다.

### `overnight_evaluations`

역할: 오버나잇 보유 판단 결과.

생성:
- Python `overnight_worker`가 `insert_overnight_eval()`로 저장한다.

수정/검증:
- Java `OvernightEvaluationVerificationScheduler`가 다음 장 시작 후 검증 갱신을 수행한다.
- Python `record_overnight_eval()`은 `trading_signals` 상태와 이벤트를 함께 갱신한다.

삭제:
- 없음.

판정:
- 현재 row 수 0이라 운영 플로우가 아직 실제로 돌지 않았거나 조건 미충족 상태다.

### `ai_cancel_signal`, `rule_cancel_signal`

역할: AI/룰 기반 취소 감사 기록.

생성:
- Python queue worker가 CANCEL 액션 처리 시 각각 insert한다.

수정/삭제:
- 없음.

판정:
- append-only 감사 테이블로 정상이다.
- 조회 API/리포트가 없으면 운영자가 취소 사유를 보기 어렵다.

### `risk_events`

역할: 리스크 차단/한도 위반 이벤트.

생성:
- Java `SignalService`가 신규 신호 처리 중 포트폴리오 설정 위반 시 저장한다.

삭제:
- 없음.

판정:
- row 수 0은 현재 차단 이벤트가 없었다는 의미일 수 있다.
- `portfolio_config`는 현재 1건 존재하므로 기본 리스크 설정은 로드 가능한 상태다.

### `news_analysis`

역할: 뉴스 분석 결과.

생성:
- Java `NewsAlertScheduler`가 `news_alert_queue`를 소비해 저장한다.
- 해당 스케줄러는 기본 설정상 비활성화되어 있다.

삭제:
- 없음.

판정:
- row 수 0이며 현재는 실운영 저장 경로가 사실상 꺼져 있다.

### `economic_events`

역할: 경제 이벤트 캘린더.

상태:
- Java `EconomicCalendarScheduler`는 주석상 비활성화되어 있다.
- 현재 row 수 0이다.

판정:
- 테이블은 존재하지만 운영 적재 플로우는 꺼져 있다.
- 시장 컨텍스트에서 경제 이벤트를 쓰려면 별도 활성화/적재 정책이 필요하다.

### `strategy_bucket_stats`

역할: 전략 버킷별 성과 통계로 보인다.

상태:
- 마이그레이션으로 생성되었으나 런타임 CRUD 참조가 없다.
- row 수 0이다.

판정:
- 미구현 테이블이다. 사용 계획이 없다면 제거 후보, 사용할 계획이면 집계 job이 필요하다.

### `trade_path_bars`

역할: 진입 후 가격 경로 bar 저장으로 보인다.

상태:
- 마이그레이션으로 생성되었으나 런타임 CRUD 참조가 없다.
- row 수 0이다.

판정:
- 미구현 테이블이다.
- `trade_outcomes` 분석 품질을 높이려면 포지션 보유 중 일정 주기로 경로를 저장하는 writer가 필요하다.

### `open_positions`, `open_positions_legacy`

역할:
- `open_positions`: 현재는 `trading_signals` 기반 호환 뷰.
- `open_positions_legacy`: V33 이전 호환용 백업 테이블.

조회:
- Java `OpenPosition` 엔티티와 `OpenPositionRepository`가 남아 있다.
- Telegram/AI status는 DB가 아니라 Redis `open_positions` 키를 카운트한다.

생성/수정/삭제:
- DB 런타임 write 없음.

판정:
- JPA 엔티티가 뷰를 테이블처럼 표현하고 있어 향후 쓰기 코드가 추가되면 장애 가능성이 있다.

권고:
- `OpenPosition` 엔티티를 read-only로 명시하거나 제거한다.
- 신규 코드는 `TradingSignalRepository.findAllActivePositions()`를 사용하도록 규칙화한다.

## 4. 실행 시점별 플로우

장 시작 전:
- 06:50, 07:25: Java `TradingScheduler`가 Kiwoom 토큰 갱신, `kiwoom_tokens` 저장.
- 07:50: S1 후보군 preload, Redis 중심.
- 07:55: `market_daily_context` morning 저장.
- 08:45: 예상체결가 preload, Redis 중심.

장중:
- 후보군은 Redis에 생성되고, Java `CandidatePoolHistoryScheduler`가 60초마다 `candidate_pool_history`에 upsert한다.
- 신호 발생 시 Java `SignalService`가 `trading_signals` 생성, `candidate_pool_history` led flag 갱신, Telegram/AI queue로 전달한다.
- Python AI queue worker가 점수/컴포넌트/액션을 반영하고, 진입 확정 시 `trade_plans`, `position_state_events`, `trading_signals`를 갱신한다.
- WebSocket listener가 `ws_tick_data`, `vi_events`를 event 단위로 저장한다.
- Java DataPersistenceScheduler는 event writer marker가 없을 때만 fallback snapshot 저장한다.
- Java `SignalPerformanceScheduler`는 10분마다 `SENT` 신호 성과를 평가한다. 이 경로는 실제 포지션과 충돌 가능성이 있다.

장 마감:
- 15:30: 오래된 신호 만료.
- 15:35: 일일 요약 생성, Telegram queue, `market_daily_context` performance 갱신.
- 15:45: `daily_pnl`, `strategy_daily_stats` 집계.
- 23:30: `ws_tick_data` 3일 초과 삭제.

## 5. 우선 조치 목록

1. Java `SignalPerformanceScheduler`의 포지션 종료 기능을 중단하거나 대상 조건을 제한한다.
   - 실제 청산은 Python `close_open_position()`으로 일원화한다.
   - 일별 집계 기능은 별도 job으로 분리한다.

2. `trading_signals` 상태 불일치를 정리하고 재발 방지 로직을 추가한다.
   - 현재 확인된 불일치: terminal status인데 `monitor_enabled=true` 64건.
   - `CANCELLED/EXPIRED/WIN/LOSS` 전환 시 `monitor_enabled=false`를 강제한다.
   - `EXPIRED`이면서 `position_status=ACTIVE`인 건은 실제 보유 여부를 확인한 뒤 `CLOSED` 또는 정상 활성 포지션으로 보정한다.

3. `stock_master` 백필 후 FK를 재적용한다.
   - 기준: `trading_signals`, `candidate_pool_history`, `daily_indicators`, `ws_tick_data`, `vi_events`의 distinct `stk_cd`.
   - 현재 누락 distinct code 수: 2,901개.
   - 백필 실패 종목은 별도 리포트로 남긴다.

4. `daily_indicators` 작성자를 하나로 정한다.
   - 권장: Java Kiwoom 적재를 canonical writer로 두고 Python은 조회만 수행.

5. `human_confirm_requests` 승인 후 enqueue 실패 보상 로직을 추가한다.
   - `APPROVED` 상태이지만 `last_enqueued_at` 기준 진행되지 않은 요청을 재전송한다.

6. 미사용 테이블의 처리 방향을 결정한다.
   - `strategy_bucket_stats`, `trade_path_bars`: 구현 예정이면 writer/scheduler 추가, 아니면 제거 후보.
   - `open_positions_legacy`: 보관 기간 후 제거 후보.

7. `OpenPosition` JPA 엔티티를 read-only 또는 제거 대상으로 정리한다.
   - 현재 DB 객체가 뷰이므로 쓰기 코드가 생기면 실패한다.

## 6. 운영 점검 SQL

활성 포지션과 미완료 성과 누락 확인:

```sql
SELECT id, stk_cd, signal_status, position_status, action, entry_at, exited_at, monitor_enabled
FROM trading_signals
WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
   OR monitor_enabled = true
ORDER BY created_at DESC;
```

닫힌 포지션 중 `trade_outcomes` 누락 확인:

```sql
SELECT s.id, s.stk_cd, s.signal_status, s.position_status, s.exited_at
FROM trading_signals s
LEFT JOIN trade_outcomes o ON o.signal_id = s.id
WHERE s.position_status = 'CLOSED'
  AND s.action = 'ENTER'
  AND o.id IS NULL
ORDER BY s.exited_at DESC NULLS LAST;
```

`stock_master` 누락 종목 확인:

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

승인 후 큐 반영 의심 요청:

```sql
SELECT id, signal_id, status, last_enqueued_at, updated_at
FROM human_confirm_requests
WHERE status = 'APPROVED'
  AND (last_enqueued_at IS NULL OR last_enqueued_at < updated_at)
ORDER BY updated_at DESC;
```
