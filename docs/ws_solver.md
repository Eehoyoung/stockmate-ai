# WebSocket 미구독 근본 원인 분석 및 해결 계획

> 작성일: 2026-03-23
> 대상 증상: `/score {종목코드}` 또는 `/quote {종목코드}` 실행 시 "실시간 데이터 없음" 반환

---

## 1. 아키텍처 개요

```
Kiwoom WS ──┬──► Java KiwoomWebSocketClient  (GRP 1~4)
            │       └─► Redis ws:tick / ws:hoga / ws:strength
            │
            └──► Python websocket-listener  (GRP 5~8)
                    └─► Redis ws:tick / ws:hoga / ws:strength (동일 키 공유)
```

두 WS 클라이언트가 **각기 다른 GRP 번호로 동일한 Redis 키에 씁니다.**
어느 쪽이든 살아있으면 실시간 데이터가 Redis에 유지됩니다.

---

## 2. Redis 키 TTL 현황

| 키 | TTL | 비고 |
|----|-----|------|
| `ws:tick:{stkCd}` | **30초** | 30초 내 메시지 없으면 자동 삭제 |
| `ws:hoga:{stkCd}` | **10초** | 호가 업데이트 빈도 낮으면 자주 만료 |
| `ws:strength:{stkCd}` | 300초 | 체결강도 리스트 |
| `ws:heartbeat` | 30초 | Python WS 연결 상태 확인 |
| `kiwoom:token` | 토큰 유효기간 | Java TokenService가 저장 |
| `candidates:001` | 없음 (LIST) | Java CandidateService가 저장 |

---

## 3. 근본 원인 목록

### 원인 1. `websocket-listener` 프로세스 미기동 (가장 빈번)

**현상:** Python 프로세스를 따로 실행해야 하는데, 재시작 후 자동으로 올라오지 않음.

**코드 증거:**
```python
# ws_client.py
if reconnect_count > MAX_RECONNECTS:  # MAX_RECONNECTS = 10
    logger.critical("최대 재연결 횟수 초과 – 프로세스 종료")
    sys.exit(1)  # 이후 아무도 재시작하지 않음
```

**해결:** 프로세스 매니저 도입 → [섹션 4.1]

---

### 원인 2. 기동 순서 의존성 (토큰이 없으면 WS 연결 불가)

**현상:** Java api-orchestrator가 먼저 기동되어 `kiwoom:token`을 Redis에 써야만 Python이 WS에 연결 가능.
Java 재시작 후 Python 미재시작 시 토큰 불일치로 연결 실패.

**코드 증거:**
```python
# token_loader.py
REDIS_TOKEN_KEY = "kiwoom:token"  # Java가 쓴 토큰 참조
MAX_RETRIES = 12  # 12회 * 5초 = 1분 대기 후 RuntimeError → sys.exit
```

Java 07:25 크론이 토큰 갱신하지만, **Python WS의 재연결 시 토큰 재로드 로직이 없음.**
`run_ws_loop`은 재연결 시마다 `load_token(rdb)`를 호출하므로 토큰 갱신 후엔 자동 복구 가능.
단, `sys.exit(1)` 후에는 불가.

**해결:** 프로세스 매니저 + 토큰 갱신 모니터링 → [섹션 4.1], [섹션 4.2]

---

### 원인 3. 개인 종목이 WebSocket 구독 목록에 없음 (/score 핵심 원인)

**현상:** Python ws_client는 `candidates:001`, `candidates:101` (Java CandidateService가 저장하는 거래량 상위 후보)만 구독함.
사용자가 개인적으로 보유한 종목 또는 관심 종목은 이 목록에 없으면 WS 수신 대상이 아님.

**코드 증거:**
```python
# ws_client.py
async def _subscribe_all(ws, rdb):
    kospi  = await _get_candidates(rdb, "001")   # candidates:001
    kosdaq = await _get_candidates(rdb, "101")   # candidates:101
    all_cands = list(dict.fromkeys(kospi + kosdaq))[:200]
    # → 목록에 없는 종목은 구독 안 됨
```

`candidates:watchlist` (Redis SET) 동적 구독 폴러가 이미 구현되어 있음:
```python
# ws_client.py _watchlist_poller()
watchlist = await rdb.smembers("candidates:watchlist")
# 신규 종목 REG, 제거 종목 UNREG 자동 처리 (30초 주기)
```

**해결:** `/score` 호출 시 해당 종목을 `candidates:watchlist`에 추가 → [섹션 4.3]

---

### 원인 4. 장 외 시간에 데이터 조회

**현상:** `ws:tick` TTL = 30초. 장 마감(15:30) 이후 모든 tick 데이터 소멸.
장 외 시간에 `/score` 호출하면 REST API fallback으로 동작하지만, 호가·체결강도는 제공 불가.

**해결:** 장 시간 체크 안내 메시지 추가 → [섹션 4.4]

---

### 원인 5. ws:hoga TTL 10초 – 호가 데이터 잦은 만료

**현상:** 호가잔량(0D) 업데이트 빈도가 낮은 종목은 10초 TTL로 인해 데이터가 자주 만료됨.
OvernightScoringService의 `bidRatioBonus()`가 항상 0점이 되는 원인.

**해결:** `ws:hoga` TTL을 30초로 연장 → [섹션 4.5]

---

### 원인 6. Java WS 자동 구독 스케줄이 장 중 수동 시작 시 누락

**현상:**
- 07:30 크론 → `setupPreMarketSubscription()` (Java WS, GRP 1~4)
- 09:00 크론 → `startMarketHours()` (Java WS, GRP 1~4 전환)
- Python ws_client는 **별도로** 수동 실행 필요

즉, 텔레그램 `/wsStart` 명령은 Java WS만 제어함.
Python ws_client는 독립 프로세스라 `/wsStart`로 제어 불가.

**해결:** `/wsStart` 명령에 Python 프로세스 상태 진단 안내 추가 → [섹션 4.4]

---

## 4. 해결 계획

### 4.1 프로세스 매니저 도입 (PM2 권장)

```bash
# pm2로 websocket-listener 관리
pm2 start main.py --name ws-listener --interpreter python3 \
  --restart-delay 5000 --max-restarts 10
pm2 start engine.py  --name ai-engine    --interpreter python3
pm2 startup   # 서버 재부팅 시 자동 시작
pm2 save
```

또는 `ecosystem.config.js` 작성:
```js
module.exports = {
  apps: [
    {
      name: 'ws-listener',
      script: 'main.py',
      interpreter: 'python3',
      cwd: '/path/to/websocket-listener',
      restart_delay: 5000,
      max_restarts: 20,
      env: { LOG_LEVEL: 'INFO' }
    },
    {
      name: 'ai-engine',
      script: 'engine.py',
      interpreter: 'python3',
      cwd: '/path/to/ai-engine',
      restart_delay: 5000,
      max_restarts: 20,
    }
  ]
}
```

**PM2 주요 명령:**
```bash
pm2 list              # 프로세스 목록
pm2 logs ws-listener  # 로그 실시간 확인
pm2 restart ws-listener
pm2 monit             # 리소스 모니터링
```

---

### 4.2 Java 기동 순서 보장 (Health check wait)

Python 기동 스크립트에 Java health check 대기 추가:
```bash
#!/bin/bash
# start_ws.sh
echo "Java api-orchestrator 기동 대기..."
until curl -sf http://localhost:8080/api/trading/health > /dev/null; do
  echo "  대기 중... (5초 후 재시도)"
  sleep 5
done
echo "Java 준비 완료 → websocket-listener 시작"
cd /path/to/websocket-listener && python main.py
```

---

### 4.3 `/score` 호출 시 동적 WS 구독 추가

**Java `TradingController`에 watchlist 추가 엔드포인트:**
```java
@PostMapping("/watchlist/add/{stkCd}")
public ResponseEntity<Map<String, String>> addToWatchlist(@PathVariable String stkCd) {
    redis.opsForSet().add("candidates:watchlist", stkCd);
    redis.expire("candidates:watchlist", Duration.ofHours(2));
    return ResponseEntity.ok(Map.of("status", "ok", "stk_cd", stkCd));
}
```

**`scoreStock()` 엔드포인트에서 자동 호출:**
```java
@GetMapping("/score/{stkCd}")
public ResponseEntity<Map<String, Object>> scoreStock(@PathVariable String stkCd) {
    // WS 구독 대상 아닌 종목은 watchlist에 추가 (Python이 30초 내 구독)
    redis.opsForSet().add("candidates:watchlist", stkCd);
    redis.expire("candidates:watchlist", Duration.ofHours(2));

    Map<String, Object> result = overnightScoringService.calcManualScore(stkCd);
    return ResponseEntity.ok(result);
}
```

**동작 흐름:**
```
/score 098460
  → Java: candidates:watchlist에 098460 추가 (SADD)
  → Python _watchlist_poller: 30초 내 감지 → WS REG 전송
  → 키움: 0B/0H/0D 스트림 시작
  → Redis: ws:tick:098460 생성 (TTL 30s)
  → 재조회 시 실시간 데이터로 점수 계산
```

> ⚠️ Python websocket-listener가 실행 중이어야 동작함. 미실행 시 watchlist 추가는 되지만 구독이 안 됨.

---

### 4.4 Telegram 명령어 개선

**`/status` 명령에 WS 상태 진단 추가:**
```
WS 상태 진단:
  ws:heartbeat: ✅ 정상 (업데이트: 5초 전)   ← Python WS 정상
  ws:heartbeat: ❌ 없음 (30초 TTL 만료)      ← Python WS 미실행
  ws:connected : ✅ Java WS 연결됨
```

**`/score` 결과에 재구독 안내 추가:**
- REST fallback 시: "30초 후 재조회하면 실시간 데이터로 갱신됩니다" 안내
- Python WS 미실행 감지 시: "ws-listener 프로세스를 확인하세요" 안내

---

### 4.5 `ws:hoga` TTL 연장 (10초 → 30초)

**Python `redis_writer.py`:**
```python
# 변경 전
await rdb.expire(key, 10)

# 변경 후
await rdb.expire(key, 30)
```

**Java `RedisMarketDataService.java`:**
```java
// 변경 전
private static final Duration HOGA_TTL = Duration.ofSeconds(10);

// 변경 후
private static final Duration HOGA_TTL = Duration.ofSeconds(30);
```

---

## 5. 즉시 적용 가능한 임시 조치

장중에 `/score` 실시간 데이터가 없을 때 빠른 복구 절차:

```
1. /status         → Java WS 상태 확인
2. /wsStart        → Java WS 재구독 시작
3. Python 터미널에서:
   cd websocket-listener && python main.py
4. 30초 후 /score {종목코드} 재시도
```

---

## 6. 적용 우선순위

| 우선순위 | 작업 | 효과 | 난이도 |
|---------|------|------|--------|
| 🔴 즉시 | PM2 도입 (4.1) | websocket-listener 자동 재시작 | 낮음 |
| 🔴 즉시 | `ws:hoga` TTL 연장 (4.5) | 호가 데이터 안정성 향상 | 낮음 |
| 🟡 단기 | /score watchlist 추가 (4.3) | 개인 종목 자동 구독 | 중간 |
| 🟡 단기 | /status WS 상태 진단 (4.4) | 장애 원인 빠른 파악 | 중간 |
| 🟢 중기 | 기동 순서 보장 스크립트 (4.2) | 전체 시스템 안정화 | 낮음 |
