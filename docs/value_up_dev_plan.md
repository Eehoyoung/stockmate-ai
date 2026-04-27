# StockMate AI – 고도화 개발 계획서 (Value-Up Dev Plan)

> **기준 문서**: `docs/project-capabilities.md` (기능/한계 정의)
> **작성 기준일**: 2026-03-21
> **목표**: 신호 품질 향상, API 호출 최적화, 자동매매 기능 추가, 4개 모듈 전반 고도화

---

## 완료 현황 요약

| Phase | 제목 | 상태 | 완료율 |
|-------|------|------|--------|
| **Phase 1** | API 효율화 | **완료** | 100% |
| **Phase 2** | 자동매매 | 미착수 (범위 제외) | 0% |
| **Phase 3** | 모듈 고도화 | **완료** | 100% |
| **Phase 4** | 운영 인프라 | **완료** | 100% |

---

## 개요

| Phase | 제목 | 핵심 목표 |
|-------|------|-----------|
| **Phase 1** | API 효율화 | Ranking-API-First 패턴 도입, ka10033 교체, Claude 토큰 절감 |
| **Phase 2** | 자동매매 | kt10000/kt10001 연동, 포지션 관리, 리스크 제어 |
| **Phase 3** | 모듈 고도화 | 4개 모듈 품질/안정성/운영성 개선 |
| **Phase 4** | 운영 인프라 | 모니터링, 통계 리포트, 알림 고도화 |

---

## Phase 1 – API 효율화 및 신호 품질 개선

### 1-A. ka10033 오용 교체 (긴급)

**문제**: `CandidateService`와 S7 전술이 ka10033(신용비율상위)을 거래량 순위 API로 오용 중

**해결 방안**

| 용도 | 기존 (오용) | 교체 대상 |
|------|------------|-----------|
| 장전 갭 후보 탐색 (S1/S7) | ka10033 | **ka10029** (예상체결등락률상위) |
| 당일 고유동성 종목 (S7 보조) | ka10033 | **ka10030** (당일거래량상위) |

**작업 목록**

```
[x] api-orchestrator: Ka10029Response, Ka10029Request DTO 생성
[x] api-orchestrator: Ka10030Response, Ka10030Request DTO 생성
[x] api-orchestrator: CandidateService → ka10029 호출로 교체
    - sort_tp=1 (상승률), trde_qty_cnd=10 (만주이상), stk_cnd=1 (관리제외), pric_cnd=8 (1천원이상)
    - fluRt 3~15% 범위 필터 → S1 후보 리스트
[x] api-orchestrator: TradingScheduler.S7 → ka10029 + ka10030 교집합으로 교체
    - ka10029: 갭 2~10% 필터
    - ka10030: 거래대금 10억 이상(trde_amt >= 1000) 필터
[x] api-orchestrator: Ka10033 관련 코드 제거 또는 신용비율 전용 주석 추가
```

---

### 1-B. S4 사전 필터링 (ka10023 + ka10019)

**문제**: S4가 CandidateService 200종목 전체에 ka10080(분봉) 호출 → API 200회 낭비

**해결 방안**: Ranking API로 유망 종목 30개 사전 추출 후 ka10080 호출

```
전체 200종목
    │
    ├─ ka10023 (거래량급증) → sdnin_rt >= 50% → 급증 종목 Set
    ├─ ka10019 (가격급등락) → jmp_rt >= 3.0% (30분 내) → 급등 종목 Set
    │
    ▼
교집합 or 합집합 최대 30종목
    │
    ▼
ka10080 분봉 차트 → 장대양봉 패턴 확인 (기존 로직 유지)
```

**작업 목록**

```
[x] api-orchestrator: Ka10023Response, Ka10023Request DTO 생성
[x] api-orchestrator: Ka10019Response, Ka10019Request DTO 생성
[x] api-orchestrator: VolSurgeService 신규 생성
    - ka10023 호출: sort_tp=2 (급증률순), tm_tp=1, tm=5 (5분), trde_qty_tp=10, stk_cnd=1
    - sdnin_rt >= 50% 필터
[x] api-orchestrator: PriceSurgeService 신규 생성
    - ka10019 호출: flu_tp=1 (급등), tm_tp=1, tm=30, trde_qty_tp=00010, stk_cnd=1
    - jmp_rt >= 3.0% 필터
[x] api-orchestrator: StrategyService.S4 → VolSurgeService + PriceSurgeService 교차 후 ka10080 호출
```

---

### 1-C. S7 호가비율 사전 필터링 (ka10020)

**문제**: S7이 전 후보 종목에 개별 0D WebSocket 데이터 조회

**해결 방안**: ka10020(호가잔량상위)으로 매수비율 200% 이상 종목만 사전 추출

**작업 목록**

```
[x] api-orchestrator: Ka10020Response, Ka10020Request DTO 생성
[x] api-orchestrator: BidUpperService 신규 생성
    - 코스피(001) + 코스닥(101) 각각 호출 (000 전체 미지원)
    - sort_tp=3 (매수비율순), trde_qty_tp=0000 (장전 포함), stk_cnd=1
    - buy_rt >= 200.0% 종목 Set 반환
[x] api-orchestrator: TradingScheduler.S7 → BidUpperService 교집합 후 0D 조회 축소
```

---

### 1-D. Claude 토큰 최적화

**문제**: 점수 60점 이상 신호 전량 Claude 호출 → 고비용

**해결 방안**

```
[x] ai-engine: 전략별 Claude 호출 임계점 세분화
    - S1: score >= 70  (갭상승은 확실한 신호만)
    - S2: score >= 65  (VI는 중간 임계)
    - S3: score >= 60  (기관/외인은 방향 명확)
    - S4: score >= 75  (장대양봉은 고확신 요구)
    - S5: score >= 65
    - S6: score >= 60
    - S7: score >= 70
[x] ai-engine: Claude 프롬프트 압축 (현재 ~500 토큰 → ~200 토큰 목표)
    - 불필요한 컨텍스트 제거, 핵심 수치만 전달
[x] ai-engine: 하루 Claude 호출 횟수 상한 설정 (env: MAX_CLAUDE_CALLS_PER_DAY=100)
[x] ai-engine: 오류 신호 dead-letter-queue 구현 (기존 없음)
```

---

## Phase 2 – 자동매매 기능 추가

### 2-A. 주문 실행 API 연동 (api-orchestrator)

**사용 API**: `kt10000` 주식 매수주문, `kt10001` 주식 매도주문

**작업 목록**

```
[ ] api-orchestrator: KiwoomOrderService 신규 생성
[ ] api-orchestrator: PositionService 신규 생성
[ ] api-orchestrator: RiskManagerService 신규 생성
[ ] api-orchestrator: OrderService 신규 생성
[ ] api-orchestrator: OrderTrackingScheduler 신규 생성
[ ] api-orchestrator: StopLossService 신규 생성
```

---

### 2-B. Telegram 양방향 자동매매 인터페이스

**작업 목록**

```
[ ] telegram-bot: 신호 수신 후 [매수 승인] / [무시] 인라인 버튼 추가
[ ] telegram-bot: /position 명령어 추가
[ ] telegram-bot: /sell {stkCd} 명령어 추가
[ ] telegram-bot: /status 명령어 추가
[ ] telegram-bot: 체결 알림 메시지 포맷
```

---

## Phase 3 – 4개 모듈 고도화

### 3-A. api-orchestrator

```
[x] 0H 예상체결 전일종가 보완
    - 장전 08:00 시 ka10001로 후보 종목 전일종가 일괄 수집
    - Redis ws:expected:{stkCd} 에 pred_pre_pric 사전 저장
    - S1/S7 갭 계산 정확도 보장

[x] WebSocket 구독 종목 동적 관리
    - api-orchestrator가 후보 종목 목록을 Redis candidates:watchlist (Set)에 저장
    - websocket-listener가 이 Set을 폴링하여 구독 종목 동적 추가/제거

[x] API 오류 처리 고도화
    - 1700 Rate Limit: 지수 백오프 (1s, 2s, 4s, 최대 3회)
    - 8005 토큰 만료: 자동 재발급 후 재호출
    - KiwoomApiService retry 로직 구현 완료

[x] 일별 성과 집계 (compileDailySummary at 15:35)
    - 당일 신호 통계 집계 → Redis daily_summary:{YYYYMMDD}
    - telegram_queue 에 DAILY_REPORT 메시지 발행
```

---

### 3-B. ai-engine

```
[x] strategy_runner.py 실제 Kiwoom API 호출 구현
    - strategy_1_gap_opening.py: ka10029 호출 → 갭 3~15% 후보
    - strategy_3_inst_foreign.py: ka10131 호출 → 연속 순매수
    - strategy_5_program_buy.py: ka90003 + ka90009 호출
    - strategy_6_theme.py: ka90001 + ka90002 호출
    - strategy_7_auction.py: ka10029 호출
    - 각 전략이 신호 생성 후 telegram_queue에 직접 LPUSH

[x] 비동기 Redis 전환
    - redis.asyncio 사용 (engine.py, redis_reader.py)
    - strategy_2_vi_pullback.py, strategy_4_big_candle.py 비동기 전환

[x] 전략별 Claude 프롬프트 최적화
    - analyzer.py: S1~S7 전략별 압축 프롬프트
    - 수치 중심 압축 (200 토큰 목표)

[x] 오류 처리
    - queue_worker.py: error_queue dead-letter 큐
    - analyzer.py: Claude API 타임아웃(10s) 시 규칙점수 폴백
```

---

### 3-C. websocket-listener

```
[x] candidates:watchlist Redis Set 폴링으로 동적 구독
    - 30초마다 candidates:watchlist 조회
    - 신규 종목 → GRP5(0B), GRP6(0D), GRP7(0H) REG 전송
    - 제거 종목 → UNREG 전송

[x] 0H 예상체결 전일종가 저장
    - write_expected() 에서 pred_pre_pric 역산 저장
    - exp_cntr_pric / (1 + exp_flu_rt/100) 계산

[x] 연결 상태 Redis 저장
    - ws:heartbeat (Hash, TTL 30s): grp5~8 상태 heartbeat
    - 10초마다 갱신

[x] KIWOOM_MODE 환경변수로 실전/모의 WS URL 분기
```

---

### 3-D. telegram-bot

```
[x] /report 명령어 추가
    - daily_summary:{today} 에서 읽어서 표시

[x] 신호 메시지 포맷 개선
    - 진입가, 목표가(+8%), 손절가(-3%), 리스크/리워드 표시

[x] 수신 필터 설정 명령어
    - /filter s1 s4 → S1, S4 전략 신호만 수신
    - Redis user_filter:{chatId} 에 저장
    - signals.js에서 발송 전 필터 확인
```

---

## Phase 4 – 운영 인프라

```
[x] 헬스체크 엔드포인트
    - api-orchestrator: GET /actuator/health (Spring Boot Actuator 활성화)
    - ai-engine: GET /health (aiohttp 서버, 포트 8082)
    - websocket-listener: GET /health (aiohttp 서버, 포트 8081) + Redis ws:heartbeat

[x] 일별 성과 집계 스케줄러
    - 장 마감(15:35) 후 오늘 신호 집계 → Redis daily_summary:{YYYYMMDD}
    - Telegram으로 일일 리포트 자동 발송 (DAILY_REPORT 타입)

[x] 로그 표준화
    - scorer.py + analyzer.py: 구조화 JSON 로그 (ts, module, strategy, stk_cd, score)
    - ai-engine: logging.basicConfig + FileHandler

[x] 실전/모의 환경 분기
    - env: KIWOOM_MODE=real|mock
    - api-orchestrator WebClientConfig: BASE_URL 분기 (real→api.kiwoom.com, mock→mockapi.kiwoom.com)
    - websocket-listener ws_client.py: WS_URL 분기
```

---

## 신규 API 연동 요약

| API ID | 용도 | 연동 위치 | Sprint | 상태 |
|--------|------|-----------|--------|------|
| ka10029 | 예상체결등락률상위 → S1/S7 후보 | api-orchestrator CandidateService | 1 | **완료** |
| ka10030 | 당일거래량상위 → S7 유동성 필터 | api-orchestrator TradingScheduler | 1 | **완료** |
| ka10023 | 거래량급증 → S4 사전필터 | api-orchestrator VolSurgeService | 1 | **완료** |
| ka10019 | 가격급등락 → S4 사전필터 | api-orchestrator PriceSurgeService | 1 | **완료** |
| ka10020 | 호가잔량상위 → S7 매수비율 필터 | api-orchestrator BidUpperService | 1 | **완료** |
| kt10000 | 주식 매수주문 | api-orchestrator KiwoomOrderService | 2 | 미착수 |
| kt10001 | 주식 매도주문 | api-orchestrator KiwoomOrderService | 2 | 미착수 |

---

## 기대 효과

| 항목 | 현재 | 고도화 후 |
|------|------|-----------|
| S4 API 호출 수 | 200회/스캔 (ka10080 전체) | ~30회 (사전필터 후) |
| S7 후보 품질 | 신용비율 기준 (오용) | 갭상승 + 거래량 + 호가비율 기준 |
| Claude 호출 | 60점 이상 전량 | 전략별 임계치 + 일일 상한 |
| 주문 실행 | 불가 | 텔레그램 승인 후 자동 실행 (Phase 2 미구현) |
| 포지션 관리 | 없음 | 손절/익절 자동화 (Phase 2 미구현) |
| 운영 가시성 | 없음 | 헬스체크 + 일일 리포트 |
