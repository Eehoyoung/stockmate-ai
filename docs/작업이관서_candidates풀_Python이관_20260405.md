# 작업 이관서 — candidates 후보 풀 적재 Python 이관

**작성일**: 2026-04-05  
**작성자**: Claude Sonnet 4.6  
**수신**: candidates 풀 담당자  
**우선순위**: P1 (strategy_runner.py 동작에 직결)

---

## 1. 이관 배경

### 1-1. 현재 구조

```
Java TradingScheduler (cron 매 15분)
  └─ CandidateService.getS{N}Candidates()
        └─ Kiwoom REST API 조회
              └─ Redis candidates:s{N}:{market} LPUSH

Python strategy_runner.py
  └─ rdb.lrange("candidates:s{N}:{market}")  ← 이 풀을 읽어서 실행
```

### 1-2. 이관이 필요한 이유

| 문제 | 내용 |
|------|------|
| **Java WS 완전 비활성화** | `JAVA_WS_ENABLED=false`, WebSocket은 Python websocket-listener 단독 운영 |
| **S4/S3/S5/S6 풀 미구현** | Java `CandidateService`에 해당 메서드 없음 → 풀 항상 비어있음 → 해당 전략 전혀 실행 안 됨 |
| **실시간 필터 불가** | WS tick/체결강도 기반 사전 필터링은 Python(WS 데이터 보유)만 가능 |
| **이중 유지보수** | 전략 추가 시 Java + Python 양쪽 모두 수정 필요 |

### 1-3. Java CandidateService 구현 현황

| 전략 | Java 메서드 | 상태 |
|------|-------------|------|
| S1 | `getS1Candidates()` | ✅ 구현 (ka10029) |
| **S2** | **없음** | ❌ VI 이벤트 기반, Java 불필요 |
| **S3** | **없음** | ❌ 미구현 — 풀 항상 비어 전략 미실행 |
| **S4** | **없음** | ❌ 미구현 — 풀 항상 비어 전략 미실행 |
| **S5** | **없음** | ❌ 미구현 — 풀 항상 비어 전략 미실행 |
| **S6** | **없음** | ❌ N/A (strategy가 내부에서 직접 ka90001 조회) |
| S7 | `getS7Candidates()` | ✅ 구현 (ka10029) |
| S8 | `getS8Candidates()` | ✅ 구현 (ka10027) |
| S9 | `getS9Candidates()` | ✅ 구현 (ka10027) |
| S10 | `getS10Candidates()` | ✅ 구현 (ka10016) |
| S11 | `getS11Candidates()` | ✅ 구현 (ka10035) |
| S12 | `getS12Candidates()` | ✅ 구현 (ka10032) |
| S13 | `getS13Candidates()` | ✅ 구현 (S8+S10 합산) |
| S14 | `getS14Candidates()` | ✅ 구현 (ka10027 하락률) |
| S15 | `getS15Candidates()` | ✅ 구현 (S8 재활용) |

---

## 2. 이관 목표

`ai-engine/candidates_builder.py` 신규 모듈 생성.  
`strategy_runner.py`와 **독립된 루프**로 동작하며 매 N분마다 `candidates:s{N}:{market}` 키를 갱신한다.

```
Python candidates_builder.py (신규, 매 5~20분 주기)
  └─ Kiwoom REST API 조회 (Java와 동일한 API)
        └─ Redis candidates:s{N}:{market} LPUSH + EXPIRE

Python strategy_runner.py (기존, 매 60초 주기) — 변경 없음
  └─ rdb.lrange("candidates:s{N}:{market}")
```

---

## 3. 구현 명세

### 3-1. 파일 생성

**`ai-engine/candidates_builder.py`**

```python
"""
candidates_builder.py
Python 전담 후보 풀 적재 모듈.
Java CandidateService 역할을 Python으로 이관.

실행: engine.py 에서 asyncio.create_task(run_candidate_builder(rdb)) 로 기동
갱신 주기: CANDIDATE_BUILD_INTERVAL_SEC (기본 600초 = 10분)
"""
```

### 3-2. 전략별 후보 풀 구현 명세

아래 내용은 Java `CandidateService`의 로직을 그대로 Python으로 이관한 것이다.  
**API, 파라미터, 필터 조건을 변경하지 말 것.**

---

#### S1 — 갭상승 시초가 (적재 시각: 07:30~09:10, 3분 TTL)

```
API     : ka10029 예상체결등락률상위 (POST /api/dostk/rkinfo)
파라미터 : mrkt_tp={market}, sort_tp=1, trde_qty_cnd=10, stk_cnd=1, crd_cnd=0, pric_cnd=8, stex_tp=1
필터    : 3.0% ≤ flu_rt ≤ 15.0%
Redis 키 : candidates:s1:{market}
TTL     : 180초 (3분)
상한    : 100개
```

---

#### S4 — 장대양봉 추격 (09:30~14:30, 5분 TTL) ← **신규 구현 필요**

```
API     : ka10027 전일대비등락률상위 (POST /api/dostk/rkinfo)
파라미터 : mrkt_tp={market}, sort_tp=1, trde_qty_cnd=0010, stk_cnd=1,
           crd_cnd=0, updown_incls=0, pric_cnd=8, trde_prica_cnd=0, stex_tp=1
필터    : 2.0% ≤ flu_rt ≤ 20.0%  (장중 상승 중인 종목)
Redis 키 : candidates:s4:{market}
TTL     : 300초 (5분)  — 장대양봉은 빠르게 갱신 필요
상한    : 100개

※ 추가 우선순위 정렬: ws:strength:{stk_cd} Redis 키가 있으면
  체결강도 120% 이상 종목을 앞으로 정렬 (WS 구독 종목 우선)
```

---

#### S7 — 동시호가 (07:30~09:00, 3분 TTL)

```
API     : ka10029 예상체결등락률상위
파라미터 : S1과 동일
필터    : 2.0% ≤ flu_rt ≤ 10.0%
Redis 키 : candidates:s7:{market}
TTL     : 180초
상한    : 100개
```

---

#### S8 — 골든크로스 스윙 (09:05~14:30, 20분 TTL)

```
API     : ka10027 전일대비등락률상위
파라미터 : sort_tp=1, trde_qty_cnd=0010, stk_cnd=1, crd_cnd=0,
           updown_incls=0, pric_cnd=8, trde_prica_cnd=0, stex_tp=1
필터    : 0.5% ≤ flu_rt ≤ 8.0%
Redis 키 : candidates:s8:{market}
TTL     : 1200초 (20분)
상한    : 150개
```

---

#### S9 — 눌림목 스윙 (09:05~14:30, 20분 TTL)

```
API     : ka10027 (S8과 동일 파라미터)
필터    : 0.3% ≤ flu_rt ≤ 5.0%
Redis 키 : candidates:s9:{market}
TTL     : 1200초
상한    : 150개
```

---

#### S10 — 52주 신고가 (09:05~14:30, 20분 TTL)

```
API     : ka10016 신고저가요청 (POST /api/dostk/stkinfo)
파라미터 : mrkt_tp={market}, ntl_tp=1(신고가), high_low_close_tp=1,
           stk_cnd=1, trde_qty_tp=00010, crd_cnd=0, updown_incls=0,
           dt=250(52주), stex_tp=1
필터    : 없음 (전체)
Redis 키 : candidates:s10:{market}
TTL     : 1200초
상한    : 100개

※ S10 strategy 자체가 내부에서 ka10016+ka10023을 직접 조회하므로
  풀이 없어도 동작하지만, 풀이 있으면 속도 향상
```

---

#### S11 — 외인 연속 순매수 (09:05~14:30, 30분 TTL)

```
API     : ka10035 외인연속순매매상위 (POST /api/dostk/rkinfo)
파라미터 : mrkt_tp={market}, trde_tp=2(연속순매수), base_dt_tp=1, stex_tp=1
필터    : dm1 > 0 AND dm2 > 0 AND dm3 > 0 AND tot > 0
Redis 키 : candidates:s11:{market}
TTL     : 1800초 (30분)
상한    : 80개
```

---

#### S12 — 종가강도 (14:00~14:50, 10분 TTL)

```
API     : ka10032 거래대금상위 (POST /api/dostk/rkinfo)
파라미터 : mrkt_tp={market}, mang_stk_incls=0(관리종목제외), stex_tp=1
필터    : flu_rt > 0 (양전 종목만)
Redis 키 : candidates:s12:{market}
TTL     : 600초 (10분)
상한    : 50개
```

---

#### S13 — 박스권 돌파 (09:05~14:00, 20분 TTL)

```
출처 : candidates:s8:{market} ∪ candidates:s10:{market} 합산
별도 API 호출 없음 — S8/S10 풀이 적재된 후 실행
Redis 키 : candidates:s13:{market}
TTL     : 1200초
상한    : 150개
```

---

#### S14 — 과매도 반등 (09:05~14:00, 20분 TTL)

```
API     : ka10027 전일대비등락률상위 (하락률 정렬)
파라미터 : sort_tp=3(하락률), trde_qty_cnd=0010, stk_cnd=1,
           crd_cnd=0, updown_incls=0, pric_cnd=8, trde_prica_cnd=0
필터    : 3.0% ≤ abs(flu_rt) ≤ 10.0%
Redis 키 : candidates:s14:{market}
TTL     : 1200초
상한    : 100개
```

---

#### S15 — 모멘텀 정렬 (10:00~14:30, 20분 TTL)

```
출처 : candidates:s8:{market} 재활용 (S8과 동일)
Redis 키 : candidates:s15:{market}
TTL     : 1200초
상한    : 100개
```

---

### 3-3. 스케줄 구조 (권장)

```python
async def run_candidate_builder(rdb):
    """candidates_builder 메인 루프"""
    while True:
        now = datetime.now().time()
        token = await rdb.get("kiwoom:token")
        if token:
            if time(7, 25) <= now <= time(9, 10):
                # 장전: S1, S7 집중 갱신 (3분 주기)
                await _build_s1_s7(token, rdb)
                await asyncio.sleep(180)
            elif time(9, 5) <= now <= time(14, 50):
                # 장중: 전략별 주기 관리
                await _build_all(token, rdb)
                await asyncio.sleep(CANDIDATE_BUILD_INTERVAL_SEC)  # 기본 600초
            else:
                await asyncio.sleep(300)
        else:
            await asyncio.sleep(30)
```

### 3-4. engine.py 기동 추가

```python
# engine.py 기존 task 목록에 추가
from candidates_builder import run_candidate_builder

asyncio.create_task(run_candidate_builder(rdb))
```

---

## 4. Java 처리 방안

### 유지할 코드

| 항목 | 이유 |
|------|------|
| `TradingScheduler` 브리핑/리포트 로직 | WS 불필요, Java 유지 OK |
| `TokenService`, `TokenRefreshScheduler` | 토큰 관리는 Java 담당 유지 |
| `ForceCloseScheduler`, `DataCleanupScheduler` | DB/Redis 유지보수 |
| `CandidateService.tagStrategy()` | 전략 태그 기록, 무해 |

### 비활성화/삭제할 코드

| 항목 | 조치 |
|------|------|
| `TradingScheduler.preloadCandidatePools()` (cron 09:05~14:30) | **삭제** — Python이 대체 |
| `TradingScheduler.startPreMarketSubscription()` (07:30, S1/S7 적재) | **삭제** — Python이 대체 |
| `CandidateService.getS{N}Candidates()` 메서드 전체 | **삭제** (점진적 가능) |
| `TradingScheduler.preparePreOpenData()` 의 `getAllCandidates()` 호출 | Python candidates 풀에서 읽도록 수정 또는 삭제 |

> **점진적 이관 권장**: Python candidates_builder 정상 동작 확인 후 Java 코드 제거.  
> 과도기 중 Java와 Python이 동시에 같은 Redis 키에 쓰더라도 `LPUSH`는 멱등성이 없으므로  
> **Java를 먼저 비활성화한 후 Python을 활성화**할 것.

---

## 5. 검증 방법

Python candidates_builder 기동 후 아래로 확인:

```bash
# Redis CLI
KEYS candidates:s*
LLEN candidates:s4:001
LLEN candidates:s4:101
LRANGE candidates:s4:001 0 4
```

strategy_runner 로그에서 각 전략이 `후보 없음` 대신 정상 스캔되는지 확인.

---

## 6. 우선순위 및 순서

| 순서 | 작업 | 긴급도 |
|------|------|--------|
| 1 | `candidates_builder.py` 뼈대 생성 + S4 풀 구현 | 🔴 긴급 (S4 전혀 미실행) |
| 2 | S1, S7, S8, S9 이관 (Java에 있으나 Python으로 통합) | 🟠 높음 |
| 3 | S10~S15 이관 | 🟡 중간 |
| 4 | Java `preloadCandidatePools()` 비활성화 | 🟡 중간 (Python 안정화 후) |
| 5 | Java `CandidateService.getS{N}Candidates()` 삭제 | 🟢 낮음 (점진적) |

---

## 7. 참고 파일

| 파일 | 내용 |
|------|------|
| `ai-engine/strategy_runner.py` | candidates 풀 읽는 위치 (lrange 키 확인) |
| `api-orchestrator/.../CandidateService.java` | 이관 원본 로직 |
| `api-orchestrator/.../TradingScheduler.java` | 삭제 대상 스케줄 위치 |
| `docs/작업완료보고서_20260405.md` | 스코어링 고도화 배경 |

---

*이관서 작성: 2026-04-05 / Claude Sonnet 4.6*
