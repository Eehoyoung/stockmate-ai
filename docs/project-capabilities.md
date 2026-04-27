# StockMate AI – 프로젝트 기능 및 한계 정의서

> **목적**: 4개 모듈의 현재 기능과 한계를 명확히 정의한다.
> **최종 업데이트**: 2026-03-21 (Phase 1/3/4 고도화 완료 후)

---

## 1. 프로젝트 전체 개요

| 항목 | 현재 상태 |
|------|-----------|
| **핵심 기능** | 실시간 시장 데이터 수집 → 7개 전술 신호 생성 → AI 점수화 → 텔레그램 알림 |
| **자동매매** | 미구현 (신호 발행까지만 동작, 주문 실행 없음) |
| **운영 환경** | 실전/모의 자동 분기 (KIWOOM_MODE=real/mock 환경변수) |
| **시장 범위** | 코스피 + 코스닥 (KRX 기준, NXT/통합 미활용) |

---

## 2. 모듈별 현재 기능

### 2.1 api-orchestrator (Java Spring Boot)

**할 수 있는 것**
- Kiwoom 액세스 토큰 발급 및 갱신 (`TokenService`)
- 장전/장중/장후 스케줄에 따른 7개 전술 신호 생성 (`TradingScheduler`)
- S1: 갭상승 후보 → `CandidateService`가 **ka10029**(예상체결등락률상위)로 갭 3~30% 필터
- S2: VI 해제 후 `vi_watch_queue`에서 팝 → 눌림목 -1%~-3% 감지
- S3: 기관/외국인 연속 순매수 종목 조회 (ka10131)
- S4: **ka10023(거래량급증) + ka10019(가격급등락)으로 사전 필터링** → 최대 30종목만 ka10080 호출
- S5: 프로그램 순매수 상위 종목 조회 (ka90003) + 외인 교집합 (ka90009)
- S6: 상위 테마 조회 (ka90001) → 테마 구성 후발주 필터 (ka90002)
- S7: **ka10029(갭 2~10%) + ka10030(거래대금 10억+) + ka10020(호가비율 200%+) 교집합** 사전 필터
- Redis `telegram_queue`에 신호 페이로드 직렬화 후 LPUSH (`toQueuePayload()` 중앙화)
- 체결/호가/예상체결/VI 실시간 데이터 Redis 저장 (`RedisMarketDataService`)
- WebSocket GRP1-4 구독 관리 (`WebSocketSubscriptionManager`)
- **장전 08:00** 후보 종목 전일종가 일괄 수집 (`preparePreOpenData`) → `ws:expected:{stkCd}` 사전 저장
- **장 마감 15:35** 일별 성과 집계 (`compileDailySummary`) → Redis + telegram_queue DAILY_REPORT 발행
- **API 오류 재시도**: 1700 Rate Limit 지수 백오프(3회), 8005 토큰 만료 자동 갱신 + 재시도
- **실전/모의 URL 자동 분기**: `KIWOOM_MODE` 환경변수로 WebClient baseUrl 자동 선택
- **Spring Boot Actuator**: GET /actuator/health 헬스체크 엔드포인트

**할 수 없는 것 (한계)**
- 주문 실행 불가 (kt10000/kt10001 미연동)
- 포지션/잔고 조회 불가 (kt20000류 미연동)

---

### 2.2 ai-engine (Python asyncio)

**할 수 있는 것**
- `telegram_queue`에서 신호 팝 → 규칙 기반 1차 점수 (`scorer.py`)
- **전략별 Claude 호출 임계값** 세분화 (S1:70, S2:65, S3:60, S4:75, S5:65, S6:60, S7:70)
- **일별 Claude 호출 상한** (MAX_CLAUDE_CALLS_PER_DAY=100, Redis 카운터)
- **전략별 압축 프롬프트** (~200 토큰)으로 Claude API 2차 평가 (`analyzer.py`)
- **Claude API 타임아웃(10s)** 및 오류 시 규칙 스코어 폴백
- `ai_scored_queue`에 최종 점수 + Claude 요약 LPUSH
- **오류 신호 dead-letter queue** (`error_queue`) 구현
- `ENABLE_STRATEGY_SCANNER=true` 시 `strategy_runner.py` 활성화
  - S1/S3/S5/S6/S7 전략 스캔을 직접 실행 (실제 Kiwoom API 호출)
- **비동기 Redis** (redis.asyncio) 전면 사용
- **GET /health** 헬스체크 엔드포인트 (포트 8082)

**할 수 없는 것 (한계)**
- strategy_2_vi_pullback.py, strategy_4_big_candle.py는 strategy_runner.py에서 호출되지 않음 (Java 전담)

---

### 2.3 websocket-listener (Python asyncio)

**할 수 있는 것**
- GRP5-8 WebSocket 구독 (0B 체결, 0D 호가, 0H 예상체결, 1h VI)
- 0B 데이터 → `ws:tick:{stkCd}` (Hash, TTL 30s)
- 0B 체결강도 → `ws:strength:{stkCd}` (List, 최근 10개)
- 0D 호가 → `ws:hoga:{stkCd}` (Hash, TTL 10s)
- 0H 예상체결 → `ws:expected:{stkCd}` (Hash, TTL 60s) + **pred_pre_pric 역산 저장**
- 1h VI 발동/해제 → `vi:{stkCd}` (Hash) (vi_watch_queue 등록은 api-orchestrator 전담)
- 연결 실패 시 지수 백오프 재연결, 최대 재시도 초과 시 `sys.exit(1)`
- **candidates:watchlist 30초마다 폴링** → 신규 종목 REG / 제거 종목 UNREG 동적 구독
- **ws:heartbeat** (Hash, TTL 30s) 10초마다 갱신
- **KIWOOM_MODE** 환경변수로 실전/모의 WS URL 자동 분기
- GET /health 헬스체크 (포트 8081)

**할 수 없는 것 (한계)**
- 네트워크 단절 후 누락된 데이터 복구 없음

---

### 2.4 telegram-bot (Node.js)

**할 수 있는 것**
- `ai_scored_queue`에서 신호 팝 → Telegram 메시지 발송
- 신호 타입별 메시지 포맷팅 (전략명, 종목, 점수, Claude 요약 포함)
- **진입가, 목표가(+8%), 손절가(-3%), 리스크/리워드(1:2.7)** 표시
- 전송 실패 시 재시도
- **사용자별 전략 필터**: `/filter s1 s4` → 지정 전략만 수신 (Redis user_filter:{chatId})
- **일일 리포트 자동 수신**: DAILY_REPORT 타입 자동 발송
- `/report` 명령어: daily_summary:{today} 조회
- `/filter` 명령어: 전략 수신 필터 설정/조회/해제
- 봇 명령어: /ping, /상태, /신호, /성과, /후보, /시세, /전술, /토큰갱신, /ws시작, /ws종료, /help

**할 수 없는 것 (한계)**
- 매수/매도 명령 수신 및 처리 불가 (Telegram → 주문 실행 경로 없음)
- 포지션/잔고 조회 명령 미지원
- 신호 승인 후 주문 실행 인터랙션 없음

---

## 3. 데이터 흐름 현황

```
[키움 WebSocket]
    │  0B/0D/0H/1h 실시간
    ▼
[websocket-listener] ──Redis ws:tick/hoga/expected/vi──▶ [api-orchestrator]
    │ candidates:watchlist 동적 구독                          │ 7개 전술 스캔
    │ ws:heartbeat 10초마다 갱신                              │ ka10029/10030/10023/10019/10020
    │ pred_pre_pric 역산 저장                                  │ ka10080/10081/10131
                                                              │ ka90001/90002/90003/90009
                                                              │ ka10001 (전일종가 사전 저장)
                                                              ▼
                                                       Redis telegram_queue
                                                              │
                                                              ▼
                                               [ai-engine] scorer → analyzer(Claude)
                                                  │ 전략별 임계값 + 일별 상한
                                                  │ 타임아웃 폴백, dead-letter queue
                                                              │
                                                              ▼
                                                       Redis ai_scored_queue
                                                              │
                                                              ▼
                                                     [telegram-bot] → 텔레그램 알림
                                                        │ 사용자별 전략 필터
                                                        │ 목표가/손절가/리스크리워드 표시
                                                        │ 일일 리포트 자동 발송

                                                              ❌ 주문 실행 없음 (Phase 2)
```

---

## 4. 알려진 버그 및 잘못된 동작

| ID | 위치 | 내용 | 심각도 | 상태 |
|----|------|------|--------|------|
| B-1 | `CandidateService` | ka10033(신용비율상위) 오용 → 거래량 기준 후보 선정 불가 | 높음 | **해결됨** (ka10029로 교체) |
| B-2 | `TradingScheduler.S7` | ka10033으로 동시호가 후보 조회 → 전혀 다른 종목 반환 | 높음 | **해결됨** (ka10029+ka10030+ka10020 교집합) |
| B-3 | `strategy_runner.py` | Kiwoom API 실제 호출 없음 → 장에서 실제 동작 불가 | 높음 | **해결됨** (httpx 실제 API 호출 구현) |
| B-4 | `ws:expected` | `pred_pre_pric` 저장 안 됨 → 갭 계산 시 0 나눗셈 가능 | 중간 | **해결됨** (redis_writer.py 역산 저장 + preparePreOpenData) |
| B-5 | `token_loader.py` | Redis 키 불일치: 문서는 `kiwoom:access_token`, 코드는 `kiwoom:token` | 낮음 | **해결됨** (kiwoom:token 통일) |

---

## 5. 외부 의존성 및 제약

| 항목 | 내용 |
|------|------|
| **Kiwoom REST Rate Limit** | 1700 오류 → 지수 백오프 3회 재시도 (1s/2s/4s) |
| **WebSocket GRP 제한** | api-orchestrator GRP1-4, websocket-listener GRP5-8 |
| **Claude API 비용** | 전략별 임계값 + 일별 상한(100회)으로 비용 제어 |
| **Redis TTL 정책** | ws:tick 30s / ws:hoga 10s / ws:expected 60s / ws:strength 5m |
| **PostgreSQL** | 신호 영구 저장 (TradingSignal 테이블) |

---

## 6. 한계 요약 (고도화 우선순위 기준)

| 우선순위 | 한계 | 영향 범위 |
|----------|------|-----------|
| P1 | 자동매매 미구현 (Phase 2) | 시스템 완성도 |
| P2 | 텔레그램 양방향 주문 없음 (Phase 2) | 운영 편의성 |
