# SMA Candidates 풀 완성도 보완 계획

**작성일**: 2026-03-30
**목표 버전**: 2.3.0
**근거 문서**: `docs/SMA_완성도_평가.md` 비즈니스 1.2 / 수익 3.2

---
## 1. 현황 (As-Is)

### 1.1 현재 구현된 Redis 후보 풀

| Redis 키 | 갱신 방식 | 소스 API | 필터 조건 | 연결 전략 | TTL |
|----------|----------|---------|----------|---------|-----|
| `candidates:{001/101}` | lazy (TTL 만료 시 재조회) | ka10029 예상체결등락률상위 | 갭 3~30%, 거래대금 미필터 | S1, S7, S12 | 3분 |
| `candidates:swing:{001/101}` | lazy | ka10027 sort_tp=1 상승률 | 등락률 0.5~8%, 1천원↑, 거래대금 미필터 | S8, S9, **S13**, S15 | 5분 |
| `candidates:oversold:{001/101}` | lazy | ka10027 sort_tp=3 하락률 | 하락률 3~10%, 1천원↑, 거래대금 미필터 | S14 | 5분 |
| `candidates:newhigh:{001/101}` | lazy | ka10016 ntl_tp=1 신고가 | 52주 신고가, 만주 이상 | S10, (S13 Java) | 5분 |
| **(없음)** | — | ka10035 외인연속순매매 | 연속 순매수, trdeTp=2 | S11 (직접 호출) | — |

### 1.2 S11 실행 경로 (문제 확인)

```
TradingScheduler.scanFrgnCont()
  └─ strategyService.scanFrgnCont(market)      ← S11 로직
       └─ apiService.fetchKa10035(...)          ← 매 15분 직접 API 호출
                                                  candidates 풀 체계 완전 외부
```

### 1.3 S13 Java ↔ Python 불일치 (문제 확인)

```
[Java]  TradingScheduler.scanBoxBreakout()
          └─ candidateService.getSwingAndNewHighCandidates()  ← swing ∪ newhigh
               (candidates:swing + candidates:newhigh 합산)

[Python] strategy_13_box_breakout.py
          └─ rdb.lrange("candidates:swing:001", ...)          ← swing만 (G1 작업 결과)
               newhigh 풀 누락
```

### 1.4 거래대금 필터 부재 (문제 확인)

`CandidateService.java` 내 `getSwingCandidates()`, `getOversoldCandidates()`:
```java
.trdePricaCnd("0")   // 전체 (거래대금 무제한 → 유동성 극소 종목 포함 가능)
```

ka10027 API의 `trde_prica_cnd` 파라미터: `"0"`전체 / `"2"`10억원↑ / `"3"`50억원↑ / `"4"`100억원↑

### 1.5 풀 갱신 stampede 위험 (구조 문제)

현재 모든 풀이 **lazy 방식** (TTL 만료 후 첫 번째 호출이 재조회).
예: 10:00에 S8/S9/S13/S15가 각각 `candidates:swing:`을 동시 조회 시 TTL 만료 상태면
4개 cron이 동시에 API 호출 가능 → Kiwoom API rate limit 위험 + 중복 캐싱.

---

## 2. 식별된 갭

| ID | 구분 | 설명 | 영향 전략 | 우선순위 |
|----|------|------|---------|---------|
| G-C1 | 구조 | S11 전용 candidates 풀 없음 – 매 15분 직접 API 호출 | S11 | **P0** |
| G-C2 | 불일치 | Python S13이 swing만 사용 → Java S13(swing+newhigh)과 후보군 불일치 | S13 | **P0** |
| G-C3 | 품질 | swing/oversold 풀 거래대금 필터 없음 – 저유동성 종목 유입 | S8/S9/S13/S14/S15 | **P1** |
| G-C4 | 운영 | lazy 방식 stampede – 여러 전략 cron이 동시에 TTL 만료 시 다중 API 호출 | 전 전략 | **P1** |
| G-C5 | 운영 | 풀 크기 모니터링 없음 – 빈 풀 무음 실패 | 전 전략 | **P1** |
| G-C6 | 수익 | S12 종가강도가 갭 풀(candidates:001) 사용 → 종가 전략에 부적합 | S12 | **P2** |
| G-C7 | 수익 | S15 다중지표 전략이 단순 상승률 풀 사용 – 거래대금 교차 검증 없음 | S15 | **P2** |

---

## 3. 세부 구현 계획

---

### G-C1. S11 전용 candidates 풀 신설 (P0)

**목표**: `candidates:frgncont:{001/101}` Redis 키를 CandidateService 체계에 통합
**API**: ka10035 외인연속순매매상위 (이미 `KiwoomApiService.fetchKa10035()` 구현됨)

#### 3.1.1 CandidateService.java – getFrgnContCandidates() 추가

```java
private static final String FRGNCONT_KEY = "candidates:frgncont:";
private static final Duration FRGNCONT_TTL = Duration.ofMinutes(30); // 외인 포지션은 일 단위 변동

/**
 * ka10035 외인연속순매수 상위, TTL 30분.
 * key: candidates:frgncont:{market}
 */
public List<String> getFrgnContCandidates(String market) {
    String cacheKey = FRGNCONT_KEY + market;
    List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
    if (cached != null && !cached.isEmpty()) return cached;

    if (!MarketTimeUtil.isTradingActive()) return Collections.emptyList();

    try {
        var resp = apiService.fetchKa10035(
            StrategyRequests.FrgnContNettrdRequest.builder()
                .mrktTp(market)
                .trdeTp("2")        // 연속순매수
                .baseDtTp("1")      // 최근 1일 기준
                .stexTp("1")
                .build());

        if (resp == null || !resp.isSuccess()) return Collections.emptyList();

        List<String> codes = resp.getFrgnContNettrdUpper().stream()
            .filter(i -> i.getStkCd() != null && !i.getStkCd().isBlank())
            .map(i -> i.getStkCd())
            .limit(50)
            .collect(Collectors.toList());

        if (!codes.isEmpty()) {
            redis.delete(cacheKey);
            redis.opsForList().rightPushAll(cacheKey, codes);
            redis.expire(cacheKey, FRGNCONT_TTL);
        }
        return codes;
    } catch (Exception e) {
        log.warn("[CandidateService] getFrgnContCandidates 오류 [{}]: {}", market, e.getMessage());
        return Collections.emptyList();
    }
}
```

#### 3.1.2 StrategyService.java – scanFrgnCont() 수정

```java
// 수정 전
var contResp = apiService.fetchKa10035(
    StrategyRequests.FrgnContNettrdRequest.builder().mrktTp(market)...);
// 각 항목을 직접 처리...

// 수정 후 – candidates 풀에서 종목 코드만 읽고, ka10035 데이터는 상세 점수용으로만 활용
List<String> candidates = candidateService.getFrgnContCandidates(market);
if (candidates.isEmpty()) return Collections.emptyList();
// 이후 기존 로직(ka10035 응답에서 세부 지표 추출)을 candidates 필터 기반으로 재구성
```

**ka10035 응답 필드 (기존 구현 확인)**:
- `dm1`, `dm2`, `dm3`: 최근 1/2/3일 순매수량
- `tot`: 연속 순매수 합계

---

### G-C2. Python S13 풀 – swing ∪ newhigh 정합성 복원 (P0)

**문제**: G1 작업에서 S13 Python이 `candidates:swing`만 읽도록 변경 →
Java TradingScheduler.scanBoxBreakout()가 `getSwingAndNewHighCandidates()`로 swing+newhigh 합산하는 것과 불일치.

박스권 돌파 당일에는 52주 신고가 갱신을 동반하는 경우가 많으므로 `newhigh` 풀 포함이 전략적으로 타당.

#### strategy_13_box_breakout.py 수정

```python
# 수정 전 (G1 작업 결과)
kospi  = await rdb.lrange("candidates:swing:001", 0, 99)
kosdaq = await rdb.lrange("candidates:swing:101", 0, 99)
if not kospi and not kosdaq:
    kospi  = await rdb.lrange("candidates:001", 0, 99)
    kosdaq = await rdb.lrange("candidates:101", 0, 99)

# 수정 후 – Java 로직과 동일하게 swing ∪ newhigh
swing_k  = await rdb.lrange("candidates:swing:001", 0, 99)
swing_q  = await rdb.lrange("candidates:swing:101", 0, 99)
newhigh_k = await rdb.lrange("candidates:newhigh:001", 0, 49)
newhigh_q = await rdb.lrange("candidates:newhigh:101", 0, 49)
kospi  = list(dict.fromkeys(swing_k + newhigh_k))
kosdaq = list(dict.fromkeys(swing_q + newhigh_q))
if not kospi and not kosdaq:                       # 폴백: 갭 풀
    kospi  = await rdb.lrange("candidates:001", 0, 99)
    kosdaq = await rdb.lrange("candidates:101", 0, 99)
```

---

### G-C3. 거래대금 최소값 필터 적용 (P1)

**목표**: 스윙/과매도 풀에서 유동성 극소 종목 제거
**기준**: 거래대금 10억원 이상 (`trdePricaCnd = "2"`)
**영향 범위**: S8/S9/S13/S14/S15 후보군 품질 향상

ka10027 `trde_prica_cnd` 옵션:
| 값 | 기준 |
|----|------|
| `"0"` | 전체 (현재 – 미필터) |
| `"2"` | 10억원 이상 |
| `"3"` | 50억원 이상 |
| `"4"` | 100억원 이상 |

**→ `"2"` (10억원) 적용: 지나치게 좁히지 않으면서 유동성 확보**

#### CandidateService.java 수정 (2곳)

```java
// getSwingCandidates() – 현재
.trdePricaCnd("0")
// 수정 후
.trdePricaCnd("2")   // 거래대금 10억원 이상

// getOversoldCandidates() – 현재
.trdePricaCnd("0")
// 수정 후
.trdePricaCnd("2")   // 거래대금 10억원 이상
```

> **주의**: `getNewHighCandidates()` (ka10016)는 이미 `trdeQtyTp("00010")` (만주 이상)으로
> 유동성 1차 필터가 적용되어 있어 별도 변경 불필요.

---

### G-C4. Lazy 방식 Stampede 방지 – Proactive Refresh Cron 추가 (P1)

**목표**: 전략 cron이 실행되기 전에 풀이 미리 채워져 있도록 보장
**원칙**: 전략 스캔 cron보다 **2~3분 선행** 갱신 cron 등록

#### TradingScheduler.java – 풀 사전 갱신 메서드 추가

```java
/**
 * 08:55 – 정규장 개시 전 스윙·과매도 풀 워밍업
 * S8(10:00~), S9(09:30~), S13(09:30~), S15(10:10~) 의 첫 스캔 전 선행 갱신
 */
@Scheduled(cron = "0 55 8 * * MON-FRI")
public void warmupSwingPools() {
    for (String mkt : List.of("001", "101")) {
        candidateService.getSwingCandidates(mkt);
        candidateService.getOversoldCandidates(mkt);
        candidateService.getNewHighCandidates(mkt);
        candidateService.getFrgnContCandidates(mkt);
    }
    log.info("[Warmup] 스윙·과매도·신고가·외인연속 풀 사전 갱신 완료");
}

/**
 * 09:28, 09:58, 10:28 ... 매 30분 (xx:28) – 스윙 풀 선행 갱신
 * 5분 TTL 풀들이 S8(10:00), S9(09:30~) 스캔 직전 항상 유효하도록
 */
@Scheduled(cron = "0 28/30 9-14 * * MON-FRI")
public void proactiveSwingRefresh() {
    if (!MarketTimeUtil.isTradingActive()) return;
    for (String mkt : List.of("001", "101")) {
        // TTL 강제 만료 후 재조회 (기존 TTL 남아있어도 갱신)
        redis.delete("candidates:swing:" + mkt);
        redis.delete("candidates:oversold:" + mkt);
        candidateService.getSwingCandidates(mkt);
        candidateService.getOversoldCandidates(mkt);
    }
}
```

> **TTL 강제 만료**: `redis.delete()` 후 재조회로 확실한 갱신 보장.
> 30분 주기 갱신 × 5분 TTL = 최대 5분 지연으로 풀 신선도 유지.

---

### G-C5. 풀 크기 메타데이터 기록 및 빈 풀 경보 (P1)

**목표**: Redis에 풀 메타를 기록하여 Telegram `/상태` 명령어 및 자동 경보에 활용

#### 3.5.1 CandidateService.java – saveMeta() 헬퍼 추가

```java
private static final Map<String, String> META_SOURCE = Map.of(
    "swing",    "ka10027(상승률0.5~8%)",
    "oversold", "ka10027(하락률3~10%)",
    "newhigh",  "ka10016(52주신고가)",
    "frgncont", "ka10035(외인연속순매수)",
    "default",  "ka10029(갭3~30%)"
);

private void saveMeta(String type, String market, int size) {
    String metaKey = "candidates:meta:" + type + ":" + market;
    redis.opsForHash().putAll(metaKey, Map.of(
        "size",       String.valueOf(size),
        "updated_ms", String.valueOf(System.currentTimeMillis()),
        "source",     META_SOURCE.getOrDefault(type, type)
    ));
    redis.expire(metaKey, Duration.ofHours(1));
}
```

각 풀 저장 시 마지막에 `saveMeta(type, market, codes.size())` 호출.

#### 3.5.2 DataQualityScheduler.java (신규) – 빈 풀 감지

```java
@Scheduled(cron = "0 5 10 * * MON-FRI")  // 10:05 – 장 초반 풀 상태 점검
public void checkPoolHealth() {
    List<String> emptyPools = new ArrayList<>();
    for (String type : List.of("swing", "oversold", "newhigh", "frgncont")) {
        for (String mkt : List.of("001", "101")) {
            Long size = redis.opsForList().size("candidates:" + type + ":" + mkt);
            if (size == null || size == 0) {
                emptyPools.add(type + ":" + mkt);
            }
        }
    }
    if (!emptyPools.isEmpty()) {
        String alert = "⚠️ 빈 candidates 풀 감지: " + String.join(", ", emptyPools);
        log.warn("[DataQuality] {}", alert);
        redisService.pushTelegramQueue(buildAlertMsg(alert));
    }
}
```

---

### G-C6. S12 종가강도 풀 교체 (P2)

**문제**: `scanClosingStrength()`가 `getAllCandidates()` (갭 풀 = ka10029, 장전 갭 기준)를 사용.
14:30 이후 종가 전략에는 장중 **거래대금 상위** 종목이 적합.

**API**: ka10032 거래대금상위 (이미 `KiwoomApiService.fetchKa10032()` 구현됨)
**Redis 키**: `candidates:trdeval:{001/101}` 신설

#### CandidateService.java – getTrdeValCandidates() 추가

```java
private static final String TRDEVAL_KEY = "candidates:trdeval:";

/**
 * ka10032 거래대금상위, TTL 10분.
 * key: candidates:trdeval:{market}
 * S12 종가강도 및 종가 임박 전략용
 */
public List<String> getTrdeValCandidates(String market) {
    String cacheKey = TRDEVAL_KEY + market;
    List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
    if (cached != null && !cached.isEmpty()) return cached;

    if (!MarketTimeUtil.isTradingActive()) return Collections.emptyList();

    try {
        var resp = apiService.fetchKa10032(
            StrategyRequests.TrdePricaUpperRequest.builder()
                .mrktTp(market)
                .sortTp("1")       // 거래대금 순
                .stexTp("1")
                .build());

        List<String> codes = resp.getTrdePricaUpper().stream()
            .map(i -> i.getStkCd())
            .filter(cd -> cd != null && !cd.isBlank())
            .limit(50)
            .collect(Collectors.toList());

        if (!codes.isEmpty()) {
            redis.delete(cacheKey);
            redis.opsForList().rightPushAll(cacheKey, codes);
            redis.expire(cacheKey, Duration.ofMinutes(10));
            saveMeta("trdeval", market, codes.size());
        }
        return codes;
    } catch (Exception e) {
        log.warn("[CandidateService] getTrdeValCandidates 오류 [{}]: {}", market, e.getMessage());
        return Collections.emptyList();
    }
}
```

#### TradingScheduler.java – scanClosingStrength() 수정

```java
// 수정 전
List<String> candidates = candidateService.getAllCandidates();

// 수정 후
List<String> candidates = Stream.concat(
    candidateService.getTrdeValCandidates("001").stream(),
    candidateService.getTrdeValCandidates("101").stream()
).distinct().limit(50).collect(Collectors.toList());
```

---

### G-C7. S15 모멘텀 동조 풀 품질 강화 (P2)

**현황**: S15 Python/Java 모두 `candidates:swing` 사용 (상승률 0.5~8%, 거래대금 미필터).
S15는 MACD·RSI·Stochastic·OBV 4개 지표를 교차 확인하는 전략으로,
**거래대금 유동성이 충분한 종목**에서만 지표 신뢰도가 높음.

**API**: ka10031 전일거래량상위 (이미 `KiwoomApiService.fetchKa10031()` 구현됨)
**개선**: `candidates:swing` ∩ `candidates:volsurge` 교집합 우선 사용

**ka10031 응답 필드**: `stk_cd`, `stk_nm`, `cur_prc`, `flu_rt`, `trde_qty`, `pred_trde_qty_pre_rt` (전일거래량대비율)

#### strategy_15_momentum_align.py 수정

```python
# 수정 후 – 스윙풀(0.5~8%) ∩ 거래량급증풀 교집합 우선
swing_k = set(await rdb.lrange("candidates:swing:001", 0, 99))
swing_q = set(await rdb.lrange("candidates:swing:101", 0, 99))
vol_k   = set(await rdb.lrange("candidates:volsurge:001", 0, 49))
vol_q   = set(await rdb.lrange("candidates:volsurge:101", 0, 49))

# 교집합 우선 (거래량급증 + 소폭상승), 없으면 스윙풀 단독
kospi  = list(swing_k & vol_k) or list(swing_k)
kosdaq = list(swing_q & vol_q) or list(swing_q)
if not kospi and not kosdaq:                   # 폴백
    kospi  = await rdb.lrange("candidates:001", 0, 99)
    kosdaq = await rdb.lrange("candidates:101", 0, 99)
```

#### CandidateService.java – getVolSurgeCandidates() 추가

```java
private static final String VOLSURGE_KEY = "candidates:volsurge:";

/**
 * ka10031 전일거래량상위, 전일대비 120% 이상 필터.
 * key: candidates:volsurge:{market}, TTL 5분
 */
public List<String> getVolSurgeCandidates(String market) {
    String cacheKey = VOLSURGE_KEY + market;
    List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
    if (cached != null && !cached.isEmpty()) return cached;

    if (!MarketTimeUtil.isTradingActive()) return Collections.emptyList();

    try {
        var resp = apiService.fetchKa10031(
            StrategyRequests.PrevVolumeUpperRequest.builder()
                .mrktTp(market)
                .sortTp("1")
                .stexTp("1")
                .build());

        List<String> codes = resp.getPrevVolumeUpper().stream()
            .filter(i -> {
                try {
                    return Double.parseDouble(i.getPredTrdeQtyPreRt()) >= 120.0; // 전일대비 120%+
                } catch (Exception e) { return false; }
            })
            .map(i -> i.getStkCd())
            .limit(50)
            .collect(Collectors.toList());

        if (!codes.isEmpty()) {
            redis.delete(cacheKey);
            redis.opsForList().rightPushAll(cacheKey, codes);
            redis.expire(cacheKey, POOL_TTL);
            saveMeta("volsurge", market, codes.size());
        }
        return codes;
    } catch (Exception e) {
        log.warn("[CandidateService] getVolSurgeCandidates 오류 [{}]: {}", market, e.getMessage());
        return Collections.emptyList();
    }
}
```

---

## 4. Redis 키 최종 체계

| Redis 키 패턴 | 소스 API | api-id | 연결 전략 | TTL | 우선순위 |
|-------------|---------|--------|---------|-----|---------|
| `candidates:{001/101}` | ka10029 예상체결등락률상위 | ka10029 | S1, S7 | 3분 | 기존 |
| `candidates:swing:{001/101}` | ka10027 상승률 0.5~8% | ka10027 | S8, S9, S15 | 5분 | 기존 (C3 개선) |
| `candidates:oversold:{001/101}` | ka10027 하락률 3~10% | ka10027 | S14 | 5분 | 기존 (C3 개선) |
| `candidates:newhigh:{001/101}` | ka10016 52주 신고가 | ka10016 | S10 | 5분 | 기존 |
| `candidates:frgncont:{001/101}` | ka10035 외인연속순매수 | ka10035 | **S11** | 30분 | **C1 신설** |
| `candidates:trdeval:{001/101}` | ka10032 거래대금상위 | ka10032 | **S12** | 10분 | **C6 신설** |
| `candidates:volsurge:{001/101}` | ka10031 전일거래량상위 | ka10031 | **S15 교집합** | 5분 | **C7 신설** |
| `candidates:meta:{type}:{001/101}` | 내부 집계 | — | 모니터링 | 1시간 | **C5 신설** |

> S13은 `candidates:swing` ∪ `candidates:newhigh` 합산 사용 (별도 키 없음, C2 적용).

---

## 5. 전략별 최종 후보 풀 연결 정의

| 전략 | 분류 | 후보 풀 | 출처 |
|------|------|--------|------|
| S1 갭상승 시초가 | 데이트레이딩 | `candidates:{market}` | ka10029 갭 3~30% |
| S7 동시호가 | 데이트레이딩 | `candidates:{market}` | ka10029 갭 3~30% |
| S8 골든크로스 | 스윙 | `candidates:swing:{market}` → 갭 폴백 | ka10027 상승 0.5~8% |
| S9 눌림목 | 스윙 | `candidates:swing:{market}` → 갭 폴백 | ka10027 상승 0.5~8% |
| S10 신고가 | 스윙 | `candidates:newhigh:{market}` | ka10016 52주 신고가 |
| S11 외인연속 | 스윙 | `candidates:frgncont:{market}` | ka10035 연속순매수 |
| S12 종가강도 | 데이트레이딩 | `candidates:trdeval:{market}` | ka10032 거래대금상위 |
| S13 박스권돌파 | 스윙 | swing ∪ newhigh → 갭 폴백 | ka10027 ∪ ka10016 |
| S14 과매도반등 | 스윙 | `candidates:oversold:{market}` | ka10027 하락 3~10% |
| S15 모멘텀동조 | 스윙 | swing ∩ volsurge → swing 폴백 | ka10027 ∩ ka10031 |

---

## 6. 구현 파일 목록 및 우선순위

### P0 – 즉시 수정

| # | 파일 | 변경 내용 |
|---|------|---------|
| 1 | `CandidateService.java` | `getFrgnContCandidates()` 추가 |
| 2 | `StrategyService.java` | `scanFrgnCont()` – 직접 fetchKa10035 → candidateService 위임 |
| 3 | `strategy_13_box_breakout.py` | candidates 조회를 swing ∪ newhigh 방식으로 수정 |

### P1 – 단기 개선

| # | 파일 | 변경 내용 |
|---|------|---------|
| 4 | `CandidateService.java` | `getSwingCandidates()` / `getOversoldCandidates()` `trdePricaCnd` 0→2 |
| 5 | `CandidateService.java` | `saveMeta()` 헬퍼 추가, 각 풀 저장 시 호출 |
| 6 | `TradingScheduler.java` | `warmupSwingPools()` (08:55), `proactiveSwingRefresh()` (xx:28/30분) cron 추가 |
| 7 | `DataQualityScheduler.java` | 신규 – 10:05 풀 크기 점검 |

### P2 – 중기 개선

| # | 파일 | 변경 내용 |
|---|------|---------|
| 8 | `CandidateService.java` | `getTrdeValCandidates()`, `getVolSurgeCandidates()` 추가 |
| 9 | `TradingScheduler.java` | `scanClosingStrength()` – `getAllCandidates` → `getTrdeValCandidates` |
| 10 | `strategy_15_momentum_align.py` | swing ∩ volsurge 교집합 조회 |

---

## 7. 예상 효과

| 지표 | 현재 | 개선 후 |
|------|------|--------|
| S11 API 중복 호출 | 매 15분 직접 호출 (cron 실행마다) | 30분 TTL 캐시, 1회 호출 |
| S13 후보 누락 (신고가 돌파 종목) | swing 풀만 (0.5~8%) → 신고가 종목 누락 | swing ∪ newhigh → 포괄 |
| 저유동성 종목 진입 위험 | 거래대금 무제한 | 10억원↑ 필터 |
| Stampede 위험 | TTL 만료 시 다수 동시 API 호출 | proactive refresh로 사전 갱신 |
| 빈 풀 무음 실패 | 감지 불가 | 10:05 자동 점검 + Telegram 경보 |
| S12 후보 적합도 | 장전 갭 기준 종목 → 종가 전략 부적합 | 장중 거래대금 상위 → 종가 적합 |
| S15 지표 신뢰도 | 유동성 미검증 종목 포함 | 거래량급증 교집합 → 지표 신뢰도↑ |
