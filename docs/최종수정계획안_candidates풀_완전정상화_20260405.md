# 최종 수정계획안 — candidates:s{N}:001/101 완전정상화 & Python 단독 WebSocket

**작성일**: 2026-04-05  
**작성자**: Claude Sonnet 4.6  
**참고 문서**:
- `docs/작업이관서_candidates풀_Python이관_20260405.md`
- `docs/수정계획안_candidates풀_정상화_20260405.md`
- `docs/api/ka10054.md` (VI 발동종목요청), `docs/api/ka10065.md` (장중투자자별매매상위)
- `docs/api/ka90001.md`, `docs/api/ka90003.md`

**핵심 원칙**:
1. `candidates:s{N}:001` 과 `candidates:s{N}:101` 이 **S1~S15 전략 전부** 에 대해 Redis에 존재해야 한다.
2. WebSocket은 **Python websocket-listener 단독** 운영이며, Java WS 코드는 완전 비활성화 상태를 유지한다.
3. candidates 풀 적재는 `ai-engine/candidates_builder.py` 단독 담당이다 (Java `CandidateService` 이관 완료 목표).

---

## 1. 현황 분석 (2026-04-05 기준)

### 1-1. candidates_builder.py 구현 현황

`candidates_builder.py` 가 이미 생성되어 engine.py에서 `asyncio.create_task(run_candidate_builder(rdb))` 로 기동 중.

| 전략 | 풀 키 | builder 구현 | API | 상태 |
|------|-------|------------|-----|------|
| **S1** | `s1:{mkt}` | ✅ `_build_s1()` | ka10029 | **완료** |
| **S2** | 없음 | ❌ 미구현 | — | **🔴 풀 없음** |
| **S3** | 없음 | ❌ 미구현 | — | **🔴 풀 없음** |
| **S4** | `s4:{mkt}` | ✅ `_build_s4()` | ka10027 | **완료** |
| **S5** | 없음 | ❌ 미구현 | — | **🔴 풀 없음** |
| **S6** | 없음 | ❌ 미구현 | — | **🔴 풀 없음** |
| **S7** | `s7:{mkt}` | ✅ `_build_s7()` | ka10029 | **완료** |
| **S8** | `s8:{mkt}` | ✅ `_build_s8()` | ka10027 | **완료** |
| **S9** | `s9:{mkt}` | ✅ `_build_s9()` | ka10027 | **완료** |
| **S10** | `s10:{mkt}` | ✅ `_build_s10()` | ka10016 | **완료** |
| **S11** | `s11:{mkt}` | ✅ `_build_s11()` | ka10035 | **완료** |
| **S12** | `s12:{mkt}` | ✅ `_build_s12()` | ka10032 | **완료** |
| **S13** | `s13:{mkt}` | ✅ `_build_s13()` | s8+s10 합산 | **완료** |
| **S14** | `s14:{mkt}` | ✅ `_build_s14()` | ka10027 | **완료** |
| **S15** | `s15:{mkt}` | ✅ `_build_s15()` | s8 재활용 | **완료** |

### 1-2. strategy 파일별 풀 사용 현황

| 전략 | strategy 파일 | 풀 읽기 여부 | 문제 |
|------|-------------|------------|------|
| S1 | strategy_1_gap_opening.py | ✅ runner에서 lrange 후 전달 | — |
| S2 | strategy_2_vi_pullback.py | ❌ vi_watch_queue 이벤트만 | 풀 자체 없음 |
| S3 | strategy_3_inst_foreign.py | ❌ ka10063 직접 조회 | 풀 없음 + pool 무시 |
| S4 | strategy_4_big_candle.py | ✅ runner에서 lrange 후 전달 | — |
| S5 | strategy_5_program_buy.py | ❌ ka90003 직접 조회 | 풀 없음 + pool 무시 |
| S6 | strategy_6_theme.py | ❌ ka90001 직접 조회 | 풀 없음 + pool 무시 |
| S7 | strategy_7_auction.py | ❌ ka10029 직접 조회 | pool 무시 |
| S8 | strategy_8_golden_cross.py | ✅ (내부 lrange) | — |
| S9 | strategy_9_pullback.py | ✅ (내부 lrange) | — |
| S10 | strategy_10_new_high.py | ❌ ka10016 직접 조회 | pool 무시 |
| S11 | strategy_11_frgn_cont.py | ❌ ka10035 직접 조회 | pool 무시 |
| S12 | strategy_12_closing.py | ⚠️ ka10027+ka10063 직접 조회 | 설계 의도 차이 (§4.5 참조) |
| S13 | strategy_13_box_breakout.py | ✅ (내부 lrange s13) | — |
| S14 | strategy_14_oversold_bounce.py | ✅ (내부 lrange s14) | — |
| S15 | strategy_15_momentum_align.py | ✅ (내부 lrange s15) | — |

### 1-3. WebSocket 현황

| 항목 | 상태 |
|------|------|
| `websocket-listener` (Python) | ✅ GRP 1–4 단독 운영 중 |
| Java `KiwoomWebSocketClient` | ✅ 비활성화 (`JAVA_WS_ENABLED=false`) |
| `vi_watch_queue` 적재 | ✅ Python websocket-listener → Redis (1h VI 이벤트) |
| `ws:tick:{stk_cd}` | ✅ Python websocket-listener → Redis (0B tick) |
| `ws:hoga:{stk_cd}` | ✅ Python websocket-listener → Redis (0D 호가) |
| `ws:expected:{stk_cd}` | ✅ Python websocket-listener → Redis (0H 예상체결) |

**WebSocket 구조 변경 없음** — 이미 Python 단독 운영 중.

---

## 2. 수정 목표

```
[목표 상태]
candidates_builder.py (장전 3분/장중 10분 주기)
  ├─ S1  → candidates:s1:001 / candidates:s1:101  (TTL 180s)
  ├─ S2  → candidates:s2:001 / candidates:s2:101  (TTL 300s) ← 신규
  ├─ S3  → candidates:s3:001 / candidates:s3:101  (TTL 600s) ← 신규
  ├─ S4  → candidates:s4:001 / candidates:s4:101  (TTL 300s)
  ├─ S5  → candidates:s5:001 / candidates:s5:101  (TTL 600s) ← 신규
  ├─ S6  → candidates:s6:001 / candidates:s6:101  (TTL 300s) ← 신규
  ├─ S7  → candidates:s7:001 / candidates:s7:101  (TTL 180s)
  ├─ S8  → candidates:s8:001 / candidates:s8:101  (TTL 1200s)
  ├─ S9  → candidates:s9:001 / candidates:s9:101  (TTL 1200s)
  ├─ S10 → candidates:s10:001 / candidates:s10:101 (TTL 1200s)
  ├─ S11 → candidates:s11:001 / candidates:s11:101 (TTL 1800s)
  ├─ S12 → candidates:s12:001 / candidates:s12:101 (TTL 600s)
  ├─ S13 → candidates:s13:001 / candidates:s13:101 (TTL 1200s)
  ├─ S14 → candidates:s14:001 / candidates:s14:101 (TTL 1200s)
  └─ S15 → candidates:s15:001 / candidates:s15:101 (TTL 1200s)

strategy_runner.py & strategy_*.py
  → 모든 전략이 lrange candidates:s{N}:{market} 우선 읽기
  → 풀 없을 때만 직접 API 호출 (fallback)
```

---

## 3. candidates_builder.py 신규 구현 (S2/S3/S5/S6)

### 3-1. S2 — VI 발동 종목 풀 (신규)

**API**: `ka10054` 변동성완화장치발동종목요청 (`POST /api/dostk/stkinfo`)

```
목적 : vi_watch_queue 이벤트가 누락된 경우 보완 + 최초 기동 시 풀 사전 적재
파라미터:
  mrkt_tp   = {market}
  bf_mkrt_tp = "1"       (정규시장)
  stk_cd    = ""         (전종목)
  motn_tp   = "2"        (동적VI 우선, 0=전체 가능)
  skip_stk  = "000000000"
  trde_qty_tp = "0"
  motn_drc  = "1"        (상승 방향만 — 매수 기회)
  stex_tp   = "3"        (통합)
필터  : open_pric_pre_flu_rt (시가대비등락률) > 0 — 양전 VI 종목만
Redis 키: candidates:s2:{market}
TTL  : 300초 (5분) — VI 상태는 빠르게 변함
상한 : 50개
```

**구현 코드 (`candidates_builder.py` 에 추가)**:

```python
async def _build_s2(token: str, market: str, rdb) -> None:
    """S2 VI 발동 종목: ka10054, 동적VI 상승, TTL 300s, 50개"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka10054",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "mrkt_tp": market,
                "bf_mkrt_tp": "1",
                "stk_cd": "",
                "motn_tp": "0",          # 전체 (정적+동적)
                "skip_stk": "000000000",
                "trde_qty_tp": "0",
                "min_trde_qty": "0",
                "max_trde_qty": "0",
                "trde_prica_tp": "0",
                "min_trde_prica": "0",
                "max_trde_prica": "0",
                "motn_drc": "1",         # 상승 방향
                "stex_tp": "3",          # 통합
            },
        )
    resp.raise_for_status()
    data = resp.json()
    if not validate_kiwoom_response(data, "ka10054", logger):
        return

    items = data.get("motn_stk", [])
    codes = []
    for x in items:
        stk_cd = x.get("stk_cd", "")
        # 시가대비등락률 양전 (VI 발동 후 상승 유지 중인 종목)
        try:
            open_flu = _clean(x.get("open_pric_pre_flu_rt", "0"))
        except Exception:
            open_flu = 0.0
        if stk_cd and open_flu > 0:
            codes.append(stk_cd)
        if len(codes) >= 50:
            break

    await _lpush_with_ttl(rdb, f"candidates:s2:{market}", codes, 300)
```

**S2 전략 파일 수정 방향** (`strategy_2_vi_pullback.py`):
- vi_watch_queue 이벤트 처리가 기본 동작 → **변경 없음**
- `check_vi_pullback()` 에 최초 진입 시 `candidates:s2:{market}` 풀 병렬 참조 추가 (폴백 아님, 보완):
  ```python
  # vi_watch_queue 이벤트가 없거나 오래된 경우 builder 풀에서 보완
  supplemental = await rdb.lrange(f"candidates:s2:{market}", 0, -1)
  ```

---

### 3-2. S3 — 기관/외인 동시 순매수 풀 (신규)

**API**: `ka10065` 장중투자자별매매상위요청 (`POST /api/dostk/rkinfo`)

```
목적 : 외인 + 기관계 동시 순매수 종목 사전 적재
방법 : 외인(orgn_tp=9000) 순매수 상위 + 기관계(orgn_tp=9999) 순매수 상위 교집합
파라미터(2회 호출):
  trde_tp = "1"           (순매수)
  mrkt_tp = {market}
  orgn_tp = "9000"        (1차: 외인)
          = "9999"        (2차: 기관계)
필터  : 두 결과의 교집합 종목 (외인 AND 기관 동시 순매수)
Redis 키: candidates:s3:{market}
TTL  : 600초 (10분)
상한 : 100개
```

**구현 코드**:

```python
async def _fetch_ka10065(token: str, market: str, orgn_tp: str) -> set[str]:
    """ka10065 장중투자자별매매상위 종목코드 세트 반환"""
    codes = set()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={
                "api-id": "ka10065",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={"trde_tp": "1", "mrkt_tp": market, "orgn_tp": orgn_tp},
        )
    resp.raise_for_status()
    data = resp.json()
    if not validate_kiwoom_response(data, "ka10065", logger):
        return codes
    for x in data.get("opmr_invsr_trde_upper", []):
        stk_cd = x.get("stk_cd", "")
        if stk_cd:
            codes.add(stk_cd)
    return codes


async def _build_s3(token: str, market: str, rdb) -> None:
    """S3 기관+외인 동시 순매수: ka10065 교집합, TTL 600s, 100개"""
    frgn_set, inst_set = await asyncio.gather(
        _fetch_ka10065(token, market, "9000"),   # 외인
        _fetch_ka10065(token, market, "9999"),   # 기관계
    )
    # 두 집합의 교집합만 후보
    codes = list(frgn_set & inst_set)[:100]
    await _lpush_with_ttl(rdb, f"candidates:s3:{market}", codes, 600)
```

**S3 전략 파일 수정 방향** (`strategy_3_inst_foreign.py`):
- `scan_inst_foreign()` 앞부분에 pool 우선 읽기 추가:
  ```python
  pool = await rdb.lrange(f"candidates:s3:{market}", 0, -1)
  if pool:
      # 풀 종목에 대해 ka10063 세부 조건 검증만 수행
      pool_set = set(pool)
      raw_items = [it for it in raw_items if it.get("stk_cd") in pool_set]
  else:
      # fallback: ka10063 전수 조회
      raw_items = await fetch_intraday_investor(token, market)
  ```

---

### 3-3. S5 — 프로그램 순매수 풀 (신규)

**API**: `ka90003` 프로그램순매수상위 (`POST /api/dostk/stkinfo`)

```
목적 : 프로그램 순매수 상위 종목 사전 적재
파라미터:
  trde_upper_tp = "2"   (순매수상위)
  amt_qty_tp    = "1"   (금액)
  mrkt_tp = P00101(KOSPI) / P10102(KOSDAQ)
  stex_tp = "1"
필터  : netprps_amt (순매수금액) > 0
Redis 키: candidates:s5:{market}
TTL  : 600초 (10분) — 프로그램 순매수는 실시간성 높음
상한 : 100개
```

**구현 코드**:

```python
_MRKT_MAP = {"001": "P00101", "101": "P10102"}

async def _build_s5(token: str, market: str, rdb) -> None:
    """S5 프로그램순매수: ka90003, TTL 600s, 100개"""
    kiwoom_mkt = _MRKT_MAP.get(market, "P00101")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka90003",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "trde_upper_tp": "2",
                "amt_qty_tp": "1",
                "mrkt_tp": kiwoom_mkt,
                "stex_tp": "1",
            },
        )
    resp.raise_for_status()
    data = resp.json()
    if not validate_kiwoom_response(data, "ka90003", logger):
        return

    codes = []
    for x in data.get("pgm_trde_upper", []):
        stk_cd = x.get("stk_cd", "")
        try:
            net = _clean(x.get("netprps_amt", "0"))
        except Exception:
            net = 0.0
        if stk_cd and net > 0:
            codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s5:{market}", codes, 600)
```

**S5 전략 파일 수정 방향** (`strategy_5_program_buy.py`):
- `scan_program_buy()` 앞부분 pool 우선 읽기:
  ```python
  pool = await rdb.lrange(f"candidates:s5:{market}", 0, -1)
  if pool:
      pool_set = set(pool)
      # ka90003 결과를 pool로 필터
      raw = {cd: info for cd, info in raw.items() if cd in pool_set}
  else:
      raw = await fetch_program_netbuy(token, market)
  ```

---

### 3-4. S6 — 테마 구성종목 풀 (신규)

**API**: `ka90001` 테마그룹별수익률 → `ka90002` 테마구성종목 (2단계 조회)

```
목적 : 당일 상위 테마(1~5위)의 구성종목 사전 적재
방법 : 
  1단계: ka90001 → 당일 등락률 상위 5개 테마 코드 추출
  2단계: 각 테마별 ka90002 → 구성종목 코드 수집
필터  : flu_rt < 5.0% (이미 많이 오른 테마 선도주 제외)
Redis 키: candidates:s6:{market}  
  ※ S6는 시장 구분 없이 테마 단위 동작하므로 001과 101에 동일 내용 저장
TTL  : 300초 (5분) — 테마 모멘텀은 빠르게 변함
상한 : 150개 (상위 5 테마 × 30종목)
```

**구현 코드**:

```python
async def _build_s6(token: str, rdb) -> None:
    """S6 테마 구성종목: ka90001→ka90002, TTL 300s, 150개"""
    # 1단계: 상위 5개 테마 추출
    theme_codes = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/thme",
            headers={
                "api-id": "ka90001",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "qry_tp": "1",
                "date_tp": "1",
                "flu_pl_amt_tp": "3",   # 등락률 상위
                "stex_tp": "1",
            },
        )
    resp.raise_for_status()
    data = resp.json()
    if validate_kiwoom_response(data, "ka90001", logger):
        for grp in data.get("thme_prft_rt", [])[:5]:
            tc = grp.get("thme_cd") or grp.get("thme_grp_cd", "")
            if tc:
                theme_codes.append(tc)

    if not theme_codes:
        return

    # 2단계: 각 테마 구성종목 수집
    all_codes: list[str] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=10.0) as client:
        for tc in theme_codes:
            await asyncio.sleep(_API_INTERVAL)
            resp2 = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/thme",
                headers={
                    "api-id": "ka90002",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"thme_grp_cd": tc, "stex_tp": "1"},
            )
            data2 = resp2.json()
            if not validate_kiwoom_response(data2, "ka90002", logger):
                continue
            for x in data2.get("thme_stk", []):
                stk_cd = x.get("stk_cd", "")
                if not stk_cd or stk_cd in seen:
                    continue
                try:
                    flu_rt = _clean(x.get("flu_rt", "0"))
                except Exception:
                    flu_rt = 0.0
                # 이미 많이 오른 선도주 제외 (5% 이상 상승 종목)
                if flu_rt < 5.0:
                    all_codes.append(stk_cd)
                    seen.add(stk_cd)
            if len(all_codes) >= 150:
                break

    codes = all_codes[:150]
    # S6는 시장 구분 없이 동일 풀 사용
    for market in MARKETS:
        await _lpush_with_ttl(rdb, f"candidates:s6:{market}", codes, 300)
```

**S6 전략 파일 수정 방향** (`strategy_6_theme.py`):
- `scan_theme_laggard()` 앞부분 pool 우선 읽기:
  ```python
  # S6는 "000" 또는 특정 market으로 호출될 수 있음
  pool = await rdb.lrange("candidates:s6:001", 0, -1)  # 시장 무관 동일 풀
  if pool:
      pool_set = set(pool)
      # ka90002 구성종목 결과를 pool로 필터
  else:
      # fallback: ka90001→ka90002 직접 조회
      theme_groups = await fetch_theme_groups(token)
  ```

---

## 4. strategy 파일 수정 (pool 우선 읽기 추가)

### 4-1. S7 — strategy_7_auction.py

**현재 문제**: `scan_auction_signal()` 이 `candidates:s7:{market}` 풀을 무시하고 ka10029 직접 호출.

**수정 명세** (`scan_auction_signal()` 첫 블록 교체):

```python
async def scan_auction_signal(token: str, market: str = "000", rdb=None) -> list:
    # 1. candidates:s7:{market} 풀 우선 사용
    gap_candidates: dict = {}
    if rdb:
        try:
            pool = await rdb.lrange(f"candidates:s7:{market}", 0, -1)
            if pool:
                for i, stk_cd in enumerate(pool):
                    gap_candidates[stk_cd] = {"rank": i + 1, "gap_rt": 5.0}
                logger.debug("[S7] candidates:s7:%s 풀 사용 (%d개)", market, len(pool))
        except Exception as e:
            logger.debug("[S7] 풀 조회 실패, fallback: %s", e)

    # 풀 없으면 ka10029 직접 조회 (fallback)
    if not gap_candidates:
        logger.debug("[S7] 풀 없음 – ka10029 직접 조회 (fallback)")
        gap_candidates = await fetch_gap_rank(token, market)

    # 이하 기존 로직 동일 (ws:hoga 체크, bid_ratio 계산 등)
    ...
```

### 4-2. S10 — strategy_10_new_high.py

**현재 문제**: `scan_new_high_swing()` 이 ka10016+ka10023 전수 조회.

**수정 명세** (`scan_new_high_swing()` 첫 블록 교체):

```python
async def scan_new_high_swing(token: str, market: str = "000", rdb=None) -> list:
    # 1. candidates:s10:{market} 풀 확인 (market="000"이면 001+101 모두 조회)
    pool_codes: list[str] = []
    if rdb:
        try:
            markets_to_check = ["001", "101"] if market == "000" else [market]
            for mkt in markets_to_check:
                codes = await rdb.lrange(f"candidates:s10:{mkt}", 0, -1)
                pool_codes.extend(codes)
            pool_codes = list(dict.fromkeys(pool_codes))
            if pool_codes:
                logger.debug("[S10] candidates:s10:* 풀 사용 (%d개)", len(pool_codes))
        except Exception as e:
            logger.debug("[S10] 풀 조회 실패: %s", e)

    if pool_codes:
        # 풀 기반 경로: ka10016 생략, ws:tick에서 flu_rt 보완
        vol_surge_map = await fetch_volume_surge_map_all(token, market)
        new_high_items = [{"stk_cd": cd, "flu_rt": "0", "cur_prc": "0", "stk_nm": ""} for cd in pool_codes]
        if rdb:
            for item in new_high_items:
                try:
                    tick = await rdb.hgetall(f"ws:tick:{item['stk_cd']}")
                    if tick:
                        item["flu_rt"]  = tick.get("flu_rt", "0")
                        item["cur_prc"] = tick.get("cur_prc", "0")
                        item["stk_nm"]  = tick.get("stk_nm", "")
                except Exception:
                    pass
    else:
        # fallback: ka10016+ka10023 전수 조회
        logger.debug("[S10] 풀 없음 – ka10016+ka10023 전수 조회")
        new_high_items, vol_surge_map = await asyncio.gather(
            fetch_new_high_stocks_all(token, market),
            fetch_volume_surge_map_all(token, market),
        )
    # 이하 기존 필터링 로직 동일
    ...
```

### 4-3. S11 — strategy_11_frgn_cont.py

**현재 문제**: `scan_frgn_cont_swing()` 이 ka10035 직접 조회.

**수정 명세** (`scan_frgn_cont_swing()` 첫 블록 교체):

```python
async def scan_frgn_cont_swing(token: str, market: str = "000", rdb=None) -> list:
    # 1. candidates:s11:{market} 풀 우선 확인
    pool_codes: list[str] = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s11:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S11] candidates:s11:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S11] 풀 조회 실패: %s", e)

    if pool_codes:
        raw_items = await fetch_frgn_cont_buy(token, market, max_pages=2)
        pool_set = set(pool_codes)
        raw_items = [it for it in raw_items if it.get("stk_cd") in pool_set]
    else:
        logger.debug("[S11] 풀 없음 – ka10035 전수 조회")
        raw_items = await fetch_frgn_cont_buy(token, market, max_pages=2)
    # 이하 기존 필터링 로직 동일
    ...
```

### 4-4. S3 — strategy_3_inst_foreign.py

**수정 명세** (`scan_inst_foreign()` 첫 블록에 pool 우선 읽기):

```python
async def scan_inst_foreign(token: str, market: str = "000", rdb=None) -> list:
    pool_codes: list[str] = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s3:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S3] candidates:s3:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S3] 풀 조회 실패: %s", e)

    raw_items = await fetch_intraday_investor(token, market)
    if pool_codes:
        pool_set = set(pool_codes)
        raw_items = [it for it in raw_items if it.get("stk_cd") in pool_set]
    # 이하 기존 필터링 로직 동일
    ...
```

### 4-5. S5 — strategy_5_program_buy.py

**수정 명세** (`scan_program_buy()` 첫 블록에 pool 우선 읽기):

```python
async def scan_program_buy(token: str, market: str, rdb=None) -> list:
    pool_codes: list[str] = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s5:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S5] candidates:s5:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S5] 풀 조회 실패: %s", e)

    raw = await fetch_program_netbuy(token, market)
    if pool_codes:
        pool_set = set(pool_codes)
        raw = {cd: info for cd, info in raw.items() if cd in pool_set}
    # 이하 기존 필터링 로직 동일
    ...
```

### 4-6. S6 — strategy_6_theme.py

**수정 명세** (`scan_theme_laggard()` 첫 블록에 pool 우선 읽기):

```python
async def scan_theme_laggard(token: str, rdb=None) -> list:
    pool_codes: list[str] = []
    if rdb:
        try:
            # S6 풀은 시장 구분 없이 001로 저장
            pool_codes = await rdb.lrange("candidates:s6:001", 0, -1)
            if pool_codes:
                logger.debug("[S6] candidates:s6:001 풀 사용 (%d개)", len(pool_codes))
        except Exception as e:
            logger.debug("[S6] 풀 조회 실패: %s", e)

    if pool_codes:
        pool_set = set(pool_codes)
        # 풀 종목 대상으로 체결강도/거래량 확인만 수행 (ka90001→ka90002 생략)
        results = []
        for stk_cd in pool_codes[:50]:  # 상위 50개만 세부 검증
            await asyncio.sleep(_API_INTERVAL)
            cntr_str = await fetch_cntr_strength(token, stk_cd)
            if cntr_str >= 120.0:
                stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
                results.append({...})
        return sorted(results, key=lambda x: x.get("cntr_str", 0), reverse=True)[:5]
    else:
        # fallback: 기존 ka90001→ka90002 전수 조회
        theme_groups = await fetch_theme_groups(token)
        ...
```

### 4-7. S2 — strategy_2_vi_pullback.py (보완적 수정)

S2는 vi_watch_queue 이벤트 기반 동작이 핵심. candidates:s2:* 풀은 **이벤트 누락 보완** 목적:

```python
# vi_watch_worker.py 또는 run_vi_watch_worker() 에서 candidates:s2:* 풀도 체크:
# vi_watch_queue가 비어있을 때 candidates:s2:{market} 에서 종목 목록을 가져와
# 해당 종목들의 현재 VI 상태를 ka10054로 재확인 후 처리
```

> **현재 S2는 이벤트 기반 구조를 유지**한다. `candidates:s2:{market}` 풀은 vi_watch_worker가 보완적으로 활용하며, vi_watch_queue 이벤트가 정상 수신되고 있다면 S2 동작에는 영향 없음.

---

## 5. candidates_builder.py 스케줄 수정

### 5-1. _build_pre_market() 수정

```python
async def _build_pre_market(token: str, rdb) -> None:
    """장전 배치: S1, S2(VI 미발동 상태여도 적재), S7"""
    for market in MARKETS:
        try:
            await _build_s1(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s7(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s2(token, market, rdb)   # ← 신규 추가
            await asyncio.sleep(_API_INTERVAL)
        except Exception as e:
            logger.error("[builder] 장전 %s 빌드 오류: %s", market, e)
```

### 5-2. _build_intraday() 수정

```python
async def _build_intraday(token: str, rdb) -> None:
    """장중 배치: 전 전략 풀 갱신"""
    for market in MARKETS:
        try:
            await _build_s2(token, market, rdb)   # ← 신규
            await asyncio.sleep(_API_INTERVAL)
            await _build_s3(token, market, rdb)   # ← 신규
            await asyncio.sleep(_API_INTERVAL)
            await _build_s4(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s5(token, market, rdb)   # ← 신규
            await asyncio.sleep(_API_INTERVAL)
            await _build_s8(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s9(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s10(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s11(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s12(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s14(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s13(market, rdb)
            await _build_s15(market, rdb)
        except Exception as e:
            logger.error("[builder] 장중 %s 빌드 오류: %s", market, e)

    # S6: 시장 무관, KOSPI/KOSDAQ 루프 외부에서 1회 호출
    try:
        await _build_s6(token, rdb)               # ← 신규
    except Exception as e:
        logger.error("[builder] S6 빌드 오류: %s", e)
```

---

## 6. Java 이관 완료 계획

### 6-1. 현재 Java 상태

| 코드 | 상태 | 조치 |
|------|------|------|
| `CandidateService.getS{N}Candidates()` | 동작 중 (S1/S7~S15) | Python 안정화 후 비활성화 |
| `TradingScheduler.preloadCandidatePools()` | 동작 중 | Python 안정화 후 삭제 |
| `TradingScheduler.startPreMarketSubscription()` | 동작 중 | Python 안정화 후 삭제 |
| `KiwoomWebSocketClient` | ❌ 비활성화 (`JAVA_WS_ENABLED=false`) | 유지 (설정값으로 비활성) |
| `TokenService`, `TokenRefreshScheduler` | 동작 중 | **유지** (토큰은 Java 담당) |
| `ForceCloseScheduler`, `DataCleanupScheduler` | 동작 중 | **유지** |

### 6-2. 비활성화 순서 (Python 안정화 확인 후)

```
1. Python candidates_builder 모든 전략 풀 적재 확인 (Redis CLI)
2. Java TradingScheduler.preloadCandidatePools() 비활성화
   → TTL 만료 후 자연스럽게 Python 풀로 대체
3. Java TradingScheduler.startPreMarketSubscription() 비활성화
4. (나중에) Java CandidateService.getS{N}Candidates() 메서드 삭제
```

> **주의**: Java와 Python이 동시에 같은 키에 쓰면 LPUSH 중복 누적 발생.  
> **반드시 Java 먼저 비활성화 → Python 단독 적재** 순서로 전환.

---

## 7. 전략별 최종 데이터 흐름

```
전략  풀 적재 (candidates_builder.py)      전략 실행 (strategy_runner.py + strategy_*.py)
──── ───────────────────────────────────  ──────────────────────────────────────────────
S1   ka10029 (3~15%) → s1:001/101 180s   runner lrange → scan_gap_opening()
S2   ka10054 (동적VI 상승) → s2:001/101 300s  vi_watch_worker 이벤트 우선, 풀 보완
S3   ka10065 외인∩기관 → s3:001/101 600s  scan_inst_foreign() 풀 우선 → ka10063 세부 확인
S4   ka10027 (2~20% ws강도 우선) → s4:001/101 300s  runner lrange → check_big_candle()
S5   ka90003 순매수상위 → s5:001/101 600s  scan_program_buy() 풀 우선 → fallback
S6   ka90001→ka90002 상위5테마 → s6:001/101 300s  scan_theme_laggard() 풀 우선 → fallback
S7   ka10029 (2~10%) → s7:001/101 180s   scan_auction_signal() 풀 우선 → fallback
S8   ka10027 (0.5~8%) → s8:001/101 1200s scan_golden_cross() 풀 우선
S9   ka10027 (0.3~5%) → s9:001/101 1200s scan_pullback_swing() 풀 우선
S10  ka10016 신고가 → s10:001/101 1200s  scan_new_high_swing() 풀 우선 → fallback
S11  ka10035 외인연속 → s11:001/101 1800s scan_frgn_cont_swing() 풀 우선 → fallback
S12  ka10032 거래대금 → s12:001/101 600s  scan_closing_buy() (독립 동작, §8 참조)
S13  s8∪s10 합산 → s13:001/101 1200s    scan_box_breakout() lrange s13
S14  ka10027 하락률 → s14:001/101 1200s  scan_oversold_bounce() lrange s14
S15  s8 재활용 → s15:001/101 1200s       scan_momentum_align() lrange s15

WebSocket (Python websocket-listener 단독)
  0B tick → ws:tick:{stk_cd}
  0D hoga → ws:hoga:{stk_cd}
  0H expected → ws:expected:{stk_cd}
  1h VI → vi_watch_queue → S2 이벤트 처리
```

---

## 8. S12 설계 의도 유지

S12 Python(`scan_closing_buy`)은 `ka10027 + ka10063`(등락률+기관수급 교차) 기준으로 동작.  
`candidates:s12:*` 풀은 `ka10032`(거래대금 상위) 기준으로 적재.  
두 기준은 **의도적으로 다른 필터** 이며 버그가 아님.

> S12는 풀 기반 필터 없이 독립 직접 조회로 유지한다.  
> 단, `candidates:s12:001/101` 은 존재는 해야 하므로 builder에서 ka10032로 계속 적재.

---

## 9. 수정 파일 목록 요약

### candidates_builder.py (기존 파일 수정)

| 추가 함수 | 내용 |
|----------|------|
| `_fetch_ka10054()` | ka10054 VI 발동종목 조회 |
| `_build_s2()` | S2 풀 적재 (ka10054) |
| `_fetch_ka10065()` | ka10065 장중투자자별매매상위 |
| `_build_s3()` | S3 풀 적재 (ka10065 교집합) |
| `_build_s5()` | S5 풀 적재 (ka90003) |
| `_build_s6()` | S6 풀 적재 (ka90001→ka90002) |
| `_MRKT_MAP` | ka90003용 시장코드 상수 (이미 있으면 재사용) |
| `_build_pre_market()` | S2 추가 |
| `_build_intraday()` | S2/S3/S5/S6 추가 |

### strategy 파일 수정

| 파일 | 수정 내용 |
|------|---------|
| `strategy_7_auction.py` | `scan_auction_signal()` pool 우선 읽기 + fallback |
| `strategy_10_new_high.py` | `scan_new_high_swing()` pool 우선 읽기 + fallback |
| `strategy_11_frgn_cont.py` | `scan_frgn_cont_swing()` pool 우선 읽기 + fallback |
| `strategy_3_inst_foreign.py` | `scan_inst_foreign()` pool 우선 읽기 + fallback |
| `strategy_5_program_buy.py` | `scan_program_buy()` pool 우선 읽기 + fallback |
| `strategy_6_theme.py` | `scan_theme_laggard()` pool 우선 읽기 + fallback |
| `strategy_2_vi_pullback.py` | candidates:s2:* 풀 보완 읽기 (vi_watch_queue 유지) |

---

## 10. 작업 우선순위

| 순서 | 작업 | 파일 | 긴급도 |
|------|------|------|--------|
| 1 | `_build_s2()` 구현 (ka10054) | candidates_builder.py | 🔴 긴급 |
| 2 | `_build_s3()` 구현 (ka10065 교집합) | candidates_builder.py | 🔴 긴급 |
| 3 | `_build_s5()` 구현 (ka90003) | candidates_builder.py | 🔴 긴급 |
| 4 | `_build_s6()` 구현 (ka90001→ka90002) | candidates_builder.py | 🔴 긴급 |
| 5 | `_build_pre_market()` / `_build_intraday()` 에 S2/S3/S5/S6 추가 | candidates_builder.py | 🔴 긴급 |
| 6 | `strategy_7_auction.py` pool 우선 읽기 | strategy_7_auction.py | 🟠 높음 |
| 7 | `strategy_10_new_high.py` pool 우선 읽기 | strategy_10_new_high.py | 🟠 높음 |
| 8 | `strategy_11_frgn_cont.py` pool 우선 읽기 | strategy_11_frgn_cont.py | 🟠 높음 |
| 9 | `strategy_3_inst_foreign.py` pool 우선 읽기 | strategy_3_inst_foreign.py | 🟠 높음 |
| 10 | `strategy_5_program_buy.py` pool 우선 읽기 | strategy_5_program_buy.py | 🟡 중간 |
| 11 | `strategy_6_theme.py` pool 우선 읽기 | strategy_6_theme.py | 🟡 중간 |
| 12 | Redis 키 존재 검증 (전체 S1~S15) | — | 🟡 중간 |
| 13 | Java preloadCandidatePools() 비활성화 | Java | 🟢 낮음 |

---

## 11. 검증 방법

### 11-1. Redis 키 존재 확인 (전체 30개 키)

```bash
redis-cli KEYS "candidates:s*"
# 예상 출력 (30개):
# candidates:s1:001  candidates:s1:101
# candidates:s2:001  candidates:s2:101
# candidates:s3:001  candidates:s3:101
# ... (S4~S15까지 각 :001 / :101 쌍)

# 각 풀 크기 확인
for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  echo -n "S${n}:001 = "; redis-cli LLEN candidates:s${n}:001
  echo -n "S${n}:101 = "; redis-cli LLEN candidates:s${n}:101
done
```

### 11-2. 비어있으면 안 되는 키

장중(09:05~14:50) 기준 아래 키가 비어있으면 해당 전략이 미실행:

| 키 | 정상 LLEN | 관련 전략 |
|---|---|---|
| candidates:s2:001 | 10~50 | S2 (VI 상승 종목) |
| candidates:s3:001 | 20~100 | S3 (외인+기관 순매수) |
| candidates:s5:001 | 20~100 | S5 (프로그램 매수) |
| candidates:s6:001 | 30~150 | S6 (테마 구성종목) |
| candidates:s7:001 | 30~100 | S7 (동시호가) |

### 11-3. strategy_runner 로그 확인

```
# 정상 동작 시
[S3] candidates:s3:001 풀 사용 (42개)
[S5] candidates:s5:001 풀 사용 (67개)
[S6] candidates:s6:001 풀 사용 (120개)
[S7] candidates:s7:001 풀 사용 (88개)
[S10] candidates:s10:* 풀 사용 (51개)
[S11] candidates:s11:001 풀 사용 (23개)
[builder] candidates:s2:001 ← 15종목 (TTL 300s)
```

---

## 12. 주의사항

### API 호출 횟수 증가
S6는 ka90001(1회) + ka90002(테마수×1회) = 최대 6회 추가.  
`_API_INTERVAL`(기본 0.25s) 준수 필수. 장중 전체 빌드 완료 시간은 약 15~20초 예상.

### ka10054 발동종목 특성
ka10054는 **현재 VI 발동 상태인 종목만** 반환한다.  
장 초반(09:00~10:00)에는 빈 경우가 많을 수 있음 → TTL 만료 시 S2 풀이 비어있어도 정상.  
vi_watch_queue 이벤트가 S2의 주 입력이므로 문제 없음.

### S6 pool 시장 구분
테마는 KOSPI/KOSDAQ 경계 없이 구성되므로 `candidates:s6:001` 과 `candidates:s6:101` 에 동일 내용을 저장.  
runner가 market="001"/"101" 로 각각 호출해도 동일 결과를 반환.

### TTL 경쟁 (Java↔Python 과도기)
Java preloadCandidatePools()가 아직 살아있는 경우:
- Java와 Python이 같은 키를 동시에 LPUSH하면 목록 누적 발생
- `_lpush_with_ttl()`은 내부에서 `DELETE → RPUSH → EXPIRE` 순서로 처리하여 중복 방지
- 단, Java의 쓰기 타이밍이 겹치면 DELETE 후 Java가 다시 LPUSH할 수 있음
- **근본 해결**: Java preloadCandidatePools() 조기 비활성화 권장

---

*최종 수정계획안 작성: 2026-04-05 / Claude Sonnet 4.6*
