# 수정 계획안 — candidates:s{N}:001 / candidates:s{N}:101 전략별 풀 정상화

**작성일**: 2026-04-05  
**참고 문서**: `docs/작업이관서_candidates풀_Python이관_20260405.md`, `docs/candidate_pool_flow.md`  
**목표**: S1~S15 전 전략이 `candidates:s{N}:{market}` 풀을 정상적으로 사용하도록 수정

---

## 1. 현황 분류 및 문제 정의

### 1-1. 전략별 현재 상태

| 전략 | 풀 키 | Java 저장 | Python 사용 | 상태 | 조치 |
|------|-------|----------|------------|------|------|
| S1 | `s1:{mkt}` | ✅ `getS1Candidates()` ka10029 | ✅ `lrange s1:*` | **정상** | 없음 |
| S2 | 없음 | ❌ (이벤트 기반) | ❌ vi_watch_queue | **정상** | 없음 |
| S3 | 없음 | ❌ (직접 조회) | ❌ ka10063 직접 | **정상** | 없음 |
| S4 | `s4:{mkt}` | ❌ **미구현** | ⚠️ lrange 시도, 키 없음 | **🔴 완전 비동작** | 풀 적재 구현 |
| S5 | 없음 | ❌ (직접 조회) | ❌ ka90003 직접 | **정상** | 없음 |
| S6 | 없음 | ❌ (직접 조회) | ❌ ka90001 직접 | **정상** | 없음 |
| S7 | `s7:{mkt}` | ✅ `getS7Candidates()` ka10029 | ⚠️ 풀 무시, ka10029 직접 | **🟡 비효율** | Python이 풀 사용 |
| S8 | `s8:{mkt}` | ✅ `getS8Candidates()` ka10027 | ✅ `lrange s8:*` | **정상** | 없음 |
| S9 | `s9:{mkt}` | ✅ `getS9Candidates()` ka10027 | ✅ `lrange s9:*` | **정상** | 없음 |
| S10 | `s10:{mkt}` | ✅ `getS10Candidates()` ka10016 | ⚠️ 풀 무시, ka10016 직접 | **🟡 비효율** | Python이 풀 사용 |
| S11 | `s11:{mkt}` | ✅ `getS11Candidates()` ka10035 | ⚠️ 풀 무시, ka10035 직접 | **🟡 P3 미완료** | Python이 풀 사용 |
| S12 | `s12:{mkt}` | ✅ `getS12Candidates()` ka10032 | ⚠️ 풀 무시, ka10027 직접 | **🟡 기준 불일치** | 조치 불필요 (§4 참조) |
| S13 | `s13:{mkt}` | ✅ S8+S10 합산 | ✅ `lrange s13:*` | **정상** | 없음 |
| S14 | `s14:{mkt}` | ✅ `getS14Candidates()` ka10027 | ✅ `lrange s14:*` | **정상** | 없음 |
| S15 | `s15:{mkt}` | ✅ S8 재활용 | ✅ `lrange s15:*` | **정상** | 없음 |

### 1-2. 핵심 문제 요약

1. **S4 완전 비동작**: `candidates:s4:*` 키가 Redis에 존재하지 않음 → strategy_runner S4 블록이 항상 빈 리스트로 스킵
2. **S7 이중 API 낭비**: Java가 풀을 채우고 있음에도 Python이 ka10029를 한 번 더 호출
3. **S10/S11 이중 API 낭비**: 동일 API를 Java·Python 양쪽에서 중복 호출

---

## 2. 수정 방향

이관서(`작업이관서_candidates풀_Python이관_20260405.md`)의 장기 목표(Java 전면 이관)와 별개로,
**현재 Java 인프라를 유지하면서 즉시 수정 가능한 최소 변경**을 먼저 수행한다.

```
[단계 1 — 즉시 수정]  Java 코드 유지 + Python strategy 파일 수정
  ├─ S4 풀 적재: Java CandidateService에 getS4Candidates() 추가
  ├─ S7: scan_auction_signal()이 candidates:s7:* 풀을 읽도록 수정
  ├─ S10: scan_new_high_swing()이 candidates:s10:* 풀을 읽도록 수정
  └─ S11: scan_frgn_cont_swing()이 candidates:s11:* 풀을 읽도록 수정

[단계 2 — 이관서 방향]  candidates_builder.py 신규 생성 (Java 의존 제거)
  └─ 이관서 §3 명세대로 구현, 완료 후 Java preloadCandidatePools() 비활성화
```

이 문서는 **단계 1** 수정 사항을 상세히 기술한다.

---

## 3. 단계 1 수정 상세

### 3-1. S4 풀 적재 — Java `CandidateService.java` 수정

**파일**: `api-orchestrator/src/main/java/org/invest/apiorchestrator/service/CandidateService.java`

**추가 위치**: S7 메서드 바로 뒤 (~line 258)

```java
/**
 * S4 장대양봉 추격 후보 풀 (ka10027 등락률 2~20%, 캐시 5분).
 * 장중 상승 중인 종목 대상 – 장대양봉 후보는 빠른 갱신 필요.
 * key: candidates:s4:{market}
 */
public List<String> getS4Candidates(String market) {
    String cacheKey = "candidates:s4:" + market;
    List<String> cached = redis.opsForList().range(cacheKey, 0, -1);
    if (cached != null && !cached.isEmpty()) return cached;
    if (!org.invest.apiorchestrator.util.MarketTimeUtil.isTradingActive()) {
        log.debug("[Candidate] 거래 시간 외 – S4 풀 호출 생략 [market={}]", market);
        return Collections.emptyList();
    }
    try {
        KiwoomApiResponses.FluRtUpperResponse resp =
                apiService.fetchKa10027(
                        StrategyRequests.FluRtUpperRequest.builder()
                                .mrktTp(market).sortTp("1").trdeQtyCnd("0010")
                                .stkCnd("1").crdCnd("0").updownIncls("0")
                                .pricCnd("8").trdePricaCnd("0").build());
        if (resp == null || resp.getItems() == null) return Collections.emptyList();
        List<String> codes = resp.getItems().stream()
                .filter(item -> {
                    try {
                        double f = Double.parseDouble(item.getFluRt().replace("+","").replace(",",""));
                        return f >= 2.0 && f <= 20.0;   // 장중 상승 종목 (장대양봉 후보)
                    } catch (Exception ex) { return false; }
                })
                .map(KiwoomApiResponses.FluRtUpperResponse.FluRtUpperItem::getStkCd)
                .limit(100).collect(Collectors.toList());
        if (!codes.isEmpty()) {
            redis.delete(cacheKey);
            redis.opsForList().rightPushAll(cacheKey, codes);
            redis.expire(cacheKey, Duration.ofMinutes(5));  // 장대양봉은 5분 TTL
        }
        return codes;
    } catch (Exception e) {
        log.error("[Candidate] S4 후보 조회 실패 [{}]: {}", market, e.getMessage());
        return Collections.emptyList();
    }
}
```

**`TradingScheduler.java` 수정** — `preloadCandidatePools()` 메서드에 S4 추가:

```java
// 기존 코드 (S8~S15 루프 안)
try { candidateService.getS8Candidates(mkt); }  catch (Exception e) { ... }
// ↓ S4 라인 추가 (S8 이전)
try { candidateService.getS4Candidates(mkt); }  catch (Exception e) { log.warn("[Pool] S4 {} 오류: {}", mkt, e.getMessage()); }
```

---

### 3-2. S7 풀 사용 — `strategy_7_auction.py` 수정

**현재 문제**: `scan_auction_signal()`이 `candidates:s7:*` 풀을 무시하고 ka10029를 직접 호출.

**수정 방향**: 풀이 있으면 사용, 없으면 ka10029 직접 조회로 fallback.

**파일**: `ai-engine/strategy_7_auction.py`

`scan_auction_signal()` 함수 전체 교체:

```python
async def scan_auction_signal(token: str, market: str = "000", rdb=None) -> list:
    """전술 7: 동시호가 최종 스캔 함수"""

    # 1. candidates:s7:{market} 풀 우선 사용 (Java/candidates_builder 적재 기대)
    gap_candidates: dict = {}
    if rdb:
        try:
            pool = await rdb.lrange(f"candidates:s7:{market}", 0, -1)
            if pool:
                # 풀에서 읽은 종목코드를 gap_candidates 형태로 변환
                # (rank, gap_rt는 ws:expected 또는 기본값으로 보완)
                for i, stk_cd in enumerate(pool):
                    gap_candidates[stk_cd] = {"rank": i + 1, "gap_rt": 5.0}  # 기본값
                logger.debug("[S7] candidates:s7:%s 풀 사용 (%d개)", market, len(pool))
        except Exception as e:
            logger.debug("[S7] 풀 조회 실패, 직접 조회로 fallback: %s", e)

    # 풀이 비어있으면 ka10029 직접 조회 (fallback)
    if not gap_candidates:
        logger.debug("[S7] candidates:s7:%s 풀 없음 – ka10029 직접 조회", market)
        gap_candidates = await fetch_gap_rank(token, market)

    # 2. ws:expected 데이터로 gap_rt 실제값 보완 + 신용 필터
    high_credit_stocks = await fetch_credit_filter(token, market)

    results = []
    for stk_cd, info in gap_candidates.items():
        if stk_cd in high_credit_stocks:
            continue

        # 3. Redis에서 실시간 호가잔량(0D) 데이터 확인
        try:
            hoga_data = await rdb.hgetall(f"ws:hoga:{stk_cd}") if rdb else {}
        except Exception:
            hoga_data = {}

        if not hoga_data:
            continue

        total_bid = clean_num(hoga_data.get("125", 0))
        total_ask = clean_num(hoga_data.get("121", 1))
        bid_ratio = total_bid / total_ask
        live_gap_pct = clean_num(hoga_data.get("201", info["gap_rt"]))

        if (2.0 <= live_gap_pct <= 10.0) and (bid_ratio >= 2.0):
            stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
            results.append({
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "strategy": "S7_AUCTION",
                "gap_pct": round(live_gap_pct, 2),
                "bid_ratio": round(bid_ratio, 2),
                "vol_rank": info["rank"],
                "entry_type": "시초가_시장가",
                "target_pct": 4.5,
                "stop_pct": -2.0,
            })

    return sorted(results, key=lambda x: x["bid_ratio"], reverse=True)[:5]
```

---

### 3-3. S10 풀 사용 — `strategy_10_new_high.py` 수정

**현재 문제**: `scan_new_high_swing()`이 candidates 풀을 무시하고 ka10016+ka10023 전수 조회.

**수정 방향**: 
- 풀이 있으면 해당 종목 대상으로 정밀 검증만 수행 (ka10016 생략, ka10023으로 거래량 확인)
- 풀이 없으면 기존 전수 조회 방식으로 fallback

**파일**: `ai-engine/strategy_10_new_high.py`

`scan_new_high_swing()` 앞부분 수정:

```python
async def scan_new_high_swing(token: str, market: str = "000", rdb=None) -> list:
    """52주 신고가 돌파 스윙 전략 메인 스캐너"""

    # 1. candidates:s10:{market} 풀 확인 (market="000"이면 001+101 모두 조회)
    pool_codes: list[str] = []
    if rdb:
        try:
            markets_to_check = ["001", "101"] if market == "000" else [market]
            for mkt in markets_to_check:
                codes = await rdb.lrange(f"candidates:s10:{mkt}", 0, -1)
                pool_codes.extend(codes)
            pool_codes = list(dict.fromkeys(pool_codes))  # 중복 제거
            if pool_codes:
                logger.debug("[S10] candidates:s10:* 풀 사용 (%d개)", len(pool_codes))
        except Exception as e:
            logger.debug("[S10] 풀 조회 실패: %s", e)

    # 2. 원천 데이터 확보 (풀 없으면 전수 조회, 있으면 거래량 급증만 조회)
    if pool_codes:
        # 풀 기반 경로: ka10016 생략, ka10023으로 거래량 급증만 조회
        vol_surge_map = await fetch_volume_surge_map_all(token, market)
        new_high_items = [
            {"stk_cd": cd, "flu_rt": "0", "cur_prc": "0", "stk_nm": ""}
            for cd in pool_codes
        ]
        # ws:tick에서 실시간 flu_rt/cur_prc 보완
        if rdb:
            for item in new_high_items:
                try:
                    tick = await rdb.hgetall(f"ws:tick:{item['stk_cd']}")
                    if tick:
                        item["flu_rt"] = tick.get("flu_rt", "0")
                        item["cur_prc"] = tick.get("cur_prc", "0")
                        item["stk_nm"]  = tick.get("stk_nm", "")
                except Exception:
                    pass
    else:
        # 기존 전수 조회 경로 (fallback)
        logger.debug("[S10] 풀 없음 – ka10016+ka10023 전수 조회")
        new_high_items, vol_surge_map = await asyncio.gather(
            fetch_new_high_stocks_all(token, market),
            fetch_volume_surge_map_all(token, market),
        )

    # 이하 기존 필터링 로직 동일 (results 리스트 구성)
    results = []
    for item in new_high_items:
        stk_cd = item.get("stk_cd")
        try:
            flu_rt  = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
            cur_prc = abs(float(str(item.get("cur_prc", "0")).replace("+", "").replace(",", "")))
        except (TypeError, ValueError):
            continue

        if not (2.0 <= flu_rt <= 15.0):
            continue

        sdnin_rt = vol_surge_map.get(stk_cd, 0.0)
        if sdnin_rt < 100.0:
            continue

        await asyncio.sleep(_API_INTERVAL)
        cntr_str = await fetch_cntr_strength(token, stk_cd)

        await asyncio.sleep(_API_INTERVAL)
        bid_ratio = await fetch_hoga(token, stk_cd, rdb)

        try:
            from ma_utils import get_ma_context
            ma_ctx = await get_ma_context(token, stk_cd)
            if ma_ctx.valid and ma_ctx.is_overextended(threshold_pct=25.0):
                continue
        except Exception:
            pass

        score = (flu_rt * 0.3) + (min(sdnin_rt / 100, 5.0) * 12) + (max(cntr_str - 100, 0) * 0.2)
        stk_nm = item.get("stk_nm", "").strip() or ""

        results.append({
            "stk_cd":        stk_cd,
            "stk_nm":        stk_nm,
            "cur_prc":       round(cur_prc),
            "strategy":      "S10_NEW_HIGH",
            "flu_rt":        round(flu_rt, 2),
            "vol_surge_rt":  round(sdnin_rt, 1),
            "cntr_strength": round(cntr_str, 1),
            "bid_ratio":     round(bid_ratio, 3) if bid_ratio is not None else None,
            "score":         round(score, 2),
            "target_pct":    12.0,
            "stop_pct":      -5.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
```

---

### 3-4. S11 풀 사용 — `strategy_11_frgn_cont.py` 수정

**현재 문제**: `scan_frgn_cont_swing()`이 candidates 풀을 무시하고 ka10035 직접 조회 (CLAUDE.md P3).

**수정 방향**:
- 풀이 있으면 해당 종목에 대해 ws:tick Redis 데이터로 필터링 (ka10035 호출 절감)
- 풀이 없으면 기존 ka10035 직접 조회 fallback

**파일**: `ai-engine/strategy_11_frgn_cont.py`

`scan_frgn_cont_swing()` 앞부분 수정:

```python
async def scan_frgn_cont_swing(token: str, market: str = "000", rdb=None) -> list:
    """외국인 연속 순매수 스윙 전략 스캔 (Redis 풀 우선 → fallback 직접 조회)"""

    # 1. candidates:s11:{market} 풀 우선 확인
    pool_codes: list[str] = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s11:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S11] candidates:s11:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S11] 풀 조회 실패: %s", e)

    # 2. 원천 데이터 확보
    if pool_codes:
        # 풀 기반: 각 종목의 D1/D2/D3/tot 를 ka10035 단건 조회 또는
        # 전체 한 번 조회 후 교집합 필터
        raw_items = await fetch_frgn_cont_buy(token, market, max_pages=2)
        # 풀 종목만 필터
        pool_set = set(pool_codes)
        raw_items = [it for it in raw_items if it.get("stk_cd") in pool_set]
        logger.debug("[S11] 풀 필터 후 %d개", len(raw_items))
    else:
        # fallback: 기존 전수 조회
        logger.debug("[S11] 풀 없음 – ka10035 전수 조회")
        raw_items = await fetch_frgn_cont_buy(token, market, max_pages=2)

    if not raw_items:
        return []

    # 이하 기존 필터링 로직 동일
    results = []
    for item in raw_items:
        stk_cd = item.get("stk_cd")
        if not stk_cd:
            continue

        dm1 = _parse_qty(item.get("dm1", "0"))
        dm2 = _parse_qty(item.get("dm2", "0"))
        dm3 = _parse_qty(item.get("dm3", "0"))
        tot = _parse_qty(item.get("tot", "0"))

        if dm1 <= 0 or dm2 <= 0 or dm3 <= 0 or tot <= 0:
            continue

        flu_rt   = 0.0
        cntr_str = 100.0
        if rdb:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            if tick:
                flu_rt   = float(str(tick.get("flu_rt", "0")).replace("+", ""))
                cntr_str = float(str(tick.get("cntr_str", "100")).replace(",", ""))

        if not (0.0 < flu_rt <= 10.0):
            continue
        if cntr_str < 100.0:
            continue

        score   = (tot / 1_000_000) * 5 + (dm1 / 1_000_000) * 3 + (flu_rt * 0.5)
        cur_prc = abs(float(str(item.get("cur_prc", "0")).replace("+", "").replace(",", "")))

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        results.append({
            "stk_cd":       stk_cd,
            "stk_nm":       stk_nm,
            "strategy":     "S11_FRGN_CONT",
            "score":        round(score, 2),
            "cur_prc":      cur_prc,
            "dm1":          dm1,
            "dm2":          dm2,
            "dm3":          dm3,
            "tot":          tot,
            "flu_rt":       round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "entry_type":   "현재가_종가",
            "target_pct":   8.0,
            "target2_pct":  12.0,
            "stop_pct":     -4.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
```

---

### 3-5. S12 — 조치 불필요 (설계 차이)

S12 Python(`scan_closing_buy`)은 `ka10027 + ka10063`(등락률+기관수급 교차)을 기준으로 동작하고,
Java 풀(`candidates:s12:*`)은 `ka10032`(거래대금 상위) 기준이다.
두 기준은 **의도적으로 다른 필터**이며, 어느 쪽도 버그가 아니다.

> **결론**: S12 풀은 Java가 채우지만 Python은 독립적으로 동작하는 구조를 유지.
> 종가매매(14:30~14:50) 특성상 별도 풀 없이 직접 조회가 적절.

---

### 3-6. `strategy_runner.py` — S10 market 파라미터 수정

**현재 문제**: S10을 `market="000"` (전체)으로 호출하나, Java 풀은 `001`/`101`로 분리 저장.
풀 기반 경로에서 두 키를 모두 조회하도록 strategy_10 내부에서 처리하므로 runner는 변경 불필요.

> S10 내 3-3 수정 코드에서 `market == "000"` 이면 `001`+`101` 풀을 모두 조회하도록 이미 처리.

---

## 4. S2, S3, S5, S6 — 변경 없음 (설계 의도)

| 전략 | 이유 |
|------|------|
| S2 | VI 이벤트 기반. 사전 풀 개념이 없음. `vi_watch_queue` → `check_vi_pullback` 구조 유지. |
| S3 | ka10063 장중투자자별매매 = 실시간 데이터. 사전 캐시 의미 없음. |
| S5 | ka90003 프로그램순매수 = 실시간 순위. 10~14시 창구 집중 직접 조회 필요. |
| S6 | ka90001 테마그룹 = 당일 테마 실시간 변동. 캐시하면 신호 품질 저하. |

---

## 5. 수정 파일 목록 요약

### Java (api-orchestrator)

| 파일 | 수정 내용 |
|------|---------|
| `service/CandidateService.java` | `getS4Candidates()` 메서드 추가 (~30줄) |
| `scheduler/TradingScheduler.java` | `preloadCandidatePools()` 에 `getS4Candidates(mkt)` 호출 1줄 추가 |

### Python (ai-engine)

| 파일 | 수정 내용 | 크기 |
|------|---------|------|
| `strategy_7_auction.py` | `scan_auction_signal()` pool 우선 읽기 + fallback 추가 | 중 |
| `strategy_10_new_high.py` | `scan_new_high_swing()` pool 우선 읽기 + fallback 추가 | 중 |
| `strategy_11_frgn_cont.py` | `scan_frgn_cont_swing()` pool 우선 읽기 + fallback 추가 | 소 |

### 신규 파일 없음 (단계 1)

단계 1은 기존 Java 인프라를 유지하고 Python strategy 파일만 수정.  
`candidates_builder.py` 신규 생성은 단계 2(이관서 참조)에서 진행.

---

## 6. 수정 후 각 전략 흐름

```
S4  [수정 후]
  Java preloadCandidatePools() 09:05~  → ka10027 (2~20%) → candidates:s4:001/101
  strategy_runner.py S4 블록          → lrange s4:001/101 → check_big_candle 순차

S7  [수정 후]
  Java startPreMarketSubscription() 07:30 → ka10029 (2~10%) → candidates:s7:001/101
  strategy_runner.py S7 블록              → scan_auction_signal(token, market, rdb)
  scan_auction_signal()                   → lrange s7:{market} 우선
                                            → 없으면 ka10029 직접 (fallback)
                                            → ws:hoga 체크 → 결과

S10 [수정 후]
  Java preloadCandidatePools() 09:05~  → ka10016 → candidates:s10:001/101
  strategy_runner.py S10 블록          → scan_new_high_swing(token, "000", rdb)
  scan_new_high_swing()                → lrange s10:001 + s10:101 우선
                                         → 있으면 ka10023만 추가 호출 (ka10016 생략)
                                         → 없으면 ka10016+ka10023 전수 조회 (fallback)

S11 [수정 후]
  Java preloadCandidatePools() 09:05~  → ka10035 → candidates:s11:001/101
  strategy_runner.py S11 블록          → scan_frgn_cont_swing(token, market, rdb)
  scan_frgn_cont_swing()               → lrange s11:{market} 우선
                                         → 있으면 ka10035 전수 후 pool 교집합 필터
                                         → 없으면 ka10035 전수 조회 (fallback)
```

---

## 7. 검증 방법

### 7-1. Redis 키 확인

```bash
# 수정 후 Redis CLI에서 아래 키들이 존재해야 함
KEYS candidates:s*
LLEN candidates:s4:001
LLEN candidates:s4:101
LRANGE candidates:s4:001 0 4   # 종목코드 5개 샘플
LRANGE candidates:s7:001 0 4
LRANGE candidates:s10:001 0 4
LRANGE candidates:s11:001 0 4
```

### 7-2. strategy_runner 로그 확인

```
# 수정 전 (S4 비동작)
[Runner] S4 스캔 오류: ... (또는 아무 로그 없음)

# 수정 후 정상
[S7] candidates:s7:001 풀 사용 (87개)
[S10] candidates:s10:* 풀 사용 (43개)
[S11] candidates:s11:001 풀 사용 (23개)
[Runner] 신호 발행 [S4_BIG_CANDLE] stk=XXXXXX score=...
```

### 7-3. S4 전략 단독 테스트

```python
# Python REPL에서
import asyncio, redis.asyncio as aioredis
rdb = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
codes = await rdb.lrange("candidates:s4:001", 0, 9)
print(codes)  # 빈 리스트면 Java 수정 미적용
```

---

## 8. 우선순위 및 작업 순서

| 순서 | 작업 | 파일 | 긴급도 | 예상 공수 |
|------|------|------|--------|---------|
| 1 | `CandidateService.getS4Candidates()` 추가 | Java | 🔴 긴급 | 30분 |
| 2 | `TradingScheduler.preloadCandidatePools()` S4 호출 추가 | Java | 🔴 긴급 | 5분 |
| 3 | `strategy_7_auction.py` 풀 우선 읽기 | Python | 🟠 높음 | 30분 |
| 4 | `strategy_11_frgn_cont.py` 풀 우선 읽기 | Python | 🟠 높음 | 20분 |
| 5 | `strategy_10_new_high.py` 풀 우선 읽기 | Python | 🟡 중간 | 40분 |
| 6 | 검증 및 로그 확인 | — | — | 20분 |
| 7 | (단계 2) `candidates_builder.py` 신규 생성 | Python | 🟢 낮음 | 3~4시간 |
| 8 | (단계 2) Java preloadCandidatePools 비활성화 | Java | 🟢 낮음 | 10분 |

---

## 9. 주의 사항

### TTL 충돌 주의 (단계 2 이관 시)
Java와 Python이 동시에 같은 Redis 키에 LPUSH할 경우 목록이 중복 누적된다.
단계 2 이관 시에는 반드시 **Java preloadCandidatePools 비활성화 → Python candidates_builder 활성화** 순서로 진행.

### S4 등락률 범위 선택 근거
`ka10027 sort_tp=1(상승률), 2~20%`
- 2% 미만: 장대양봉 판별 어려움
- 20% 초과: 상한가 인접 → 진입 리스크 과다
- 기존 S8(0.5~8%)보다 넓은 범위가 S4 추격매수 성격에 적합

### S10 풀 기반 경로의 flu_rt 처리
Java 풀(`candidates:s10:*`)은 종목코드만 저장하며 등락률은 없다.
풀 기반 경로에서는 `ws:tick:{stk_cd}`에서 `flu_rt`를 보완하고,
tick이 없는 종목은 `flu_rt=0`으로 처리되어 `2.0 <= flu_rt <= 15.0` 조건에서 탈락한다.
→ 타이트한 종목 선별 기준이 자연스럽게 유지됨.
