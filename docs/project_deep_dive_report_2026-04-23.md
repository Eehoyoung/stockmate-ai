# StockMate AI 프로젝트 심층 탐색 보고서

작성일: 2026-04-23 KST  
작성 방식: CEO 총괄 + 하위 탐색 에이전트 4개 병렬 투입  
대상 저장소: `C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai`

## 1. 탐색 조직도

이번 탐색은 계층형으로 수행했다.

| 계층 | 역할 | 탐색 범위 |
|---|---|---|
| CEO / 총괄 | 전체 아키텍처, 서비스 간 경계, 최종 위험도 통합 | 루트, 설정, Redis/DB/큐 흐름, 검증 |
| API 리드 | Java Spring Boot 오케스트레이터 | `api-orchestrator/` |
| AI/퀀트트레이더 리드 | 전략, 스코어링, TP/SL, 포지션, 뉴스/Claude | `ai-engine/` |
| 실시간 데이터 리드 | Kiwoom WebSocket, Redis/PG writer, health | `websocket-listener/` |
| Telegram/운영 리드 | 봇, 운영 스크립트, 문서 불일치 | `telegram-bot/`, `docs/`, 루트 운영 파일 |

주의: 작업트리는 이미 다수 파일이 수정된 상태였다. 본 탐색은 읽기 중심으로 진행했고, 기존 변경분은 건드리지 않았다.

## 2. 전체 시스템 요약

StockMate AI는 네 개 런타임이 Redis와 PostgreSQL을 중심으로 결합된 다중 서비스 자동매매 보조 시스템이다.

1. `api-orchestrator/`: Spring Boot API, Kiwoom REST, 스케줄러, JPA/Flyway, 후보군/시그널 저장.
2. `ai-engine/`: Python 전략 스캐너, 규칙 점수, Claude 분석, TP/SL, 포지션 감시, 뉴스/리포트.
3. `websocket-listener/`: Python Kiwoom WebSocket 단독 수신기, Redis 실시간 시세 저장, 선택적 PG 직접 적재.
4. `telegram-bot/`: Node.js Telegraf 봇, 명령 처리, `ai_scored_queue` 소비, 운영자 알림/제어.

핵심 데이터 버스는 Redis다. 주요 큐와 키는 다음과 같다.

| Redis 키/큐 | 생산자 | 소비자 | 의미 |
|---|---|---|---|
| `kiwoom:token` | `api-orchestrator` | `ai-engine`, `websocket-listener` | Kiwoom 인증 토큰 |
| `telegram_queue` | `api-orchestrator`, `ai-engine.strategy_runner` | `ai-engine.queue_worker` | 1차 후보/시그널 입력 |
| `ai_scored_queue` | `ai-engine.queue_worker`, 모니터/뉴스 worker | `telegram-bot` | 최종 알림 출력 |
| `vi_watch_queue` | `websocket-listener.redis_writer`, `ai-engine.vi_watch_worker` | `ai-engine.strategy_runner` | VI 해제 후 눌림 감시 |
| `human_confirm_queue` | `ai-engine.confirm_gate_redis` | `telegram-bot.confirmGate` | 인간 승인 요청, 현재 사실상 비활성 |
| `confirmed_queue` | `telegram-bot` | `ai-engine.confirm_worker` | 인간 승인 후 분석 대상 |
| `ws:tick:{stkCd}` | `websocket-listener` | Java/Python/Telegram | 체결 실시간 스냅샷 |
| `ws:hoga:{stkCd}` | `websocket-listener` | Java/Python/Telegram | 호가 잔량 |
| `ws:expected:{stkCd}` | Java/Python WS | Java/Python | 예상체결/프리마켓 |
| `vi:{stkCd}` | `websocket-listener` | Java/Python | VI 상태 |
| `candidates:s{N}:{market}` | Java/Python 후보군 빌더 | 전략 스캐너, WS 구독 | 전략별 후보 풀 |
| `candidates:watchlist` | Java/Python/수동 명령 | WS 구독, 지표 저장 | 실시간 감시 대상 |

PostgreSQL은 Flyway 기반으로 `trading_signals`, `ws_tick_data`, `vi_events`, `daily_indicators`, `portfolio_config`, `risk_events`, `candidate_pool_history`, `strategy_daily_stats`, `market_daily_context`, `overnight_evaluations` 등을 관리한다.

## 3. 전체 핵심 플로우

### 3.1 장전 준비

1. `api-orchestrator`의 `TradingScheduler`가 토큰을 갱신한다.
2. `CandidateService`와 `candidates_builder.py`가 Kiwoom API로 후보군을 만든다.
3. `websocket-listener`가 07:30 이후 Kiwoom WS에 로그인하고 phase별 구독을 시작한다.
4. `ws:expected:*`, `ws:hoga:*`, `ws:tick:*`, `ws:py_heartbeat`가 Redis에 쌓인다.
5. `market_daily_context`, 뉴스 컨트롤, 경제 이벤트 플래그가 장전 판단 재료가 된다.

### 3.2 장중 신호 생성

1. Java와 Python 전략 스캐너가 S1-S15 전략별 후보를 훑는다.
2. 신호는 `telegram_queue`로 들어간다.
3. `ai-engine.queue_worker`가 Redis 실시간 컨텍스트를 붙인다.
4. `scorer.py`가 규칙 점수를 산출한다.
5. 점수가 기준 이상이면 Claude 분석을 호출하고, 아니면 rule-only cancel 또는 fallback enter로 분기한다.
6. 결과는 `ai_scored_queue`와 DB에 기록된다.
7. `telegram-bot`이 최종 메시지를 운영자에게 전송한다.

### 3.3 포지션 관리

1. 진입된 신호는 `trading_signals`의 `position_status`, `signal_status`, TP/SL 필드로 관리된다.
2. `position_monitor.py`와 `PositionMonitorScheduler`가 TP1/TP2/SL/trailing/time-stop을 감시한다.
3. `position_reassessment.py`가 추세/모멘텀/호가/강도 스냅샷을 갱신한다.
4. 장마감 후 `overnight_worker.py`와 Java overnight scheduler가 보유/청산 판단을 수행한다.
5. 결과는 Telegram 청산 신호, `daily_pnl`, `strategy_daily_stats`, `overnight_evaluations`로 이어진다.

## 4. 서비스별 기능 지도

### 4.1 `api-orchestrator/`

핵심 진입점:

- `ApiOrchestratorApplication.java`: Spring Boot 시작, `.env` 기반 환경 주입.
- `ApplicationStartupRunner.java`: 초기 포트폴리오/전략 파라미터/토큰 상태 확인.
- `TradingController.java`: 외부 운영 API 대부분을 담당.

주요 기능:

- 토큰: `TokenService`, `KiwoomTokenRepository`, Redis `kiwoom:token`.
- Kiwoom REST: `KiwoomApiService`, `KiwoomStockService`, `KiwoomRateLimiter`.
- 후보군: `CandidateService`, `BidUpperService`, `PriceSurgeService`, `VolSurgeService`.
- 전략 실행: `StrategyService`의 S1/S3/S4/S5/S6/S10/S12 등 Java 경로와 Python 경로 병존.
- 시그널 저장/발행: `SignalService`.
- 스케줄러: `TradingScheduler`, `DataPersistenceScheduler`, `PositionMonitorScheduler`, `SignalPerformanceScheduler`, `StockMasterScheduler`, `OvernightRiskScheduler`, `NewsAlertScheduler`, `DataQualityScheduler`.
- DB 스키마: `src/main/resources/db/migration/`의 `V1`-`V30`.

API 표면:

- `/api/trading/token/refresh`
- `/api/trading/signals/today`
- `/api/trading/signals/stats`
- `/api/trading/strategy/s1/run`, `/s2/run`, `/s3/run`, `/s4/run`, `/s5/run`, `/s6/run`, `/s7/run`, `/s10/run`, `/s12/run`
- `/api/trading/ws/start`, `/ws/stop`, `/ws/connect`, `/ws/disconnect`
- `/api/trading/candidates`
- `/api/trading/health`
- `/api/trading/control/{mode}`
- `/api/trading/signals/performance`
- `/api/trading/signals/performance/summary`
- `/api/trading/calendar/week`, `/calendar/today`, `/calendar/event`
- `/api/trading/signals/stock/{stkCd}`
- `/api/trading/signals/strategy-analysis`
- `/api/trading/score/{stkCd}`
- `/api/trading/candidates/pool-status`
- `/api/trading/strategy-params/{strategy}`, `/strategy-params`
- `/api/trading/monitor/health`
- `/api/trading/db/table-status`

주요 위험:

- `StrategyService.resolveStkNm()` 주변에 `nm != null || !nm.toString().isEmpty()` 형태의 NPE 후보가 있다면 `&&`로 바꿔야 한다.
- `TradingController.setTradingControl()`에서 `news:prev_control`에 이전 값이 아니라 새 값을 넣는 구조다. Python news scheduler와 상태 복원 의미가 어긋날 수 있다.
- `TradingScheduler.preparePreOpenData()`는 `pred_pre_pric`를 쓰는데 overnight 계열은 `exp_cntr_pric` 또는 raw field를 찾는다. 익일 평가 fast path가 빗나갈 수 있다.
- `RedisConfig`는 비밀번호가 없으면 실패하는 쪽인데 `application.yml`은 빈 문자열 기본값을 둔다. 로컬/테스트 환경과 충돌한다.
- `SignalService.processSignal()`은 일일 카운트를 먼저 증가시킨 뒤 포지션/쿨다운/한도에서 탈락시킬 수 있다. 거절 신호가 쿼터를 소모한다.
- `StockMasterScheduler`는 종목을 계속 active로만 갱신하는 구조라 active universe가 비대해질 수 있다.
- `DataPersistenceScheduler.persistViSnapshots()`의 `redis.keys("vi:*")`는 운영 Redis에서 블로킹 위험이 높다.
- `EconomicCalendarScheduler`가 비활성이라면 `calendar:pre_event` 기반 뉴스/거래 제어가 실제로 갱신되지 않을 수 있다.
- `V30__merge_open_positions_into_trading_signals.sql` 이후 `open_positions`가 뷰/트리거 호환층으로 보이며, JPA 엔티티와 DB 구조 정합성이 가장 취약한 지점이다.

성능 개선:

- Kiwoom API 호출은 서비스/스케줄러 곳곳에 분산되어 있다. 호출량 budget, 세마포어, 캐시, backpressure를 공통화해야 한다.
- `CandidateService.getCandidatesWithTags()`는 후보별 Redis 조회 N+1 가능성이 있다.
- `SignalPerformanceScheduler`는 당일 SENT를 반복 스캔한다. 변경분 기반 또는 상태 인덱스가 필요하다.
- `DataPersistenceScheduler`는 `KEYS` 대신 `SCAN` 또는 VI key index set을 써야 한다.
- `TradingScheduler.preloadCandidatePools()`는 고정 풀에 작업을 던지지만 이전 작업 overlap 방지가 부족하다.

### 4.2 `ai-engine/`

핵심 진입점:

- `engine.py`: Redis/PG 연결 후 주요 worker를 모두 task로 실행.
- `queue_worker.py`: `telegram_queue` 소비, rule score/Claude/DB 저장/`ai_scored_queue` 발행.
- `strategy_runner.py`: 시간대별 S1-S15 전략 실행.
- `candidates_builder.py`: 후보군 생성.
- `tp_sl_engine.py`: 전략별 TP/SL/RR/trailing/time-stop 계산.
- `position_monitor.py`, `position_reassessment.py`, `overnight_worker.py`: 포지션 생명주기.

전략 지도:

| 전략 | 파일 | 성격 |
|---|---|---|
| S1_GAP_OPEN | `strategy_1_gap_opening.py` | 장초반 갭/예상체결 |
| S2_VI_PULLBACK | `strategy_2_vi_pullback.py` | VI 해제 후 눌림 |
| S3_INST_FRGN | `strategy_3_inst_foreign.py` | 기관/외국인 수급 |
| S4_BIG_CANDLE | `strategy_4_big_candle.py` | 대양봉/거래량 |
| S5_PROG_FRGN | `strategy_5_program_buy.py` | 프로그램+외국인 |
| S6_THEME_LAGGARD | `strategy_6_theme.py` | 테마 후발주 |
| S7_ICHIMOKU_BREAKOUT | `strategy_7_ichimoku_breakout.py` | 일목 돌파 |
| S8_GOLDEN_CROSS | `strategy_8_golden_cross.py` | 골든크로스 |
| S9_PULLBACK_SWING | `strategy_9_pullback.py` | 추세 눌림 |
| S10_NEW_HIGH | `strategy_10_new_high.py` | 신고가/돌파 |
| S11_FRGN_CONT | `strategy_11_frgn_cont.py` | 외국인 연속 매수 |
| S12_CLOSING | `strategy_12_closing.py` | 종가 강도 |
| S13_BOX_BREAKOUT | `strategy_13_box_breakout.py` | 박스 돌파 |
| S14_OVERSOLD_BOUNCE | `strategy_14_oversold_bounce.py` | 과매도 반등 |
| S15_MOMENTUM_ALIGN | `strategy_15_momentum_align.py` | 모멘텀 정렬 |

퀀트 관점 핵심:

- `scorer.py`는 `vol_score`, `momentum_score`, `technical_score`, `demand_score`, `time_bonus`, `risk_penalty`로 점수를 분해한다.
- `strategy_meta.py`는 swing/day 전략 구분과 threshold를 제공한다.
- `tp_sl_engine.py`는 전략별 TP1/TP2/SL, RR, trailing, time stop을 계산한다.
- `overnight_scorer.py`는 야간 보유 점수를 따로 산출한다.
- `downtrend_detector.py`, `position_reassessment.py`는 레짐/추세 반전 감시에 활용 가능하다.

주요 위험:

- `engine.py`의 `enable_confirm = False` 하드코딩으로 승인 게이트가 비활성이다.
- `tp_sl_engine.py`의 `compute_rr()` 내부 `strategy` 미정의 참조 후보는 호출 시 `NameError` 위험이 있다.
- `db_writer.insert_score_components()`가 저장하려는 `base_score`와 `scorer.py` components 구조가 어긋날 수 있다.
- `status_report_worker.py`에서 S9 후보풀 키가 `candidates:s8:*`로 잡힌 후보가 있다. S9 상태 집계 왜곡 위험.
- `analyzer.py`의 KOSPI/KOSDAQ 비용 모델이 동일하게 보인다. 실제 거래비용/슬리피지 반영이 부족할 수 있다.
- `strategy_meta.py`와 `scorer.py`의 Claude threshold가 중복/불일치한다.
- Claude 실패 또는 일일 한도 초과 시 `queue_worker.py`가 rule-only ENTER로 기울 수 있다. 모델 장애가 진입 완화로 이어지는 것은 실전 리스크다.
- dedup이 `scanner:dedup:{strategy}:{stk_cd}` 단위라 전략 간 동일 종목 중복 진입을 완전히 막지 못한다.
- Claude JSON 파싱이 문자열 블록 추출에 의존한다. 출력 형식 흔들림과 프롬프트 주입에 취약하다.
- 포지션 감시/재평가가 종목별 Redis + Kiwoom 호출을 많이 수행한다. 보유 수 증가 시 병목 가능성이 높다.

퀀트 개선:

- 글로벌 dedup: `stk_cd` 기준 전역 진입 쿨다운을 별도로 둬야 한다.
- 비용 내재 RR: `tp_sl_engine.py`의 RR 필터에 수수료/슬리피지를 강제 반영해야 한다.
- 레짐 필터: 시장/섹터/종목 추세를 `CONTINUE/CAUTIOUS/PAUSE`보다 세분화해 전략별로 적용해야 한다.
- walk-forward 백테스트: 전략별 threshold는 고정 휴리스틱보다 기간별 out-of-sample 검증이 필요하다.
- 손절 우선순위: time-stop, trailing, hard SL, trend reversal 간 충돌 우선순위를 문서/테스트로 고정해야 한다.
- 스윙/데이 분리: 동일 전략이라도 당일 청산형과 overnight 허용형의 손익분포가 다르므로 별도 평가해야 한다.

### 4.3 `websocket-listener/`

핵심 진입점:

- `main.py`: Redis/PG/health/WS loop 기동.
- `ws_client.py`: Kiwoom WS 연결, 로그인, phase별 구독, 재연결, 메시지 처리.
- `redis_writer.py`: Redis 실시간 시세 저장.
- `db_writer.py`: 선택적 PG 직접 적재.
- `health_server.py`: `/health`.

기능:

- Kiwoom WS LOGIN 후 `0B`, `0H`, `0D`, `1h` 타입을 처리한다.
- phase는 `pre_open`, `pre_market`, `market`, `closed`로 나뉜다.
- `candidates:watchlist`, `candidates:watchlist:priority`를 바탕으로 구독 대상을 정한다.
- VI 해제 이벤트는 `vi_watch_queue`로 들어가 S2 전략의 재료가 된다.
- `ws:py_heartbeat`로 AI/Java가 WS 상태를 판단한다.

주요 위험:

- `ws_client.py`의 `subscribed_set` 초기화가 실제 REG 결과와 다를 수 있다. 동적 구독 누락 위험.
- `db_writer.py`의 `_f/_i`와 `redis_writer.py` 일부 파싱이 `abs()` 또는 `replace("-", "")`를 사용한다. 등락 방향성이 사라질 수 있다.
- Redis/PG writer는 예외를 로그만 남기고 재시도 큐가 없다. 순간 장애는 데이터 손실로 이어진다.
- WS 메시지 idempotency가 없다. 재연결/재전송 시 PG 중복 가능성이 있다.
- `/health`가 PG writer 상태를 반영하지 않는다.
- token 부재 시 최대 60초 대기 후 추가 30초 sleep이 있어 기동 지연이 커질 수 있다.
- 워치리스트 변경을 코드 단위로 순차 REG/UNREG한다. 후보 수가 많아지면 WS 송신 병목.

성능/운영 개선:

- Redis write는 pipeline으로 묶는다.
- PG direct insert는 비동기 배치 writer task로 분리한다.
- 구독은 전체 재구독보다 diff 기반 batch로 바꾼다.
- health에 PG writer 상태, 최근 write 실패 수, 마지막 LOGIN 성공 시각, reconnect count를 추가한다.
- Kiwoom payload 필드 스키마 검증을 추가한다.

### 4.4 `telegram-bot/`

핵심 진입점:

- `src/index.js`: Telegraf 기동, 권한 필터, 명령/callback 등록.
- `src/handlers/commands.js`: 수동 명령.
- `src/handlers/signals.js`: `ai_scored_queue` polling 및 broadcast.
- `src/handlers/confirmGate.js`: 인간 확인 게이트, 현재 비활성.
- `src/services/kiwoom.js`: Java/AI HTTP bridge.
- `src/services/redis.js`: Redis queue/시세 조회.
- `src/services/confirmStore.js`: `human_confirm_requests` DB 조회/상태 변경.
- `src/utils/formatter.js`: 알림 메시지 포매팅.

등록 명령:

`/ping`, `/health`, `/status`, `/signals`, `/perf`, `/track`, `/analysis`, `/history`, `/quote`, `/score`, `/claude`, `/candidates`, `/report`, `/news`, `/sector`, `/events`, `/settings`, `/filter`, `/watchAdd`, `/watchRemove`, `/confirmPending`, `/reanalyze`, `/pause`, `/resume`, `/errors`, `/strategy`, `/token`, `/wsStart`, `/wsStop`, `/help`, `/start`.

주요 위험:

- `confirmGate.js`의 `isConfirmGateEnabled()`가 `false`를 반환해 확인 게이트가 사실상 꺼져 있다.
- `commands.js`에는 return 뒤 레거시 dead code가 남아 있다. `/status`, `/claude`, `/errors` 주변이 대표적이다.
- `signals.js` rate limit은 프로세스 메모리 기반이다. PM2 cluster나 재기동 시 전역 제한이 아니다.
- `logger.js`는 파일 append만 하며 rotation이 없다.
- Redis password 요구 수준이 서비스별로 다르다. Docker Compose는 requirepass를 쓰지만 Node Redis는 password 없이도 붙으려 한다.
- `bot.launch()`를 await하지 않아 시작 실패 처리와 부트 순서가 약하다.

운영 개선:

- rate limit, confirm gate 상태를 Redis 기반 공유 상태로 옮긴다.
- `/status`에 `telegram_queue`, `ai_scored_queue`, `human_confirm_queue`, `confirmed_queue`, `error_queue`를 같이 보여준다.
- confirm flow를 문서화하고 `/help`에서 하나의 묶음으로 안내한다.
- log rotation 또는 외부 수집기를 붙인다.
- `package.json`의 `npm test`가 더미 실패라면 README에 명시하거나 실제 테스트 묶음으로 바꾼다.

### 4.5 루트 운영/문서

루트 운영 파일:

- `docker-compose.yml`: Redis/Postgres만 띄움.
- `ecosystem.config.js`: PM2로 `ws-listener`, `ai-engine`, `telegram-bot` 실행.
- `stockmate.sh`: Java JAR + PM2 운영 스크립트.
- `.env`, `.env.example`: Kiwoom/Redis/Postgres/Telegram/Claude 설정.
- `AGENTS.md`, `CLAUDE.md`: 작업 지침.

주요 위험:

- `docker-compose.yml`의 한글 주석이 깨져 보인다. 파일 인코딩 일관성 점검 필요.
- `stockmate.sh`는 Redis/Postgres 기동을 보장하지 않는다. 운영자가 순서를 기억해야 한다.
- 문서 중 일부는 계획 문서와 현재 구현이 섞여 있다. 예: `docs/telegram_dead_code_plan.md`, `docs/scorer_telegram_upgrade_plan.md`.
- 루트 `.env`가 실제 값으로 존재한다. 커밋 여부와 별개로 운영 보안 관리 대상이다.

## 5. 최상위 위험 우선순위

| 우선순위 | 영역 | 문제 | 영향 | 권장 조치 |
|---|---|---|---|---|
| P0 | 승인 게이트 | Java/Python/Telegram 모두 confirm flow 흔적은 있으나 실제 비활성 | 인간 승인 기대 시 미작동 | `ENABLE_CONFIRM_GATE` 설계 확정 후 end-to-end 테스트 |
| P0 | 포지션/DB | `open_positions` 뷰/트리거와 JPA 엔티티 혼재 | 포지션 상태 불일치 | `trading_signals` 중심으로 단일 source of truth 확정 |
| P0 | TP/SL | `compute_rr()` NameError 후보, 비용 반영 미흡 | 진입/청산 기준 왜곡 | 재현 테스트와 비용 반영 RR 고정 |
| P0 | Redis key 정합성 | `ws:expected` 필드명이 Java/Python/overnight에서 불일치 | 익일 평가/갭 판단 실패 | 실시간 키 스키마 문서와 adapter 통일 |
| P1 | 중복 진입 | 전략별 dedup만 존재 | 동일 종목 다전략 중복 진입 | 글로벌 `stk_cd` dedup/cooldown 추가 |
| P1 | 데이터 손실 | WS writer 예외 시 재시도 없음 | 틱/VI 유실 | DLQ 또는 batch retry writer |
| P1 | Redis 운영 | `KEYS vi:*` 사용 | Redis block | `SCAN` 또는 index set |
| P1 | 테스트 환경 | Java context test DB 의존, Python test encoding/async dep 문제 | 회귀 검증 약화 | Testcontainers/pytest deps/encoding 복구 |
| P2 | 운영성 | 로그 rotation 없음, health가 PG writer 미반영 | 장애 원인 파악 지연 | health 확장, logrotate |
| P2 | 문서 | 계획 문서와 현재 코드 불일치 | 운영 혼선 | 문서 상태 라벨링 |

## 6. 검증 결과

실행한 검증:

```text
python -m py_compile ai-engine\engine.py ai-engine\queue_worker.py ai-engine\scorer.py ai-engine\strategy_runner.py websocket-listener\main.py websocket-listener\ws_client.py websocket-listener\redis_writer.py
node --check telegram-bot\src\index.js
node --check telegram-bot\src\handlers\signals.js
node --check telegram-bot\src\handlers\commands.js
node --check telegram-bot\src\utils\formatter.js
api-orchestrator\gradlew.bat test --dry-run
```

결과:

- 핵심 Python 운영 파일 문법 검증: 통과.
- Node 주요 파일 `--check`: 통과.
- Gradle dry-run: 통과.
- `python -m compileall ai-engine websocket-listener -q`: 실패. `ai-engine/tests/test_scorer.py`의 한글 문자열/인코딩 손상으로 `SyntaxError: invalid character`가 발생했다.

주의:

- 하위 API 에이전트는 실제 `./gradlew test` 실행 시 DB/Flyway 연결 실패로 context test가 실패한다고 보고했다. 내 총괄 검증은 dry-run만 수행했다.
- WebSocket 하위 에이전트는 `websocket-listener` pytest에서 `pytest-asyncio` 부재로 일부 async 테스트가 실패한다고 보고했다.

## 7. 즉시 수정 권장 작업

1. `ai-engine/tp_sl_engine.py`: `compute_rr()`의 `strategy` 미정의 참조 여부 확인 및 테스트 추가.
2. `ai-engine/engine.py`, `telegram-bot/src/handlers/confirmGate.js`: confirm gate를 실제 환경변수 기반으로 켜고 끌 수 있게 정리.
3. `api-orchestrator`와 `ai-engine`의 `ws:expected:{stkCd}` 필드 스키마 통일.
4. `websocket-listener/db_writer.py`, `redis_writer.py`: 부호 보존 파싱으로 교정.
5. `api-orchestrator/DataPersistenceScheduler`: `redis.keys("vi:*")` 제거.
6. `ai-engine/strategy_runner.py`: 전략 간 글로벌 dedup/cooldown 추가.
7. `telegram-bot/commands.js`: return 이후 dead code 제거.
8. 테스트 인프라 복구: Python 테스트 인코딩, `pytest-asyncio`, Java Testcontainers 또는 profile 분리.
9. health 확장: PG writer, queue depth, reconnect, last successful Kiwoom login, write failure counters.
10. 문서 정리: 계획/현행/폐기 문서 라벨링.

## 8. 기능 강화 로드맵

### 단기

- 운영 dashboard형 `/status` 개선.
- 글로벌 중복 진입 차단.
- Redis key schema 문서화.
- log rotation.
- 실패 큐와 재처리 명령 추가.

### 중기

- 전략별 walk-forward 백테스트 프레임워크.
- 비용 반영 기대값 기반 필터.
- 레짐/섹터 차등 게이트.
- 포지션 생명주기 단일화.
- 후보군/전략 성능 지표 자동 저장.

### 장기

- 전략 파라미터 자동 튜닝은 반드시 out-of-sample 검증을 통과한 경우에만 반영.
- 뉴스/경제 이벤트를 단순 `PAUSE`가 아니라 시장/섹터/전략별 risk multiplier로 적용.
- Telegram을 운영 UI로 유지하되, 내부 상태는 API/DB/Redis에서 재구성 가능한 event-sourced 형태로 발전.

## 9. 결론

이 프로젝트는 이미 상당히 넓은 기능을 갖춘 실전형 매매 보조 시스템이다. 강점은 전략 수, 실시간 WS, Redis 기반 decoupling, Telegram 운영면, TP/SL/overnight까지 이어지는 전체 루프가 존재한다는 점이다.

가장 큰 약점은 기능 폭에 비해 상태 정합성과 테스트 안전망이 얇다는 점이다. 특히 confirm gate 비활성, Redis key schema 불일치, 포지션 DB 구조 혼재, 중복 진입 차단 부족, WS writer 유실 가능성은 수익률보다 먼저 안정성을 해칠 수 있다.

다음 작업은 새 기능 추가보다 P0/P1 정합성 보강을 먼저 하는 것이 맞다. 그 후에 백테스트/레짐 필터/비용 반영 RR을 붙이면, 기능 강화가 실제 운용 품질 향상으로 이어질 가능성이 높다.
