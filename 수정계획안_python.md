# Python ai-engine 수정계획안

작성일: 2026-04-01
대상: `ai-engine/` 전략 파일 전수점검 결과 (S1~S15, http_utils, ma_utils, indicator_*)

---

## 요약

| 우선순위 | 항목 수 | 영향 범위 |
|---------|--------|---------|
| P1 (치명) | 4건 | API 호출 실패, 데이터 0건 반환 |
| P2 (중요) | 3건 | 에러 무시, 로그 오탐 |
| P3 (개선) | 2건 | 코드 중복, 불필요 파라미터 |

---

## P1 – 즉시 수정 필요 (데이터 수신 실패 직접 원인)

### P1-1. `http_utils.py:51` — ka10046 `stex_tp` 누락

```python
# 현재 (오류)
json={"stk_cd": stk_cd}

# 수정 후
json={"stk_cd": stk_cd, "stex_tp": "1"}
```

**영향 범위**: `fetch_cntr_strength()` 호출처 전체
- `strategy_2_vi_pullback.py` — `from http_utils import fetch_cntr_strength`
- `strategy_6_theme.py` — `from http_utils import fetch_cntr_strength`
- `strategy_10_new_high.py` — `from http_utils import fetch_cntr_strength`

Kiwoom ka10046 스펙: `stex_tp` Required=Y. 누락 시 return_code="1511" 오류 바디를 HTTP 200으로 반환 → `validate_kiwoom_response()`가 감지하더라도 체결강도 100.0 기본값으로 폴백, **필터링이 무력화됨**.

---

### P1-2. `strategy_1_gap_opening.py:36~48` — 로컬 `fetch_cntr_strength` 3중 버그

```python
# 현재 (오류 3가지)
async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    async with httpx.AsyncClient() as client:          # ① timeout 미설정
        resp = await client.post(
            ...,
            json={"stk_cd": stk_cd}                    # ② stex_tp 누락 (P1-1과 동일)
        )
        data = resp.json()                              # ③ raise_for_status/validate 미호출
        strengths = [...]
        return ...
```

| # | 문제 | 결과 |
|---|------|------|
| ① | `httpx.AsyncClient()` — timeout 없음 | 응답 지연 시 무한 블로킹 |
| ② | `stex_tp` 누락 | 1511 에러 바디 무시하고 빈 리스트로 평균 계산 → 100.0 반환 |
| ③ | `raise_for_status()` / `validate_kiwoom_response()` 없음 | HTTP 4xx/5xx 및 200 wrapping 500 모두 무시 |

**수정 방향**: 로컬 함수 삭제 후 `http_utils.fetch_cntr_strength` 임포트로 교체.

```python
# 수정 후 (import 추가)
from http_utils import validate_kiwoom_response, fetch_cntr_strength
```

---

### P1-3. `strategy_3_inst_foreign.py:91~119` — ka10055 `stex_tp` 누락

```python
# 현재 (오류)
json={"stk_cd": stk_cd, "tdy_pred": "1"}   # 당일 요청
json={"stk_cd": stk_cd, "tdy_pred": "2"}   # 전일 요청

# 수정 후
json={"stk_cd": stk_cd, "tdy_pred": "1", "stex_tp": "1"}
json={"stk_cd": stk_cd, "tdy_pred": "2", "stex_tp": "1"}
```

함수: `fetch_volume_compare()`
API: ka10055 당일전일체결량 at `/api/dostk/stkinfo`
`stex_tp` 누락으로 에러 바디 수신, `validate_kiwoom_response()` 는 호출하고 있으나 1511 오류가 항상 발생 → `vol_ratio` 1.0 폴백 → 거래량 필터(≥1.5배) 무력화 → S3 후보가 과다 통과됨.

---

### P1-4. `strategy_5_program_buy.py:58~84` — ka10044/ka10001 `Content-Type` 헤더 누락 + `stex_tp` 누락

```python
# 현재 (오류 — check_extra_conditions 내부)
# ka10044 호출
headers={"api-id": "ka10044", "authorization": f"Bearer {token}"}  # Content-Type 없음
json={"stk_cd": stk_cd}                                              # stex_tp 없음

# ka10001 호출
headers={"api-id": "ka10001", "authorization": f"Bearer {token}"}  # Content-Type 없음
json={"stk_cd": stk_cd}                                              # stex_tp 없음
```

```python
# 수정 후
headers={"api-id": "ka10044", "authorization": f"Bearer {token}",
         "Content-Type": "application/json;charset=UTF-8"}
json={"stk_cd": stk_cd, "stex_tp": "1"}
```

| 문제 | 현상 |
|------|------|
| `Content-Type` 미설정 | httpx 기본값 전송 → Kiwoom 서버 파싱 실패 가능 |
| `stex_tp` 누락 | 1511 에러 바디 → `check_extra_conditions()` 항상 `False` 반환 → S5 후보 전량 탈락 |

---

## P2 – 중요 (오류 무시 / 로그 오탐)

### P2-1. `strategy_10_new_high.py:59` — `validate_kiwoom_response` api_id 오타

```python
# 현재 (오타)
if not validate_kiwoom_response(data, "ka10082", logger):

# 수정 후
if not validate_kiwoom_response(data, "ka10016", logger):
```

함수: `fetch_new_high_stocks()`
API: ka10016 (신고저가요청)
오타로 인해 에러 로그에 `[ka10082]`로 찍혀 실제 오류 발생 시 추적 불가. ka10082는 이 파일에서 사용하지 않는 API ID.

---

### P2-2. `strategy_5_program_buy.py:60~70` — ka10044 응답에 `raise_for_status()` / `validate` 미호출

```python
# 현재 (오류)
dly = await client.post(...)
inst_data = dly.json().get("inst_frgn_trde_tm", [])   # 상태코드/에러바디 체크 없음

info = await client.post(...)
item = info.json().get("stk_info", [{}])[0]            # 상태코드/에러바디 체크 없음
```

```python
# 수정 후
dly = await client.post(...)
dly.raise_for_status()
dly_data = dly.json()
if not validate_kiwoom_response(dly_data, "ka10044", logger):
    return False
inst_data = dly_data.get("inst_frgn_trde_tm", [])
```

HTTP 4xx/5xx나 200 wrapping 에러 바디를 그대로 파싱하다 `KeyError`/`IndexError`로 `except Exception: return False` 처리됨 → 오류 원인 로깅 불가.

---

### P2-3. `strategy_1_gap_opening.py` — `http_utils.fetch_cntr_strength`와 `validate_kiwoom_response` 둘 다 import되어 있지 않음

```python
# 현재 (strategy_1_gap_opening.py 상단)
from http_utils import validate_kiwoom_response

# 수정 후 (P1-2 수정 시 함께 변경)
from http_utils import validate_kiwoom_response, fetch_cntr_strength
```

P1-2와 연계: 로컬 `fetch_cntr_strength` 삭제 후 import 추가 필요.

---

## P3 – 개선 (코드 품질)

### P3-1. `indicator_rsi.py:174~177` — ka10080 요청에 `base_dt` 불필요

```python
# 현재 (불필요 파라미터 포함)
json={
    "stk_cd": stk_cd.strip(),
    "tic_scope": tic_scope,
    "upd_stkpc_tp": "1",
    "base_dt": base_dt,     # ka10080 스펙 상 불필요 (일봉 ka10081 전용)
},

# 수정 후
json={
    "stk_cd": stk_cd.strip(),
    "tic_scope": tic_scope,
    "upd_stkpc_tp": "1",
},
```

`base_dt`는 ka10081 일봉 전용 파라미터. ka10080 분봉 조회 시 포함하면 Kiwoom 서버가 무시하거나 파라미터 수 초과로 오류 가능성 있음 (현재 동작은 하지만 스펙 외 파라미터).

---

### P3-2. `strategy_1_gap_opening.py` — `fetch_cntr_strength` 로컬 정의 중복

`http_utils.py`에 동일 목적의 함수가 있음에도 S1이 독자적으로 정의. P1-2 수정 후 중복 제거로 코드 일관성 확보.

삭제 대상: `strategy_1_gap_opening.py` line 36~48의 `async def fetch_cntr_strength(...)`

---

## 전략별 이상 없는 파일 (정상 확인)

| 파일 | 주요 API | 상태 |
|------|---------|------|
| `strategy_2_vi_pullback.py` | http_utils.fetch_cntr_strength (위임) | 정상 (P1-1 수정 후 해결) |
| `strategy_4_big_candle.py` | ka10080 | 정상 |
| `strategy_6_theme.py` | ka90001, ka90002, http_utils.fetch_cntr_strength | 정상 (P1-1 수정 후 해결) |
| `strategy_7_auction.py` | ka10029 | 정상 |
| `strategy_8_golden_cross.py` | ma_utils (ka10081) | 정상 |
| `strategy_9_pullback.py` | ma_utils (ka10081) | 정상 |
| `strategy_11_frgn_cont.py` | ka10035 | 정상 |
| `strategy_12_closing.py` | ka10027, ka10063 | 정상 |
| `strategy_13_box_breakout.py` | ma_utils (ka10081) | 정상 |
| `strategy_14_oversold_bounce.py` | ma_utils (ka10081) | 정상 |
| `strategy_15_momentum_align.py` | ma_utils (ka10081), indicator_volume | 정상 |
| `ma_utils.py` | ka10081 | 정상 |
| `http_utils.py` | ka10046 | P1-1 수정 필요 |

---

## 수정 순서 권장

1. **`http_utils.py` L51** — `stex_tp` 추가 (P1-1)
   → S2, S6, S10 체결강도 필터 즉시 복구

2. **`strategy_1_gap_opening.py`** — 로컬 함수 삭제 + import 교체 (P1-2 + P3-2)
   → S1 체결강도 필터 복구 + 코드 정리

3. **`strategy_3_inst_foreign.py` L98, L105** — `stex_tp` 추가 (P1-3)
   → S3 거래량 필터 복구

4. **`strategy_5_program_buy.py` L63~83** — Content-Type + stex_tp + validate 추가 (P1-4 + P2-2)
   → S5 extra conditions 복구

5. **`strategy_10_new_high.py` L59** — api_id 오타 수정 (P2-1)
   → 에러 로그 추적성 복구

6. **`indicator_rsi.py` L177** — `base_dt` 제거 (P3-1)
   → 스펙 준수
