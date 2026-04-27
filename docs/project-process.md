# StockMate AI – 프로젝트 전체 구조 및 매매 프로세스

> 작성일: 2026-03-21
> 버전: v1.0 (전체 버그 수정 및 아키텍처 정리 후)

---

## 1. 시스템 개요

StockMate AI는 **키움 REST/WebSocket API**를 통해 한국 주식 시장의 실시간 데이터를 수집하고, 7가지 전술로 매매 후보를 선별한 뒤, **Claude AI**의 최종 분석 결과를 **Telegram**으로 알림하는 자동 매매 신호 시스템이다.

```
Kiwoom Securities API
    │
    ├─ REST API  ──────────────────── api-orchestrator (Java)
    │                                  전술 스캔 · 스케줄러 · DB · 토큰 관리
    │
    └─ WebSocket ──┬─ api-orchestrator (GRP 1~4)   ← 체결/호가/VI 구독
                   └─ websocket-listener (GRP 5~8) ← 보완 실시간 데이터

Redis (공유 메시지 버스)
    ├─ ws:tick / ws:hoga / ws:expected / vi:{stk_cd}   실시간 시세
    ├─ candidates:{market}                              후보 종목 목록
    ├─ telegram_queue                                   신호 → AI Engine
    ├─ ai_scored_queue                                  AI 결과 → Telegram Bot
    └─ vi_watch_queue                                   VI 눌림목 감시 대기열

ai-engine (Python)
    telegram_queue 소비 → Claude AI 분석 → ai_scored_queue 발행

telegram-bot (Node.js)
    ai_scored_queue 소비 → Telegram 메시지 발송
```

---

## 2. 모듈별 역할

### 2-1. `api-orchestrator` (Java / Spring Boot 4.0)

| 역할 | 설명 |
|---|---|
| 토큰 관리 | Kiwoom OAuth2 토큰 발급·갱신·Redis 캐싱 (`kiwoom:token`) |
| 후보 종목 관리 | CandidateService – 스캔 대상 종목 목록 Redis 저장 (`candidates:{market}`) |
| WebSocket 구독 | GRP1(0B 체결), GRP2(0D 호가), GRP3(0H 예상체결), GRP4(1h VI) |
| 실시간 데이터 저장 | RedisMarketDataService – ws:tick / ws:hoga / ws:expected / vi: 키 관리 |
| 전술 스캔 | StrategyService – S1~S7 전술 실행 |
| 신호 발행 | SignalService – 중복 체크 → DB 저장 → telegram_queue LPUSH |
| VI 감시 | ViWatchService – vi_watch_queue 소비 → S2 눌림목 체크 |
| 스케줄러 | TradingScheduler – 전술별 시간대 스캔 스케줄 |
| DB | PostgreSQL – TradingSignal, KiwoomToken, ViEvent, WsTickData |

### 2-2. `websocket-listener` (Python asyncio)

| 역할 | 설명 |
|---|---|
| 보완 WebSocket | GRP5(0B 체결), GRP6(0H 예상체결), GRP7(1h VI), GRP8(0D 호가) |
| Redis 단순 기록 | redis_writer.py – 수신 데이터를 Redis 해시에 저장만 수행 |
| 헬스체크 | HTTP `/health` 엔드포인트 (기본 포트 8081) |
| 토큰 의존 | Java api-orchestrator가 발급한 `kiwoom:token`을 Redis에서 읽어 사용 |

> **역할 경계**: vi_watch_queue 등록은 api-orchestrator 단독 담당. websocket-listener는 순수 데이터 기록기.

### 2-3. `ai-engine` (Python asyncio)

| 역할 | 설명 |
|---|---|
| 큐 소비 | queue_worker.py – `telegram_queue` RPOP 폴링 |
| 1차 스코어링 | scorer.py – 규칙 기반 점수 계산 (0~100점) |
| AI 분석 | analyzer.py – Claude API (`AsyncAnthropic`) 호출 |
| 결과 발행 | `ai_scored_queue` LPUSH |
| 전술 스캐너 (선택) | strategy_runner.py – `ENABLE_STRATEGY_SCANNER=true` 시 Python 전술 직접 실행 |

### 2-4. `telegram-bot` (Node.js / Telegraf)

| 역할 | 설명 |
|---|---|
| 신호 발송 | signals.js – `ai_scored_queue` 폴링 → 조건 충족 시 Telegram 메시지 |
| 봇 명령어 | `/상태`, `/신호`, `/성과`, `/후보`, `/시세`, `/전술`, `/토큰갱신`, `/ws시작`, `/ws종료` |
| 접근 제어 | `TELEGRAM_ALLOWED_CHAT_IDS` 환경변수로 허용 채팅 ID 제한 |

---

## 3. WebSocket 역할 분리 (GRP 구성)

```
Kiwoom WebSocket Server (wss://api.kiwoom.com:10000)
    │
    ├─ api-orchestrator (Java)
    │   GRP 1 : 0B 주식체결    → ws:tick:{stkCd}      TTL 30s
    │   GRP 2 : 0D 호가잔량    → ws:hoga:{stkCd}      TTL 10s
    │   GRP 3 : 0H 예상체결    → ws:expected:{stkCd}  TTL 60s
    │   GRP 4 : 1h VI발동해제  → vi:{stkCd}           TTL 3600s
    │                            vi_watch_queue (VI 해제 시만)
    │
    └─ websocket-listener (Python)
        GRP 5 : 0B 주식체결    → ws:tick:{stkCd}      (GRP1 보완)
        GRP 6 : 0H 예상체결    → ws:expected:{stkCd}  (GRP3 보완)
        GRP 7 : 1h VI발동해제  → vi:{stkCd} 상태만    (vi_watch_queue 등록 ✗)
        GRP 8 : 0D 호가잔량    → ws:hoga:{stkCd}      (GRP2 보완)
```

**주의사항:**
- 동일 Redis 키를 두 서비스가 모두 쓴다 (마지막 쓴 값이 유지됨).
- `vi_watch_queue` 등록은 **api-orchestrator 단독** 수행 (중복 등록 방지).
- websocket-listener 종료 시 api-orchestrator GRP 1~4가 단독으로 시스템을 유지.

---

## 4. Redis 키 계약

| 키 패턴 | 생산자 | 소비자 | TTL | 설명 |
|---|---|---|---|---|
| `kiwoom:token` | api-orchestrator | 모든 서비스 | 토큰 만료 -15분 | Kiwoom 액세스 토큰 |
| `candidates:{market}` | api-orchestrator | websocket-listener, ai-engine | - | 후보 종목 목록 |
| `ws:tick:{stkCd}` | 양쪽 WebSocket | ai-engine, api-orchestrator | 30s | 실시간 체결 데이터 |
| `ws:hoga:{stkCd}` | 양쪽 WebSocket | ai-engine, api-orchestrator | 10s | 호가잔량 |
| `ws:expected:{stkCd}` | 양쪽 WebSocket | api-orchestrator | 60s | 예상체결 (장전) |
| `ws:strength:{stkCd}` | 양쪽 WebSocket | ai-engine, api-orchestrator | 300s | 체결강도 리스트 (최근 10개) |
| `vi:{stkCd}` | 양쪽 WebSocket | api-orchestrator | 3600s | VI 발동/해제 상태 |
| `signal:{stkCd}:{strategy}` | api-orchestrator | api-orchestrator | 3600s | 신호 중복 방지 |
| `telegram_queue` | api-orchestrator, ai-engine(선택) | ai-engine | 12h | 전술 신호 대기열 |
| `ai_scored_queue` | ai-engine | telegram-bot | 12h | AI 분석 완료 신호 |
| `vi_watch_queue` | api-orchestrator | api-orchestrator | 2h | VI 눌림목 감시 대기열 |

---

## 5. 매매 신호 전체 흐름

```
[1] 전술 스캔 (api-orchestrator TradingScheduler)
        │
        ├─ S1 갭상승   09:00~09:10  2분마다  candidateService.getAllCandidates()
        ├─ S2 VI눌림목  09:00~15:20  5초마다  viWatchQueue 소비 (이벤트 기반)
        ├─ S3 외인기관  09:30~14:30  5분마다  ka10063, ka10131
        ├─ S4 장대양봉  09:30~14:30  3분마다  ka10080 + Redis 체결강도
        ├─ S5 프로그램  10:00~14:00  10분마다 ka90003, ka90009
        ├─ S6 테마후발  09:30~13:00  10분마다 ka90001, ka90002
        └─ S7 동시호가  08:30~09:00  2분마다  ka10033 + Redis 예상체결

[2] 신호 처리 (SignalService.processSignal)
        │
        ├─ Redis 중복 체크 (signal:{stkCd}:{strategy} TTL 1h)
        ├─ PostgreSQL TradingSignal 저장 (status=SENT)
        └─ telegram_queue LPUSH (TradingSignalDto.toQueuePayload)
               포함 필드: stk_cd, strategy, gap_pct, cntr_strength, bid_ratio,
                          vol_ratio, pullback_pct, body_ratio, net_buy_amt,
                          continuous_days, is_new_high, vol_rank, theme_name,
                          target_pct, stop_pct, entry_type, signal_score ...

[3] AI 엔진 처리 (ai-engine queue_worker.py)
        │
        ├─ telegram_queue RPOP
        ├─ Redis에서 실시간 시세 조회
        │      ws:tick / ws:hoga / ws:strength / vi:
        │
        ├─ [1차] scorer.py rule_score() ── 0~100점 규칙 기반 스코어
        │      S1: gap_pct(20) + strength(25) + bid_ratio(25)
        │      S2: pullback_pct(30) + is_dynamic(15) + strength(20) + bid_ratio(20)
        │      S3: net_buy_amt(25) + continuous_days(30) + vol_ratio(20)
        │      S4: vol_ratio(25) + body_ratio(20) + is_new_high(20) + strength(15)
        │      S5: net_buy_amt(40) + strength(20) + bid_ratio(15)
        │      S6: gap_pct(25) + strength(25) + bid_ratio(20)
        │      S7: gap_pct(25) + bid_ratio(30) + vol_rank(20)
        │      공통 페널티: 등락률 >15% (-20), <-5% (-15)
        │
        ├─ 60점 미만 → action=CANCEL (Claude 호출 없이 즉시 종료)
        │
        └─ [2차] analyzer.py analyze_signal() ── Claude API 분석
               입력: 신호 데이터 + 실시간 시세 + 규칙 스코어
               출력: {"action": "ENTER|HOLD|CANCEL",
                      "ai_score": 0~100,
                      "confidence": "HIGH|MEDIUM|LOW",
                      "reason": "...",
                      "adjusted_target_pct": ...,
                      "adjusted_stop_pct": ...}

[4] 결과 발행 (queue_worker.py → ai_scored_queue)
        enriched = {원본 신호} + {rule_score, ai_score, action, confidence,
                                   ai_reason, adjusted_target_pct, adjusted_stop_pct}

[5] Telegram 발송 (telegram-bot signals.js)
        │
        ├─ ai_scored_queue RPOP
        ├─ CANCEL → 무시
        ├─ ENTER + ai_score < 65 → 무시 (MIN_AI_SCORE 환경변수)
        ├─ HOLD  + ai_score < 80 → 무시
        └─ 조건 충족 → bot.telegram.sendMessage(chatId, HTML 포맷 메시지)
```

---

## 6. 일별 스케줄 타임라인

```
06:50  api-orchestrator  dailyPrepare() → 토큰 사전 발급
07:25  api-orchestrator  prepareSystem() → 토큰 갱신
07:30  api-orchestrator  startPreMarketSubscription()
                          GRP3(0H예상체결), GRP2(0D호가), GRP4(VI) 구독 시작
07:30  websocket-listener  기동 (env: KIWOOM_WS_URL, kiwoom:token 대기)
                            GRP5-8 구독 시작

08:30  [S7] 동시호가 스캔 시작 (2분마다, 09:00까지)

09:00  api-orchestrator  startMarketHours()
                          GRP1(0B체결), GRP2(0D호가), GRP4(VI) 정규장 전환
       [S1] 갭상승 스캔 시작 (2분마다, 09:10까지)
       [S2] VI 눌림목 감시 시작 (5초마다 큐 처리, 15:20까지)

09:30  [S3] 외인+기관 스캔 시작 (5분마다, 14:30까지)
       [S4] 장대양봉 스캔 시작 (3분마다, 14:30까지)
       [S6] 테마 후발주 스캔 시작 (10분마다, 13:00까지)

10:00  [S5] 프로그램+외인 스캔 시작 (10분마다, 14:00까지)

15:00  구독 갱신 중단
15:20  VI 눌림목 감시 종료
15:30  endOfDay() → 전체 구독 해제, 당일 신호 만료 처리, 전략별 성과 로그
23:30  DataCleanupScheduler → 3일 이상 된 WsTickData 삭제
```

---

## 7. 전술별 상세

### S1 – 갭상승 + 체결강도 시초가 매수
- **타이밍**: 09:00~09:10 (2분마다)
- **진입 조건**: 전일 종가 대비 갭 3~15% AND 체결강도 ≥ 130% AND 호가 매수우위 ≥ 1.3
- **진입 방식**: 시초가 시장가
- **목표/손절**: +4.0% / -2.0%

### S2 – VI 발동 후 눌림목 재진입
- **타이밍**: 장중 상시 (VI 해제 이벤트 기반, 10분 이내)
- **진입 조건**: VI 해제 후 현재가가 VI 발동가 대비 -1% ~ -3% AND 체결강도 ≥ 110% AND 호가비율 ≥ 1.3
- **진입 방식**: 지정가 눌림목
- **목표/손절**: +3.0% / -2.0%
- **구현**: ViWatchService.processViWatchQueue() ← websocket-listener write_vi() → vi_watch_queue 등록

### S3 – 외인 + 기관 동시 순매수 돌파
- **타이밍**: 09:30~14:30 (5분마다)
- **API**: ka10063(장중투자자별매매), ka10131(기관외국인연속 3일)
- **조건**: 동시 순매수 종목 AND 3일 연속 순매수 AND 거래량 ≥ 전일 1.5배
- **진입 방식**: 지정가 1호가
- **목표/손절**: +3.5% / -2.0%

### S4 – 장대양봉 + 거래량 급증 추격매수
- **타이밍**: 09:30~14:30 (3분마다)
- **API**: ka10080 (5분봉)
- **조건**: 양봉 몸통비율 ≥ 70% AND 상승폭 ≥ 3% AND 직전 5봉 대비 거래량 ≥ 5배 AND 체결강도 ≥ 140%
- **진입 방식**: 추격 시장가
- **목표/손절**: +4.0% / -2.5%

### S5 – 프로그램 순매수 + 외인 동반 상위
- **타이밍**: 10:00~14:00 (10분마다)
- **API**: ka90003(프로그램순매수상위50), ka90009(외국인기관매매상위)
- **조건**: 두 리스트 교집합 종목 → 프로그램 순매수 금액 기준 정렬
- **진입 방식**: 지정가 1호가
- **목표/손절**: +3.0% / -2.0%

### S6 – 테마 상위 + 후발주 연동
- **타이밍**: 09:30~13:00 (10분마다)
- **API**: ka90001(테마그룹상위5), ka90002(테마구성종목)
- **조건**: 테마 등락률 ≥ 2% AND 구성종목 중 상승률 0.5~상위30% 미만 AND 체결강도 ≥ 120%
- **목표**: 테마 상승률 × 60% (최대 5%)
- **진입 방식**: 지정가 1호가
- **손절**: -2.0%

### S7 – 장전 예상체결 + 호가잔량 동시호가
- **타이밍**: 08:30~09:00 (2분마다)
- **API**: ka10033(거래량순위상위50)
- **조건**: 예상갭 2~10% AND 호가 매수/매도비율 ≥ 2.0 AND 예상거래량 상위 50위
- **진입 방식**: 시초가 시장가
- **목표**: 갭 × 80% (최대 5%)
- **손절**: -2.0%

---

## 8. AI 스코어링 프로세스

```
신호 수신
    │
    ├─ 실시간 시세 조회 (Redis)
    │      ws:tick → 현재가 등락률
    │      ws:hoga → 호가 매수/매도 잔량 → bid_ratio
    │      ws:strength → 체결강도 5개 평균
    │      vi:     → VI 활성 여부
    │
    ├─ [1차] 규칙 스코어 (scorer.py rule_score)
    │      전술별 지표 점수 합산 + 공통 페널티
    │      결과: 0~100점
    │
    ├─ 60점 미만 → CANCEL (Claude API 미호출)
    │
    └─ 60점 이상 → Claude API 호출 (analyzer.py)
           시스템 프롬프트: prompts/signal_analysis.txt
           스코어링 기준:  prompts/scoring_criteria
           응답 형식: JSON
           {
               "action": "ENTER" | "HOLD" | "CANCEL",
               "ai_score": 0~100,
               "confidence": "HIGH" | "MEDIUM" | "LOW",
               "reason": "판단 근거",
               "adjusted_target_pct": 수정 목표수익률 (optional),
               "adjusted_stop_pct":   수정 손절률 (optional)
           }
           실패 시 폴백: rule_score 기반으로 action 결정
```

---

## 9. Telegram Bot 발송 조건

| action | ai_score | 발송 |
|---|---|---|
| CANCEL | any | ✗ |
| ENTER | < 65 (MIN_AI_SCORE) | ✗ |
| ENTER | ≥ 65 | ✅ 매수 신호 발송 |
| HOLD | < 80 | ✗ |
| HOLD | ≥ 80 | ✅ 관망 알림 발송 |
| FORCE_CLOSE | any | ✅ 강제청산 알림 발송 |

---

## 10. 환경변수 참조

### api-orchestrator (.env)
```
POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
KIWOOM_APP_KEY, KIWOOM_APP_SECRET, KIWOOM_BASE_URL, KIWOOM_WS_URL
CLAUDE_API_KEY, CLAUDE_MODEL
TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_IDS
```

### ai-engine (.env)
```
CLAUDE_API_KEY, CLAUDE_MODEL
REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
LOG_LEVEL                           # DEBUG | INFO | WARNING
POLL_INTERVAL_SEC                   # queue_worker 폴링 간격 (기본 2.0s)
AI_SCORE_THRESHOLD                  # Claude 호출 최소 점수 (기본 60.0)
ENABLE_STRATEGY_SCANNER             # true 시 Python 전술 스캐너 활성화
STRATEGY_SCAN_INTERVAL_SEC          # 전술 스캔 주기 (기본 60s)
```

### websocket-listener (.env)
```
KIWOOM_WS_URL, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
HEALTH_PORT                         # 헬스체크 포트 (기본 8081)
LOG_LEVEL
```

### telegram-bot (.env)
```
TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_IDS
REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
POLL_INTERVAL_MS                    # 큐 폴링 간격 (기본 2000ms)
MIN_AI_SCORE                        # ENTER 신호 최소 AI 점수 (기본 65)
```

---

## 11. 기동 순서

```
1. PostgreSQL, Redis 서버 기동
2. api-orchestrator 기동 → 토큰 발급 → Redis kiwoom:token 저장
3. websocket-listener 기동 → kiwoom:token 로드 → WS 구독 시작
4. ai-engine 기동 → telegram_queue 폴링 시작
5. telegram-bot 기동 → ai_scored_queue 폴링 시작
```

> api-orchestrator가 반드시 먼저 기동되어야 한다.
> websocket-listener는 `kiwoom:token`이 없으면 최대 1분(12회×5초) 대기 후 종료.

---

## 12. 데이터 보존 정책

| 데이터 | 저장소 | 보존 기간 |
|---|---|---|
| TradingSignal | PostgreSQL | 영구 (애플리케이션 레벨 조회) |
| KiwoomToken | PostgreSQL | 영구 (비활성화 플래그로 관리) |
| ViEvent | PostgreSQL | 영구 |
| WsTickData | PostgreSQL | 3일 (DataCleanupScheduler 23:30 삭제) |
| ws:tick, ws:hoga, ws:expected | Redis | 10~60초 TTL |
| ws:strength | Redis | 5분 TTL |
| vi:{stkCd} | Redis | 1시간 TTL |
| telegram_queue / ai_scored_queue | Redis | 12시간 TTL |
| vi_watch_queue | Redis | 2시간 TTL |
| signal:{stkCd}:{strategy} | Redis | 1시간 TTL (중복 방지) |
