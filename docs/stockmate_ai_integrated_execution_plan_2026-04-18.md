# StockMate AI 통합 실행계획서

작성일: 2026-04-18  
최종 개정: 2026-04-18 (v2.0 — 매도신호·테이블영속성·전략통폐합 반영)  
문서 오너: PO 에이전트  
참여 페르소나:
- PO 헤드
- 시니어 Python 개발자 A
- 시니어 Python 개발자 B
- 시니어 Java 개발자
- 시니어 퀀트 트레이더

참고 문서:
- `docs/stockmate_ai_p0_p1_p2_execution_plan_2026-04-18.md`
- `docs/quant-signal-quality-p0-p2-draft.md`
- `docs/ops_p0_p1_p2_execution_plan_2026-04-18.md`
- `docs/strategy-consolidation.md` (전략 통폐합 15→9 계획)
- `docs/table_persistence_completion_2026-04-16.md`

---

## 작업보고서 (2026-04-18 세션)

작성: Claude Code 세션 / 기준일: 2026-04-18

### 완료 항목

| # | 항목 | 대상 파일 | 비고 |
|---|------|----------|------|
| P0-1 | 배포 설정 검증 게이트 — ai-engine 매도신호 env 4종 | `engine.py` | INT 미파싱 시 SystemExit(1), BOOL은 경고 |
| P0-3 | 청산 파이프라인 집계 (`exit_type_mix`, `avg_hold_time_min`) | `position_monitor.py`, `status_report_worker.py` | `exit_daily:{today}` Redis hash 누적, STATUS_REPORT 출력 |
| P1-4 | `open_positions` C-4 미생성 근본원인 해소 | `db_writer.py`, `queue_worker.py`, `confirm_worker.py` | 아래 상세 참조 |
| P2-1 | `trailing_pct` 전략 타입별 차등 (저장값=기본값일 때만 재적용) | `position_monitor.py` | `_TRAILING_PCT_BY_STRATEGY` 14종, 스윙 2.5% / 단타 1.0% 등 |

### C-4 (`open_positions` 미생성) 근본원인 및 수정

**원인 3가지:**

1. **팬텀 ACTIVE 포지션**: Java `SignalService`가 신호 접수 시점에 `open_positions`에 `status=ACTIVE` 선제 INSERT → Python이 `action=CANCEL` 판정해도 해당 행이 정리되지 않아 `position_monitor`가 미체결 포지션을 감시하는 오감지 발생.

2. **TP/SL 미동기화**: Claude 조정 가격(`claude_tp1/tp2/sl`)이 `open_positions`에 기록되지 않아 모니터가 원본 pre-Claude 가격으로 trailing stop 및 TP 판정.

3. **entryPrice 미설정 시 INSERT 스킵**: Java 가드 조건에 의해 행 자체가 없는 케이스 — Python fallback INSERT는 범위 외(전략 진입가 보장 필요).

**수정 내용:**

- `db_writer.py`: `confirm_open_position()` — ENTER 확정 시 Claude 가격으로 UPDATE, `cancel_open_position_by_signal()` — CANCEL 시 `status=CLOSED, exit_type='AI_CANCEL', monitor_enabled=FALSE`
- `queue_worker.py`, `confirm_worker.py`: action 판정 직후 각 함수 호출

### 미조치·이월 항목

| 항목 | 사유 |
|------|------|
| P1-9 전략 통폐합 1단계 (S1+S7) | S7 작업 타팀 이관 — 이관 사항: `_build_s7()` 호출을 `_build_intraday()`로 이동, `TradingScheduler.preloadAuctionCandidates()`에서 `getS7Candidates()` 제거 |
| P1-10 전략 통폐합 2단계 (S8+S9+S15) | 계획서 선행조건(timeout 원인 분해) 미완료로 P1/P2 경계 이월 |
| P0-2 운영 API·Telegram 명령 표준화 | 범위 외 (api-orchestrator·telegram-bot 담당) |
| P0-4 KST 강제 전수 검증 | 범위 외 |
| P1-1 후보풀 안정화 계측 | 운영 데이터 축적 후 착수 |
| P2-2~8 전 항목 | P1 DoD 충족 후 착수 |

### P1 DoD 달성 여부

- [x] `open_positions` C-4 해소 — 포지션 레코드 안정적 생성
- [ ] 전략 통폐합 1단계(S1+S7) — S7 타팀 이관
- [ ] 전략 통폐합 2단계(S8+S9+S15) — 이월
- [ ] timeout 원인 분해 — 미착수

---

## 문서 목적과 범위

이 문서는 기능 로드맵이 아니라 `운영 가능한 신호 서비스`로 수렴시키기 위한 통합 실행계획서다.  
기존 메인 계획서의 `P0/P1/P2`, 퀀트 초안의 `신호 품질·전략 계측`, 운영 계획서의 `배포·헬스체크·KST 운영 규율`, 그리고 v2.0에서 추가된 `매도신호 시스템`, `테이블 영속성`, `전략 통폐합` 항목을 한 문서로 합쳤다.

포함 범위:
- 운영 안정성
- 신호 재현성
- 매도/청산 신호 품질
- 실전 품질 고도화
- 서비스별 책임과 인터페이스
- 배포 및 운영 검증 절차

제외 범위:
- 신규 전략 대량 추가
- 대규모 UI/UX 개편
- 브로커 교체나 인프라 전면 재설계

## 핵심 의사결정 원칙

- 모든 시간 정책은 `Asia/Seoul` 절대 기준으로 쓴다.
- 모든 종목코드는 canonical code 하나만 허용한다.
- 설정 누락이나 시간대 불일치는 `fail-fast`로 차단한다.
- 운영 메시지와 사용자 메시지는 분리한다.
- 자유형 로그보다 구조화된 계측을 우선한다.
- 운영을 깨뜨릴 수 있는 항목은 신기능보다 먼저 처리한다.
- 측정할 수 없는 개선은 계획에 넣지 않는다.
- `돌아간다`가 아니라 `재현 가능하고 운영 가능하다`를 완료 기준으로 삼는다.
- P1/P2 항목은 P0 계측이 먼저 있어야 착수한다.

## 현재 상태 베이스라인 (v2.0 기준)

현재 평가는 다음과 같다.
- 기능 완성도: 약 87~90 (매도신호·영속성 포함)
- 운영 완성도: 약 70

### v1.0 이후 신규 완료 (2026-04-14~16)

**매도 신호 시스템 (2026-04-14)**
- V17 마이그레이션: `open_positions`에 `peak_price`, `trailing_pct`(기본 1.5%), `monitor_enabled` 컬럼
- `position_monitor.py`: 30초 폴링, SL_HIT > TP2_HIT > TP1_HIT > TRAILING_STOP > TREND_REVERSAL 우선순위
- `downtrend_detector.py`: reversal_score 5개 컴포넌트, ≥ 3 → Claude 2차 판단
- `analyzer.py`: `analyze_exit()` 추가 (`_EXIT_SYS_PROMPT` 분리)
- `telegram-bot`: `formatSellSignal()`, SELL_SIGNAL 핸들러
- 신규 env: `ENABLE_POSITION_MONITOR`, `POSITION_MONITOR_INTERVAL_SEC`, `REVERSAL_CLAUDE_ENABLED`, `REVERSAL_CLAUDE_COOLDOWN_SEC`

**테이블 영속성 완성 (2026-04-16)**
- `websocket-listener`가 Redis 저장과 동시에 PostgreSQL `ws_tick_data`, `vi_events` 직접 기록
- `ws:db_writer:event_mode` Redis 플래그로 Java 분당 snapshot과 충돌 방지
- `MarketDailyContext`: KOSPI/KOSDAQ breadth, 외인/기관 수급, VIX, 일중 성과 확장
- `DailyPnl`, `StrategyDailyStat`: 시장 컨텍스트 + 임계값 스냅샷 + 추가 성과 지표
- `OvernightEvaluation`: RSI, 정배열, bid ratio, score components + 익일 시가 검증 스케줄러
- `StrategyParamHistory`: 부팅 1회 기록 → 정기 스냅샷으로 변경

**전략 통폐합 계획 수립 (2026-04-16, 미구현)**
- 15개 → 9개 (40% 감소) 3단계 계획 문서화
- 신호명(S7_AUCTION, S9_PULLBACK_SWING 등) 유지 → scorer.py 무변경 보장

### 기반 요소 (v1.0 기준)

- Java/Python/Node 전반의 `KST` 고정 설정 보강
- WebSocket 운영시간 `월-금 07:30~20:10 KST` 정책
- `STATUS_REPORT` 슬롯 정책 정리
- `_AL` 접미사 제거와 canonical stock code 정규화
- Telegram 필수 env 검증과 API base URL 강제
- 전략별 timeout override와 일부 회귀 테스트 정리
- `SWING_STRATEGIES` 환경변수 단일 소스화 (Java+Python 동기화)

### 남은 공백

- 서비스 공통의 배포 설정 검증 게이트 부재 (매도신호 env 4종 미포함)
- 매도 파이프라인(`open → monitor → exit`) 집계 미구현
- `open_positions` 미생성 근본 원인(C-4) 미해소
- `ws:db_writer:event_mode` 플래그 운영 정책 문서화 미완료
- `trailing_pct` 전략 타입별 차등 미적용 (스윙 전략 조기 청산 리스크)
- 일일 파이프라인 집계와 전략별 품질 기준선 부재
- 운영용 API/Telegram 명령 응답 모델 표준화 미완료

## 통합 우선순위 맵

우선순위는 아래 순서로 고정한다.

1. `P0 운영 안정성`
2. `P1 신호 재현성 + 전략 통폐합 1-2단계`
3. `P2 실전 품질 고도화 + 전략 통폐합 3단계`

단계 전환 조건:
- P0 → P1: 설정 검증, KST, 헬스체크, 일일 파이프라인 계측(진입 + 청산 양방향)이 운영에서 안정적으로 수집되어야 한다.
- P1 → P2: 후보풀 fallback, timeout, WS heartbeat, score-to-publish 편차가 전략별로 설명 가능해야 하고, C-4가 해소되어야 한다.

## 역할별 오너십

### PO 헤드
- 우선순위 승인
- DoD 승인
- P 단계 전환 승인
- 운영 기준선과 사용자 체감 기준 최종 결정

### 시니어 Python 개발자 A
- `ai-engine` 전략 런타임
- 후보풀 안정화
- timeout 계측 및 분해
- 규칙 기반 점수와 발송 변환 정책
- 전략 통폐합 2-3단계 (S8+S9+S15, S3+S5+S11)

### 시니어 Python 개발자 B
- `websocket-listener`
- Redis 실시간 데이터 정책
- 일일 헬스체크와 운영 계측
- `telegram-bot` 연동 정책과 운영 메시지 관점 지원
- `position_monitor`, `downtrend_detector` 운영 안정성
- 전략 통폐합 1단계 (S1+S7)

### 시니어 Java 개발자
- `api-orchestrator`
- KST 스케줄 고정
- Flyway/DB 스키마 거버넌스
- 설정 검증 fail-fast
- 운영 API와 감사 로그 정책
- `ws:db_writer:event_mode` 플래그 관리

### 시니어 퀀트 트레이더
- trailing_pct 전략 타입별 차등 설계
- 유동성 필터 격상 기준 결정
- MFE/MAE 평가 기준 설계
- 사후평가 전략 유지/중단 판단 기준 수립

## 서비스별 책임 분담

### api-orchestrator
- 운영 제어면 역할
- KST 스케줄 기준 강제
- DB 스키마와 마이그레이션 단일 진실원 관리
- 운영 헬스 API와 Telegram 운영 질의의 기준 응답 제공
- `ws:db_writer:event_mode` 플래그 상태 모니터링

### ai-engine
- 후보 생성, 규칙 평가, AI 평가, 최종 발행의 핵심 파이프라인
- 포지션 모니터링 (position_monitor, downtrend_detector, analyze_exit)
- 전략별 timeout, fallback, publish conversion, exit conversion 계측
- status report와 일일 집계 산출 (진입 + 청산 양방향)

### websocket-listener
- 장전/정규장/NXT 실시간 수집
- `07:30~20:10 KST` 연결 정책 준수
- heartbeat, reconnect, subscribed scope 관리
- canonical stock code로 Redis/PostgreSQL 적재
- `ws:db_writer:event_mode` 플래그 기준 Java snapshot과 충돌 방지

### telegram-bot
- 사용자용 신호(매수 + 매도)와 운영용 응답 채널 분리
- `/status`, `/signals`, `/today`, `/health` 운영 명령 제공
- 필수 env 검증과 운영 응답 표준 출력
- SELL_SIGNAL 청산 유형별 포맷 제공

---

## P0 실행계획

### 목표

- 배포 직후 죽는 설정 오류를 제거한다.
- 운영자가 Telegram만으로 핵심 상태를 확인할 수 있게 만든다.
- 신호 파이프라인을 매일 수치로 추적 가능한 상태로 만든다. 진입 파이프라인(`candidate → rule → AI → publish`)과 청산 파이프라인(`open → monitor → exit`) 양방향을 포함한다.

### 핵심 작업

**1. 배포 설정 검증 게이트 도입**

대상: `api-orchestrator`, `ai-engine`, `websocket-listener`, `telegram-bot`

기존 검증 항목:
- `Asia/Seoul` 시간대 설정
- Redis/Postgres 필수 연결값
- Telegram bot token 및 allowed chat IDs
- `API_ORCHESTRATOR_BASE_URL`
- Kiwoom 자격증명
- WebSocket 운영시간 정책 값

v2.0 추가 검증 항목 (ai-engine):
- `ENABLE_POSITION_MONITOR` (기본 true, 값 존재 여부 확인)
- `REVERSAL_CLAUDE_ENABLED` (기본 true)
- `POSITION_MONITOR_INTERVAL_SEC` (기본 30, 정수 여부 확인)
- `REVERSAL_CLAUDE_COOLDOWN_SEC` (기본 120, 정수 여부 확인)

**2. 운영 API 및 Telegram 명령 표준화**

현재 명령 표면인 `/status`, `/signals`, `/report`, `/errors`를 우선 표준화.  
health 응답은 단순 200 OK가 아니라 아래를 포함해야 한다.
- Redis 상태
- Postgres 상태
- 최근 WS heartbeat
- queue backlog (`telegram_queue`, `ai_scored_queue`)
- 최근 scheduler 실행 결과
- `ws:db_writer:event_mode` 플래그 상태 (event_mode ON/OFF)
- 현재 활성 포지션 수 (`position_count`)

**3. 일일 신호 파이프라인 집계 도입**

진입 파이프라인 (전략별):
- `candidate_count`
- `rule_pass_count`
- `ai_pass_count`
- `publish_count`
- `timeout_count`
- `cancel_reason_mix`

청산 파이프라인 (전략별, v2.0 신규):
- `exit_today_count`
- `exit_type_mix` (SL_HIT/TP1_HIT/TP2_HIT/TRAILING_STOP/TREND_REVERSAL 비중)
- `reversal_claude_call_count` (Claude 호출 건수)
- `trailing_active_count` (현재 trailing_stop 활성 포지션 수)
- `avg_hold_time_min` (청산 건 평균 보유시간)

이 수치들은 `StrategyDailyStat` 테이블에 자동 적재된다.

**4. KST 운영 강제**

- Java `@Scheduled`, Python 배치, WebSocket 시간창, cleanup 시각을 모두 `Asia/Seoul` 기준으로 명시
- 월요일 장전 구간 누락이 재발하지 않도록 테스트와 로그 기준 정리

**5. STATUS_REPORT 단일 원본화**

Python이 운영 브리핑 JSON의 단일 원본을 생성하고 Node는 포맷과 전달만 담당.  
최소 공통 필드 (v2.0 확장):
- `warmup_status`
- `ws_heartbeat_age_sec`
- `queue_backlog`
- `daily_pipeline_summary_key`
- 최근 10분 신호/판정 요약
- `position_count` (활성 포지션 수)
- `exit_today_count` (당일 청산 건수)
- `trailing_active_count` (trailing_stop 추적 중인 포지션 수)

**6. `ws:db_writer:event_mode` 충돌 방지 정책**

- `ws:db_writer:event_mode` 플래그가 ON일 때 Java 분당 snapshot 스케줄러가 자동 비활성화되는 로직을 헬스체크 항목에 포함한다.
- 플래그가 예기치 않게 OFF 상태일 때 api-orchestrator가 이중 적재를 시작하므로, 플래그 상태를 STATUS_REPORT와 `/health`에서 명시적으로 노출한다.

**7. 시크릿 및 로그 안전성 고정**

- 민감정보 로그 0건 원칙
- 운영 감사 이벤트 명명 규칙 확정

### 서비스별 작업

#### Python A
- 전략 실행 시작/완료/timeout 구조화 로그
- 일일 전략 집계 산출기 (진입 + 청산 양방향)
- 후보 생성수와 publish 수 연결 계측

#### Python B
- WS heartbeat age, reconnect count, subscription scope 계측
- `STATUS_REPORT` JSON shape 고정 (position 필드 3종 포함)
- Telegram 운영 명령과 ai-engine 요약값 연결 점검
- `position_monitor` 30초 폴링 상태를 STATUS_REPORT에 반영
- `ws:db_writer:event_mode` 플래그 상태 모니터링 로직

#### Java
- `spring.task.scheduling.time-zone`와 스케줄 정책 재점검
- `@ConfigurationProperties + @Validated` 기반 필수 설정 검증
- health 응답 모델 통합 (포지션 수, 플래그 상태 포함)

### 완료 기준 (DoD)

- 잘못된 env로는 서비스가 정상 기동하지 않는다 (매도신호 env 4종 포함).
- 운영자는 Telegram 명령만으로 5초 안에 핵심 상태를 확인할 수 있다.
- 하루 단위 집계에서 전략별 `candidate → rule → AI → publish` 숫자가 비지 않는다.
- 하루 단위 집계에서 `exit_type_mix`가 비지 않는다.
- `STATUS_REPORT`가 슬롯마다 같은 JSON shape로 발행된다 (position 필드 3종 포함).
- KST 기준 월요일 장전 스케줄이 재현 가능하게 검증된다.
- 민감정보 검색 시 운영 로그에서 0건이어야 한다.
- `/health`에서 `ws:db_writer:event_mode` 상태가 명시적으로 노출된다.

### 미조치 리스크

- 설정 누락으로 서비스 일부만 뜨는 착시가 반복된다.
- 신호 감소 원인을 로그 수색으로만 추적하게 된다.
- 장전/월요일 누락 이슈가 환경에 따라 재발한다.
- `ws:db_writer:event_mode` 미검증 시 Java snapshot과 ws-listener 이중 적재로 Postgres 헬스체크 false positive 발생.
- 매도 파이프라인 계측 없이 청산 품질을 판단하지 못한다.

---

## P1 실행계획

### 목표

- 장전과 장초 신호를 재현 가능한 상태로 만든다.
- 전략별 timeout과 fallback을 설명 가능한 수준으로 분해한다.
- WebSocket, 후보풀, 전략 시간창을 동일 정책으로 정렬한다.
- 전략 구조 복잡도를 낮추어 품질 계측을 단순화한다 (통폐합 1-2단계).
- `open_positions` C-4 미생성 근본 원인을 해소한다.

### 핵심 작업

**1. 후보풀 안정화**
- 후보 생성 시점: `07:50~08:20 KST`
- 기준 스냅샷: `08:25 KST`
- fallback scan 사용률을 전략별로 계측

**2. 전략 시간창 재정렬**
- 장전형: `S1` (시초가, 08:30~09:10)
- 장초/장중형: `S3`, `S6`, `S11`
- 종가형: `S12` (14:30~15:10)
- 전략 생성 대기: `S7` (동시호가, 08:30~09:00) ← S1에 통폐합 후 해소
- 상태 리포트와 실제 평가 윈도우를 같은 기준으로 맞춤

**3. timeout 원인 분해**
- 분류:
  - 데이터 대기
  - 외부 API 지연
  - 연산 병목
  - 큐 적체
- 전략별 timeout override 사용 여부와 실제 런타임 p50/p95 추적
- **이 작업은 통폐합 착수 전 완료되어야 한다.** 통폐합 후 단일 함수가 여러 API를 순차 호출하면 하위 API별 지연 특정이 어려워진다.

**4. `open_positions` C-4 미생성 원인 해소**
- 운영 로그에서 error 레벨로 스택트레이스 수집 (P0 헬스체크와 연동)
- 근본 원인 확인 후 `OpenPosition` 생성 경로 수정
- 해소 완료가 P2 사후평가의 선행조건이므로 P1 내 조기 착수 권고

**5. WebSocket 세션 정책 고정**
- 기본 정책: `월-금 07:30~20:10 KST`
- `BYPASS_MARKET_HOURS`는 예외 플래그로만 유지
- heartbeat stale, reconnect burst, subscribed scope drift 감시
- `ws:db_writer:event_mode` 플래그 상태가 세션 정책과 일관되게 유지되는지 검증

**6. canonical stock code 정책 완결**
- Redis, PostgreSQL, Telegram, 리포트, 집계에서 canonical code만 사용
- `_AL`, `_NX` 같은 접미사 재유입 차단

**7. 유동성 필터 P1 격상 (조건부)**

다음 조건 중 하나라도 해당하면 P2가 아닌 P1에서 처리한다.
- 일평균거래량 5만주 미만 종목에서 신호 발행 이력이 확인되는 경우
- S1/S2/S4처럼 단타 전략에서 호가 스프레드 0.5% 이상인 종목 신호 이력이 있는 경우

격상 시 최소 구현: R:R 계산 이전에 5일 평균거래량 필터 + 호가 스프레드 실시간 체크 적용. 현행 SLIP_FEE 고정값(KOSDAQ 0.45%)은 저유동성 종목에서 실질 슬리피지(0.9~1.5%) 대비 과소 반영된다.

**8. 상태 브리핑 정책 고정**
- 기본 슬롯: `08:30`, `12:00`, `15:40 KST`
- 운영 브리핑은 운영 채널용 의미만 갖고, 사용자 신호와 섞이지 않도록 함
- warm-up, WS freshness, queue backlog, daily pipeline 요약, 포지션 상태가 같은 필드 체계로 유지

**9. 전략 통폐합 1단계 (S1+S7 병합)**

P1 후반부에 배치. timeout 원인 분해 완료 후 착수.

대상 파일:
- `ai-engine/strategy_1_gap_opening.py`: `_clean_num`, `fetch_gap_rank`, `fetch_credit_filter`, `scan_auction_signal` 함수 4개 흡수
- `ai-engine/strategy_7_auction.py`: **삭제**
- `ai-engine/strategy_runner.py`: S7 import 경로 변경 (1줄)

신호명 `S7_AUCTION` 유지 → `scorer.py`, `overnight_scorer.py`, `candidates_builder.py` 무변경.  
완료 기준: 동일 날짜 기준 S7 신호 재현 테스트 통과.

**10. 전략 통폐합 2단계 (S8+S9+S15 병합)**

1단계 완료 후 착수. P1 후반부 병행 또는 P1/P2 경계에서 처리.

대상 파일:
- `ai-engine/strategy_8_golden_cross.py`: `_calc_ma_rsi_macd()`, `_calc_bollinger()` 공통 헬퍼 추출, `scan_pullback_swing()`, `scan_momentum_align()` 흡수
- `ai-engine/strategy_9_pullback.py`: **삭제**
- `ai-engine/strategy_15_momentum_align.py`: **삭제**
- `ai-engine/strategy_runner.py`: S9/S15 import 경로 변경 (2줄)
- `ai-engine/candidates_builder.py`: `_build_s9()`, `_build_s15()` 통합 검토. 단, 풀을 합칠 경우 S9(`flu_rt 0.3~5.0`)와 S15(`flu_rt 0.5~8.0`) 필터가 섞이므로 풀 키는 `candidates:s8:{market}` 하나로 통합하되 전략 함수 내 필터링은 분리 유지한다.

주의: S9(`09:30~13:00`)와 S15(`10:00~14:30`)의 시간창이 다르므로 스케줄 병합 로직 검토 필수.  
완료 기준: 동일 날짜 기준 S9/S15 신호 재현 테스트 통과.

### 서비스별 작업

#### Python A
- 후보풀 스냅샷 기준 시각과 fallback 사용률 계측
- 전략별 runtime/timeout/cancel 구조화
- high-score low-publish 전략 재보정 초안 작성
- 전략 통폐합 2단계 실행 (S8+S9+S15)

#### Python B
- WS 운영시간과 market phase 정책 문서/테스트 일치화
- canonical code 경계 점검
- Redis 실시간 키와 운영 대시보드 지표 연결
- dedup/TTL/캐시 정책 표준표 초안 작성
- `open_positions` C-4 로그 수집 및 해소
- 전략 통폐합 1단계 실행 (S1+S7)

#### Java
- candidate pool history, 신호 이력, 운영 집계의 DB 측 기준 정리
- Flyway 검증 강화와 canonical code 정책의 DB 보강 검토
- 운영 API에서 후보풀/스케줄/데이터품질 요약 제공
- Python 일일 집계와 Java API 날짜 기준 불일치 방지
- `ws:db_writer:event_mode` 플래그 상태 검증 로직

### 완료 기준 (DoD)

- 장전 구간 fallback scan 비율이 의미 있게 낮아진다.
- timeout 로그에서 전략명, 경과시간, 원인 범주를 즉시 확인할 수 있다.
- `_AL` 계열 키/값이 신규 경로에서 더 이상 생성되지 않는다.
- WS 정책이 코드, 설정, 문서, 테스트에서 동일하게 표현된다.
- 전략별 `publish_conversion`과 `high_score_cancel_rate`가 측정된다.
- `open_positions` C-4가 해소되어 포지션 레코드가 안정적으로 생성된다.
- 전략 통폐합 1단계(S1+S7)가 완료되고 신호 재현 테스트를 통과한다.
- 전략 통폐합 2단계(S8+S9+S15)가 완료되거나 P2로 이월되는 근거가 명시된다.

### 미조치 리스크

- 장전 신호의 재현성이 계속 흔들린다.
- timeout 원인을 특정하지 못해 단순 timeout 증가만 반복된다.
- 데이터 오염과 캐시 중복으로 전략 품질 해석이 왜곡된다.
- C-4 미해소 시 P2 사후평가의 MFE/MAE 계산 기준 자체가 없어진다.
- 통폐합 없이 15개 전략 기준으로 P1 계측을 완료하면, 9개로 줄었을 때 계측 구조를 재작성해야 한다.

---

## P2 실행계획

### 목표

- 사용자 체감 품질과 사후 평가 체계를 붙인다.
- 중복 알림과 체결 불가능 신호를 줄인다.
- 매도 시스템 파라미터를 운영 데이터 기반으로 재보정한다.
- 주간 운영 회고를 데이터 기반으로 고정한다.

### 선행 조건

P2 착수 전 아래 조건이 모두 충족되어야 한다.
- C-4 해소: `open_positions` 레코드가 안정적으로 생성되어야 한다.
- `StrategyDailyStat` + `DailyPnl` 최소 2주 운영 데이터 축적.
- P2-H(S3 cur_prc가 ka10063 실제 현재가인지) 운영 로그 검증 완료.
- P2-I(S5 net_buy_amt 단위 원/만원 확인) 운영 로그 검증 후 scorer.py 스케일 튜닝.

### 핵심 작업

**1. trailing_pct 전략 타입별 차등**

현행 단일값 1.5%는 스윙 전략에서 조기 청산 손실 패턴을 유발한다. 전략 그룹별 기본값을 분리한다.

| 전략 타입 | 전략 | trailing_pct 기본값 |
|---------|------|-------------------|
| 스윙 (3~7일) | S8, S9, S15, S3, S5, S11 | 2.5~3.0% |
| 단타 (당일~익일) | S1, S2, S4, S7 | 1.0~1.5% |
| 이벤트/돌파 | S6, S10, S13 | 2.0% |
| 종가/반등 | S12, S14 | 1.5% |

`open_positions.trailing_pct` 컬럼이 이미 존재하므로 진입 시 전략별 기본값을 설정하는 로직만 추가한다.

진단 기준: SL_HIT 청산 건 중 MFE(최고 수익점)가 +1.5% 이상이었던 비율이 30%를 초과하면 trailing_pct가 과도하게 타이트하다는 정량 신호다.

**2. TREND_REVERSAL 쿨다운 및 긴급 경로 보강**

현행 120초 쿨다운은 2개 폴링 사이클(60초) 동안 맹목 상태를 만든다. 두 가지 조정 중 하나를 선택한다.
- 옵션 A: `REVERSAL_CLAUDE_COOLDOWN_SEC` 기본값 120 → 60으로 단축
- 옵션 B: `realized_pnl_pct < -1.5%` 조건 시 쿨다운 무시하는 긴급 청산 경로 추가

옵션 B가 Claude 호출 비용과 빠른 손절 필요성 간 균형이 더 좋다. 단, `_EXIT_SYS_PROMPT` 비용 검토 후 결정한다.

**3. 유동성 필터 고도화 (P2 잔류 기준)**

P1 격상 조건에 해당하지 않는 경우 P2에서 처리한다.
- 예상 체결량
- 호가 스프레드 (실시간)
- 장전 동시호가 참여도
- 초보자 기준 체결 가능성 지표화

**4. 중복 알림 정책 정리**

매수/매도 신호 양쪽에 적용.
- 동일 종목/동일 전략
- 동일 종목/상이 전략
- 재기동 후 재발송
- SELL_SIGNAL 중복 발송 (동일 포지션 청산 이벤트 중복)
- 허용/차단 규칙 문서화 및 코드 반영
- Node는 dedup의 소유자가 아니라 소비자 역할을 유지하고, dedup 원천은 Python 정책으로 고정

**5. 사후평가 표준화**

진입 후 평가:
- `5분`, `15분`, `종가` 기준 `MFE/MAE`
- `post_publish_win_rate`
- `rr_hit_rate`

v2.0 추가 기준:
- **TP1 도달 시간(분)**: 신호 발행 후 TP1까지 걸린 시간. 단타 전략(S1/S2/S4/S7)에서 30분 초과 시 전략 파라미터 재검토 트리거로 사용.
- **SL_HIT 이전 MFE**: SL_HIT 청산 건 중 MFE가 +1.5% 이상이었던 비율 (trailing_pct 적정성 진단 지표).
- **오버나잇 익일 시가 검증**: `OvernightEvaluation` 익일 시가 검증 결과를 사후평가와 분리된 별도 기준으로 추적. 당일 종가 기준 평가와 혼용하지 않도록 평가 기준 시점(`entry_date` vs. `next_open_date`)을 스키마 수준에서 분리.

**6. 전략 통폐합 3단계 (S3+S5+S11 병합)**

P1 완료 후 별도 스프린트. 3단계는 API 소스가 달라(S5: ka90003, S11: ka10035) 가장 위험도가 높다.

- S3(`ka10063`), S5(`ka90003`), S11(`ka10035`) — API 호출 로직 분리 유지, 함수만 `strategy_3_inst_foreign.py`에 통합
- `_API_INTERVAL` 0.25s rate limit 충돌 검토 필수
- `strategy_5_program_buy.py`, `strategy_11_frgn_cont.py` 삭제
- `strategy_runner.py` S5/S11 import 경로 변경 (2줄)
- `candidates:s11:{market}` TTL 1800s 정책 유지

완료 기준: 동일 날짜 기준 S3/S5/S11 신호 재현 테스트 통과.

**7. 주간 회고 루프와 변경관리**

- timeout 상위 전략
- warm-up 실패
- WS reconnect burst
- score-to-publish 편차
- exit_type_mix 이상 (TRAILING_STOP 비율 급등 시 trailing_pct 재검토)
- `StrategyDailyStat` 임계값 스냅샷과 주간 회고 기준표 연결
- 환경변수/시간정책 변경 영향 검토

**8. 운영 자동화**
- 배포 전 체크리스트 자동 실행
- 배포 직후 5분 검증 자동화
- 장애 유형별 대응 runbook 정리

### 서비스별 작업

#### Python A
- 전략별 품질 지표 산출
- 유동성 필터 반영 전후 비교 실험
- score-to-publish calibration 개선
- trailing_pct 전략 타입별 차등 구현
- 전략 통폐합 3단계 실행 (S3+S5+S11)

#### Python B
- 중복 알림 차단 정책과 캐시/TTL 연동
- SELL_SIGNAL 중복 발송 dedup 정책
- 운영 대시보드용 실시간 품질 지표 정리
- `signals.js` 처리 경로 기준 통합 mock 테스트 확장
- TREND_REVERSAL 긴급 경로 보강 (옵션 B 선택 시)

#### Java
- 사후평가 저장 스키마와 주간 집계 API
- 배포/장애 감사 이벤트와 변경 이력 조회 지원
- `OvernightEvaluation` 기준 시점 스키마 분리 (`entry_date` vs. `next_open_date`)

### 완료 기준 (DoD)

- 중복 알림률과 체결 곤란 신호 비율이 감소 추세를 보인다.
- 전략별 사후평가 리포트가 주간 단위로 자동 생성된다.
- 주간 회고에서 운영 이슈와 전략 품질 이슈를 같은 기준표로 비교할 수 있다.
- 배포 후 검증과 장애 대응이 runbook으로 재현 가능해진다.
- trailing_pct 전략 타입별 기본값이 적용되고, SL_HIT 이전 MFE 진단 지표가 수집된다.
- 전략 통폐합 3단계(S3+S5+S11)가 완료된다.

### 미조치 리스크

- 실전 체감이 낮은 신호가 계속 발송된다.
- 좋은 백테스트와 실제 체결 가능성 사이의 간극이 남는다.
- 단일 trailing_pct 1.5%로 스윙 포지션이 조기 청산되어 기대 R:R을 달성하지 못한다.
- 운영 지식이 사람 기억에만 의존하게 된다.
- `OvernightEvaluation` 당일/익일 기준 혼용으로 사후평가 통계가 오염된다.

---

## 측정 지표

### 진입 파이프라인
- `candidate_count`
- `rule_pass_rate`
- `ai_pass_rate`
- `publish_rate`
- `timeout_rate`
- `fallback_scan_rate`
- `cancel_reason_mix`

### 운영 인프라
- `ws_heartbeat_age`
- `ws_reconnect_count`
- `warmup_status`
- `queue_backlog`
- `ws_db_writer_event_mode` (ON/OFF)

### 청산 파이프라인 (v2.0 신규)
- `exit_type_mix` (SL/TP1/TP2/TRAILING/REVERSAL 비중)
- `exit_today_count`
- `trailing_active_count`
- `reversal_claude_call_count`
- `avg_hold_time_min`

### 신호 품질
- `duplicate_alert_rate`
- `high_score_cancel_rate`
- `post_publish_win_rate`
- `5m_mfe`, `15m_mfe`, `close_return`
- `tp1_reach_time_min` (v2.0 신규)
- `sl_hit_prior_mfe_rate` (v2.0 신규, trailing_pct 진단)
- `rr_hit_rate`

---

## 리스크와 선행조건

### 선행조건
- Redis/Postgres 운영 연결 안정화
- Telegram 운영 명령 사용 채널 합의
- Kiwoom 외부 API 지연 특성 로그 확보
- Flyway 기준 스키마 운영 합의
- `open_positions` C-4 해소 (P2 사후평가 선행조건)
- P2-H(S3 cur_prc), P2-I(S5 net_buy_amt) 운영 로그 검증

### 주요 리스크
- 외부 API 지연이 timeout과 혼합되어 해석될 수 있음
- 장전 데이터 품질 부족으로 후보풀 안정화가 늦어질 수 있음
- 기존 Redis 오염 키가 운영 지표를 왜곡할 수 있음
- 테스트가 정책 변경을 따라오지 않으면 운영 신뢰도가 다시 하락함
- Python 집계 기준 날짜와 Java API 기준 날짜가 다르면 운영 숫자 해석이 흔들릴 수 있음
- `ws:db_writer:event_mode` 미검증 시 Java snapshot과 ws-listener 이중 적재로 Postgres 헬스체크 false positive 발생
- trailing_pct 단일값 1.5%: 스윙 전략에서 조기 청산 손실 패턴 (P2 전까지는 운영 로그 모니터링으로 관리)
- 전략 통폐합 3단계(S3+S5+S11): ka90003 rate limit 충돌 및 candidates:s11 TTL 정책 충돌 가능성

---

## 배포 및 운영 검증 절차

### 배포 전
- 필수 env 검증 (매도신호 env 4종 포함)
- KST 설정 검증
- DB 마이그레이션 검증
- WS 운영시간 설정 검증
- `ws:db_writer:event_mode` 플래그 초기 상태 확인
- Telegram 운영 명령 응답 smoke test

### 배포 직후 5분
- `/health` 확인 (포지션 수, 플래그 상태 포함)
- `/status` 확인
- WS heartbeat 확인
- queue backlog 확인 (`telegram_queue`, `ai_scored_queue`)
- 오늘 날짜 기준 KST 로그 timestamp 확인
- `position_monitor` 폴링 로그 확인 (30초 주기)

### 장애 시
- 설정 오류면 즉시 fail-fast 후 재배포
- heartbeat stale이면 WS 세션/구독 범위 우선 점검
- publish 급감이면 `candidate → rule → AI → publish` 단계별 숫자 확인
- timeout 급증이면 전략별 runtime 및 원인 범주부터 확인
- exit 미발행이면 `position_monitor` 폴링 상태 및 `ENABLE_POSITION_MONITOR` 확인
- `ws:db_writer:event_mode` OFF 감지 시 Java snapshot 이중 적재 여부 즉시 확인

---

## 전략 통폐합 실행 로드맵 (요약)

| 단계 | 병합 | 리스크 | 배치 | 예상 작업량 |
|------|------|--------|------|-----------|
| 1단계 | S1+S7 | 낮음 | P1 후반부 | 2시간 |
| 2단계 | S8+S9+S15 | 중간 (시간창 주의) | P1 후반부~P2 경계 | 반나절 |
| 3단계 | S3+S5+S11 | 높음 (API 소스 상이) | P2 별도 스프린트 | 하루 |

통폐합 전 필수 선행: timeout 원인 분해 완료.  
각 단계 완료 기준: 동일 날짜 기준 신호 재현 테스트 통과.

---

## 최종 정리

이 문서의 목표는 기능을 더 붙이는 것이 아니라 `운영 안정성 → 신호 재현성 → 실전 품질` 순서로 시스템을 수렴시키는 것이다.

v2.0에서는 매도 신호 시스템, 테이블 영속성, 전략 통폐합이라는 세 개의 신규 구조를 흡수했다. 이 중 매도 시스템은 P0 게이트와 STATUS_REPORT 확장을 요구하고, 전략 통폐합은 P1 timeout 분해 이후에야 안전하게 착수 가능하며, 테이블 영속성은 P2 사후평가의 물리적 기반이다.

PO는 단계 전환을 관리하고, Python 2축과 Java 1축은 각 단계에서 동시에 닫혀야 할 실행 항목을 책임진다.  
퀀트 트레이더는 trailing_pct 차등, 쿨다운 조정, 유동성 필터 격상 기준 결정을 전담한다.  
즉, 서비스별 나열이 아니라 `문제영역별 통합 실행 구조`로 운영 완성도를 끌어올리는 것이 이 계획서의 기준이다.
