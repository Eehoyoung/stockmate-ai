# 스코어 계산 고도화 계획서

> 작성일: 2026-04-04  
> 대상 파일: `ai-engine/scorer.py`, `strategy_*.py`, `http_utils.py`

---

## 목차

1. [현황 요약](#1-현황-요약)
2. [근본 원인 분석](#2-근본-원인-분석)
3. [전략별 현황 및 개선 사항 (S1~S15)](#3-전략별-현황-및-개선-사항-s1s15)
4. [Task별 구현 계획](#4-task별-구현-계획)
5. [수정 파일 목록 및 예상 점수 변화](#5-수정-파일-목록-및-예상-점수-변화)
6. [임계값(CLAUDE_THRESHOLDS) 재설정](#6-임계값claude_thresholds-재설정)
7. [구현 순서 및 의존관계](#7-구현-순서-및-의존관계)

---

## 1. 현황 요약

### 구조

```
strategy_{N}.py  →  telegram_queue (Redis)
                          │
                     queue_worker.py
                          │
                      scorer.py  ←  market_ctx (ws:tick, ws:hoga, ws:strength)
                          │
              score < threshold → CANCEL (Claude 미호출)
              score ≥ threshold → confirm_worker.py (Claude 2차 분석)
```

### 문제

스윙 전략(S8~S15) 신호가 `scorer.py` threshold를 통과하지 못해 대부분 CANCEL 처리됨.  
데이 트레이딩 전략(S1~S7)은 WS 구독 풀에 포함되어 있어 `bid_ratio`가 정상 동작하지만,  
스윙 전략 종목은 WS 구독 풀 밖에 있어 구조적으로 점수가 낮게 나온다.

---

## 2. 근본 원인 분석

### 원인 1 — Signal dict 누락 필드 (S8/S9/S13/S14/S15)

`scorer.py`는 `signal.get("cntr_strength")`, `signal.get("vol_ratio")` 등을 읽지만,  
해당 전략 파일들이 이 필드를 `results.append()` dict에 넣지 않아 `0`으로 처리된다.

**S8 예시:**
```python
# strategy_8_golden_cross.py results.append() — 현재
{
    "stk_cd": stk_cd, "stk_nm": stk_nm,
    "strategy": "S8_GOLDEN_CROSS",
    "score": ..., "rsi": ..., "gap_pct": ..., "flu_rt": ...,
    # cntr_strength ← 없음 (cntr_str 변수는 계산됨)
    # vol_ratio     ← 없음 (vol_today/vol_ma20 계산됨)
    # is_today_cross ← 없음 (is_today_cross 변수 존재)
    # stoch_gc      ← 없음 (S9은 있음, S8엔 미포함)
}
```

**scorer.py S8 case의 결과:**
```
cntr_sig = signal.get("cntr_strength", 0)  → 0 (누락)
effective_str = 0 → strength (market_ctx = 100.0, WS default)
→ cntr 항목: 100 > 100 기준 미충족 → 10점만

vol_ratio_s8 = signal.get("vol_ratio", 0)  → 0 (누락)
→ vol 항목: 0점

flu_rt (25) + vol (0) + cntr (10) + bid (0) + rsi (5~10) = 40~45
< threshold 65 → CANCEL
```

---

### 원인 2 — WS 비구독 종목 bid_ratio = 0 (스윙 전략 전체)

스윙 전략(S8~S15) 후보 종목은 WebSocket 구독 풀에 없어 `ws:hoga:{stk_cd}` 키가 Redis에 없다.

```python
# scorer.py — 현재
bid  = _safe_float(hoga.get("total_buy_bid_req"))      # → 0 (키 없음)
ask  = _safe_float(hoga.get("total_sel_bid_req", "1")) # → 1
bid_ratio = 0 / 1 = 0.0   # 실제 0인지 WS 없는 건지 구분 불가
```

**전략별 bid_ratio 배점 (현재 전부 0점)**

| 전략 | bid_ratio 최대 배점 |
|------|-------------------|
| S8_GOLDEN_CROSS | 15점 |
| S9_PULLBACK_SWING | 20점 |
| S10_NEW_HIGH | 미포함 (cntr 30점) |
| S12_CLOSING | 20점 |
| S13_BOX_BREAKOUT | 25점 |
| S14_OVERSOLD_BOUNCE | 15점 |
| S15_MOMENTUM_ALIGN | 15점 |

---

### 원인 3 — S10 cntr_strength 절벽(cliff) 구조

신고가 달성 직후 체결강도가 70~99%인 경우가 많다(매수세 소화 중).  
현재 scorer는 100% 미만이면 30점 항목이 0점이 되는 절벽 구조다.

```python
# 현재 (절벽)
score += 30 if effective_str_s10 > 130 \
    else 20 if effective_str_s10 > 110 \
    else 10 if effective_str_s10 > 100 \
    else 0   # ← 100 이하면 0점 (70~99% 구간 전부 0)

# 예시: cntr_strength = 85%
vol_surge(200%+) → 20점
flu_rt(2~5%)     → 10점
cntr(85%)        →  0점  ← 절벽
bid_ratio        →  0점  ← WS 없음
합계: 30점 < threshold 65 → 구조적으로 통과 불가
```

---

## 3. 전략별 현황 및 개선 사항 (S1~S15)

### S1 — 갭 상승 개장 `strategy_1_gap_opening.py`

**현황 (양호)**
- Signal dict: `gap_pct`, `cntr_strength` 포함 ✅
- WS 구독 대상(시초가 전 예상체결): `bid_ratio` 일부 가용
- 시간대 보너스(09:00~09:30) 적용 ✅

**현재 scorer 배점 구조**
```
gap_pct (20점) + strength (30점) + bid_ratio (25점) + cntr_sig 보너스 (10점)
최대 85점 → threshold 70
```

**개선 필요 없음.** 단, WS 예상체결 데이터 유실 시 bid_ratio=0 발생 가능.  
→ 해결 방안: Task 2의 bid_ratio None 처리 공통 적용.

---

### S2 — VI 눌림목 `strategy_2_vi_pullback.py`

**현황 (양호)**
- Signal dict: `pullback_pct`, `is_dynamic` 포함 ✅
- WS 구독 종목(VI 발동 직후 구독): `bid_ratio` 가용

**현재 scorer 배점 구조**
```
pullback_pct (30점) + is_dynamic (15점) + strength (20점) + bid_ratio (20점)
최대 85점 → threshold 65
```

**개선 사항:** VI 발동 후 WS 구독 전 구간에 bid_ratio=0 발생.  
→ Task 2의 None 처리 공통 적용.

---

### S3 — 기관/외인 동시 순매수 `strategy_3_inst_foreign.py`

**현황 (양호)**
- Signal dict: `net_buy_amt`, `continuous_days`, `vol_ratio` 포함 ✅
- WS bid_ratio 의존 없음 (scorer S3 case에 bid_ratio 미사용)

**현재 scorer 배점 구조**
```
net_buy_amt (25점) + cont_days (30점) + vol_ratio (25점)
최대 80점 → threshold 60
```

**개선 필요 없음.**

---

### S4 — 장대양봉 `strategy_4_big_candle.py`

**현황 (양호)**
- Signal dict: `vol_ratio`, `body_ratio`, `is_new_high` 포함 ✅
- `strength`는 market_ctx에서 실시간 WS 값 사용

**현재 scorer 배점 구조**
```
vol_ratio (25점) + body_ratio (20점) + is_new_high (20점) + strength (20점)
최대 85점 → threshold 75
```

**개선 사항:**  
- WS 구독 종목이므로 `bid_ratio`도 가용하나 scorer S4 case에 미활용.  
- `bid_ratio` 보너스 항목 추가 고려 (선택적).

---

### S5 — 프로그램 순매수 `strategy_5_program_buy.py`

**현황 (양호)**
- Signal dict: `net_buy_amt` 포함 ✅
- WS 구독 종목: `bid_ratio` 가용

**현재 scorer 배점 구조**
```
net_buy_amt (40점) + strength (25점) + bid_ratio (20점)
최대 85점 → threshold 65
```

**개선 필요 없음.**

---

### S6 — 테마 상승 `strategy_6_theme.py`

**현황 (양호)**
- Signal dict: `gap_pct`, `cntr_strength` 포함 ✅
- WS 구독 종목: `bid_ratio` 가용

**현재 scorer 배점 구조**
```
gap_pct (25점) + cntr_strength (30점) + bid_ratio (20점)
최대 75점 → threshold 60
```

**개선 필요 없음.**

---

### S7 — 동시호가 `strategy_7_auction.py`

**현황 (양호)**
- Signal dict: `gap_pct`, `vol_rank` 포함 ✅
- 동시호가 데이터: `bid_ratio` 가용 (WS 0H 예상체결)
- 시간대 보너스(09:00~09:30) 적용 ✅

**현재 scorer 배점 구조**
```
gap_pct (25점) + bid_ratio (30점) + vol_rank (20점)
최대 75점 → threshold 70
```

**개선 필요 없음.**

---

### S8 — 골든크로스 스윙 ⚠️ 개선 필요

**현황 (누락 필드 다수)**

`strategy_8_golden_cross.py` `results.append()`:
```python
# 현재 — 누락 필드
{
    "stk_cd", "stk_nm", "strategy", "score",
    "rsi",          # ✅ 있음
    "gap_pct",      # ✅ 있음 (MA 이격률)
    "flu_rt",       # ✅ 있음
    # "cntr_strength" ← ❌ 없음 (cntr_str 변수 계산됨)
    # "vol_ratio"    ← ❌ 없음 (vol_today/vol_ma20 계산됨)
    # "is_today_cross" ← ❌ 없음 (변수 존재)
    # "stoch_gc"     ← ❌ 없음 (S8엔 MACD 가속만 있음)
    "entry_type", "target_pct", "stop_pct"
}
```

**scorer.py S8 case 현재 결과 (WS 미구독 종목 기준):**
```
flu_rt(1~5%)     → 25점
vol_ratio(0 누락) →  0점  ← 손실
cntr(0→100 기본) → 10점  ← 손실 (cntr_sig=0, effective_str=100)
bid_ratio(0)     →  0점  ← WS 없음
rsi(55)          → 10점
합계: 45점 < threshold 65 → CANCEL
```

**개선 후 예상:**
```
flu_rt(1~5%)         → 25점
vol_ratio(2.5→≥1.5x) → 12점  ← 복구
cntr(135%)            → 30점  ← 복구
bid_ratio(None)       →  0점  ← 스킵 (패널티 없음)
rsi(55)               → 10점
is_today_cross(True)  → 10점  ← 신규
합계: 87점 → threshold 60 통과
```

---

### S9 — 눌림목 반등 스윙 ⚠️ 개선 필요

**현황 (부분 누락)**

`strategy_9_pullback.py` `results.append()`:
```python
# 현재 — 부분 포함
{
    "stk_cd", "stk_nm", "strategy", "score",
    "pct_ma5",   # ✅ 있음
    "rsi",       # ✅ 있음
    "stoch_gc",  # ✅ 있음
    # "cntr_strength" ← ❌ 없음 (cntr_str 변수 계산됨)
    # "vol_ratio"     ← ❌ 없음 (vols[0]/vol_ma20 계산됨)
    # "flu_rt"        ← ❌ 없음 (flu_rt 변수 계산됨)
    "entry_type", "target_pct", "stop_pct"
}
```

**scorer.py S9 case 현재 결과:**
```
flu_rt(WS tick 있으면 정상, 없으면 0)  → 30 or 0점
cntr(0→100 기본)                       → 10점  ← 손실
bid_ratio(0)                           →  0점  ← WS 없음
rsi(50~60)                             →  5점
합계: 45점 < threshold 60 → CANCEL
```

**개선 후 예상:**
```
flu_rt(2%)         → 30점
cntr(120%)         → 25점  ← 복구
bid_ratio(None)    →  0점  ← 스킵
rsi(52)            → 10점
pct_ma5(-0.5~2.0)  → 15점  ← 신규 활용 (scorer에 추가)
stoch_gc(True)     → 10점  ← 신규 활용
합계: 90점 → threshold 55 통과
```

---

### S10 — 52주 신고가 돌파 스윙 ⚠️ 개선 필요 (Cliff 구조)

**현황 (cntr_strength 포함, cliff 구조가 문제)**

`strategy_10_new_high.py` `results.append()`:
```python
{
    "stk_cd", "stk_nm", "cur_prc", "strategy",
    "flu_rt",        # ✅ 있음
    "vol_surge_rt",  # ✅ 있음 (ka10023 급증률)
    "cntr_strength", # ✅ 있음 (ka10046 REST 조회)
    "score",
    "target_pct", "stop_pct"
    # "bid_ratio"    ← ❌ 없음 (ka10004 미호출)
}
```

**scorer.py S10 case 문제점:**
```python
# 현재 (절벽)
score += 30 if effective_str_s10 > 130 \
    else 20 if effective_str_s10 > 110 \
    else 10 if effective_str_s10 > 100 \
    else 0   # 70~100% 구간 전부 0점

# 52주 신고가 = 강력한 조건이지만 기본 보너스 없음
```

**개선 후 (gradient + 기본 보너스):**
```python
score += 8   # 52주 신고가 통과 기본 보너스
score += (30 if effective_str_s10 > 130
          else 20 if effective_str_s10 > 110
          else 12 if effective_str_s10 > 90
          else 6  if effective_str_s10 > 70
          else 0)
```

---

### S11 — 외인 지속 매수 스윙 ⚠️ 부분 개선 필요

**현황 (거의 양호, 단 scorer가 cntr_strength 미활용)**

`strategy_11_frgn_cont.py` `results.append()`:
```python
{
    "stk_cd", "stk_nm", "strategy", "score",
    "cur_prc",
    "dm1", "dm2", "dm3", "tot",  # ✅ 있음
    "flu_rt",                     # ✅ 있음
    "cntr_strength",              # ✅ 있음
    "entry_type", "target_pct", "target2_pct", "stop_pct"
}
```

**scorer.py S11 case 현재:**
```python
case "S11_FRGN_CONT":
    dm1 = _safe_float(signal.get("dm1", 0))
    # ...
    score += 30 if strength > 120 else (20 if strength > 100 else 0)
    # ↑ market_ctx.strength 사용 → WS 구독 없으면 100.0 (기본값)
    # signal의 cntr_strength 미활용 ← 비효율
```

**개선:** scorer S11 case에서 `signal.get("cntr_strength")` 우선 사용.

---

### S12 — 종가 강도 ⚠️ 개선 필요

**현황 (buy_req/sel_req 누락)**

`strategy_12_closing.py` `results.append()`:
```python
{
    "stk_cd", "stk_nm", "cur_prc", "strategy",
    "flu_rt",        # ✅ 있음
    "cntr_strength", # ✅ 있음 (ka10027 응답에 직접 포함)
    "score",
    "entry_type", "target_pct", "stop_pct"
    # "buy_req"  ← ❌ 없음 (ka10027 응답에 있음: 매수 잔량)
    # "sel_req"  ← ❌ 없음 (ka10027 응답에 있음: 매도 잔량)
}
```

**scorer.py S12 case 현재:**
```python
case "S12_CLOSING":
    cntr_str_sig = _safe_float(signal.get("cntr_strength", 0))
    effective_str = cntr_str_sig if cntr_str_sig > 0 else strength
    score += 30 if 4 <= flu_rt <= 10 else ...
    score += 35 if effective_str >= 130 else ...
    score += 20 if bid_ratio > 1.5 else ...  # ← WS 없어서 0
```

**개선:** `buy_req`/`sel_req`를 signal에 추가, scorer에서 local_bid_ratio 대체 사용.

---

### S13 — 박스권 돌파 스윙 ⚠️ 개선 필요

**현황 (rsi 누락)**

`strategy_13_box_breakout.py` `results.append()`:
```python
{
    "stk_cd", "stk_nm", "cur_prc", "strategy",
    "flu_rt",            # ✅ 있음
    "cntr_strength",     # ✅ 있음
    "vol_ratio",         # ✅ 있음
    "is_monster_vol",    # ✅ 있음
    "bollinger_squeeze", # ✅ 있음
    "mfi_confirmed",     # ✅ 있음
    "score",
    # "rsi"         ← ❌ 없음 (indicator_rsi 미호출)
    # "bid_ratio"   ← ❌ 없음 (WS 없음)
}
```

**scorer.py S13 case 현재:**
```python
case "S13_BOX_BREAKOUT":
    # cntr_strength, vol_ratio → 정상 (signal에 있음)
    score += 30 if 3 <= flu_rt_s13 <= 8 else ...   # 정상
    score += 35 if effective_str > 150 else ...     # 정상
    score += 25 if bid_ratio > 2 else ...           # ← 0점 (WS 없음)
    if rsi > 0: score += 10 if rsi > 60 else ...   # rsi=0 (누락)
```

**개선:** S13 strategy에 RSI 계산 추가 및 signal dict 포함.  
scorer에서 `bollinger_squeeze`, `mfi_confirmed` 보너스 항목 추가 활용.

---

### S14 — 과매도 반등 스윙 ⚠️ 개선 필요

**현황 (다수 필드 누락)**

`strategy_14_oversold_bounce.py` `results.append()`:
```python
{
    "stk_cd", "stk_nm", "cur_prc", "strategy",
    "score",
    "rsi",          # ✅ 있음
    "cond_count",   # ✅ 있음 ("2/3" 문자열)
    "stop_price",   # ✅ 있음
    "target_price", # ✅ 있음
    "entry_type", "holding_days"
    # "cntr_strength" ← ❌ 없음 (cntr_str 변수 있음)
    # "vol_ratio"     ← ❌ 없음 (vol_ratio 변수 있음)
    # "atr_pct"       ← ❌ 없음 (atr_pct 변수 있음)
    # "flu_rt"        ← ❌ 없음 (flu_rt 변수 있음)
}
```

**scorer.py S14 case 현재 결과:**
```
rsi(28)            → 30점  ← 정상
atr_pct(0 누락)    →  0점  ← 손실 (atr_pct=0이면 0점)
cntr(0→100 기본)   →  5점  ← 손실
bid_ratio(0)       →  0점  ← WS 없음
합계: 35점 < threshold 65 → CANCEL
```

**개선 후 예상:**
```
rsi(28)            → 30점
atr_pct(2.5%)      → 12점  ← 복구
cntr(110%)         → 15점  ← 복구
bid_ratio(None)    →  0점  ← 스킵
합계: 57점 + cond_bonus(≥4 → +10) = 67점 → threshold 60 통과
```

---

### S15 — 모멘텀 정렬 스윙 (거의 양호)

**현황 (필드 대부분 포함)**

`strategy_15_momentum_align.py` `results.append()`:
```python
{
    "stk_cd", "stk_nm", "cur_prc", "strategy",
    "flu_rt",        # ✅ 있음
    "cntr_strength", # ✅ 있음
    "rsi",           # ✅ 있음
    "macd_gc",       # ✅ 있음
    "pct_b",         # ✅ 있음
    "vol_ratio",     # ✅ 있음
    "vwap_above",    # ✅ 있음
    "atr_pct",       # ✅ 있음
    "cond_macd", "cond_rsi", "cond_boll", "cond_vol",
    "cond_count",    # ✅ 있음 (정수)
    "score",
    # "bid_ratio" ← ❌ 없음 (WS 없음)
}
```

**scorer.py S15 case 현재 결과:**
```
rsi(55~65)         → 35점  ← 정상
vol_ratio(2.0x)    → 18점  ← 정상
cntr(115%)         → 18점  ← 정상 (signal에 있음)
bid_ratio(0)       →  0점  ← WS 없음
flu_rt(2%)         →  5점  ← 정상
합계: 76점 → threshold 70 (겨우 통과)
```

**개선 사항:** bid_ratio None 처리로 실질 최대점수 확보. `cond_count` int 활용.  
`macd_gc`, `pct_b`, `vwap_above` 등 rich signal을 scorer가 미활용 — 향후 고도화 가능.

---

## 4. Task별 구현 계획

### Task 1 — Signal dict 표준화 (S8/S9/S13/S14 — 4개 파일)

> **영향:** 원인 1 해결. S15는 이미 포함.

#### T1-A: `strategy_8_golden_cross.py`

```python
# 현재 results.append() 내부 — 변경 사항
results.append({
    "stk_cd": stk_cd,
    "stk_nm": stk_nm,
    "strategy": "S8_GOLDEN_CROSS",
    "score": round(score, 2),
    "rsi": round(rsi_now, 1),
    "gap_pct": round(gap_pct, 2),
    "flu_rt": flu_rt,
    # ↓ 신규 추가 (변수는 이미 계산되어 있음)
    "cntr_strength": round(cntr_str, 1),         # ← cntr_str 변수 존재
    "vol_ratio": round(vol_today / vol_ma20, 2), # ← 두 변수 모두 존재
    "is_today_cross": is_today_cross,            # ← 변수 존재
    "is_macd_accel": is_macd_accel,             # ← 변수 존재 (scorer 추후 활용)
    # ↑ 신규 추가
    "entry_type": "현재가_종가",
    "target_pct": 10.0,
    "stop_pct": -5.0
})
```

#### T1-B: `strategy_9_pullback.py`

```python
results.append({
    "stk_cd": stk_cd,
    "stk_nm": stk_nm,
    "strategy": "S9_PULLBACK_SWING",
    "score": round(score, 2),
    "pct_ma5": round(pct_ma5, 2),
    "rsi": round(rsi_now, 1),
    "stoch_gc": stoch_gc,
    # ↓ 신규 추가
    "cntr_strength": round(cntr_str, 1),         # ← cntr_str 변수 존재
    "vol_ratio": round(vols[0] / (sum(vols[1:21]) / 20), 2), # ← vols 존재
    "flu_rt": round(flu_rt, 2),                  # ← flu_rt 변수 존재
    # ↑ 신규 추가
    "entry_type": "현재가_종가_분할매수",
    "target_pct": 6.0,
    "stop_pct": -4.0
})
```

#### T1-C: `strategy_13_box_breakout.py`

RSI 계산 추가 후 signal dict에 포함:

```python
# scan_box_breakout() 내부 — RSI 추가 (S13에 현재 없음)
from indicator_rsi import calc_rsi   # import 추가
# ...기존 코드...
rsi_vals = calc_rsi(closes, 14)      # 추가
rsi_now = rsi_vals[0] if rsi_vals else 0.0  # 추가

results.append({
    # 기존 필드 유지
    "stk_cd": stk_cd, "stk_nm": stk_nm, "cur_prc": ...,
    "strategy": "S13_BOX_BREAKOUT",
    "score": ..., "flu_rt": ..., "cntr_strength": ...,
    "vol_ratio": ..., "is_monster_vol": ...,
    "bollinger_squeeze": ..., "mfi_confirmed": ...,
    # ↓ 신규 추가
    "rsi": round(rsi_now, 1),        # ← 추가
    # ↑ 신규 추가
    "entry_type": ..., "holding_days": ...,
    "target_pct": 10.0, "stop_pct": -5.0
})
```

#### T1-D: `strategy_14_oversold_bounce.py`

```python
results.append({
    "stk_cd": stk_cd,
    "stk_nm": ...,
    "cur_prc": cur_prc,
    "strategy": "S14_OVERSOLD_BOUNCE",
    "score": round(score, 2),
    "rsi": round(rsi_now, 1),
    "cond_count": cond_count,        # 문자열 "2/3" → int로 변경
    # ↓ 신규 추가
    "cntr_strength": round(cntr_str, 1),  # ← cntr_str 변수 존재
    "vol_ratio": round(vol_ratio, 2),     # ← vol_ratio 변수 존재
    "atr_pct": round(atr_pct, 2),         # ← atr_pct 변수 존재
    "flu_rt": round(flu_rt, 2),           # ← flu_rt 변수 존재
    # ↑ 신규 추가
    "stop_price": ..., "target_price": ...,
    "entry_type": ..., "holding_days": ...
})
```

> **주의:** `cond_count` 필드를 `"2/3"` 문자열에서 `int`로 변경.  
> scorer.py의 `int(signal.get("cond_count", 0) or 0)` 처리는 문자열에서 0을 반환하므로 수정 필요.

---

### Task 2 — scorer.py bid_ratio 중립화 처리 (공통)

> **영향:** 원인 2 해결. 모든 WS 비구독 스윙 전략에 적용.

```python
# scorer.py rule_score() 내부 — 현재
bid  = _safe_float(hoga.get("total_buy_bid_req"))
ask  = _safe_float(hoga.get("total_sel_bid_req", "1"))
bid_ratio = bid / ask if ask > 0 else 0.0

# 변경 후
_hoga_available = bool(hoga)   # 빈 dict이면 WS 데이터 없음
bid  = _safe_float(hoga.get("total_buy_bid_req", 0))
ask  = _safe_float(hoga.get("total_sel_bid_req", 1))
bid_ratio = (bid / ask) if (_hoga_available and ask > 0) else None
```

각 전략 case의 bid_ratio 사용 부분:

```python
# 변경 전
score += 25 if bid_ratio > 2 else (20 if bid_ratio > 1.5 else ...)

# 변경 후
if bid_ratio is not None:
    score += 25 if bid_ratio > 2 else (20 if bid_ratio > 1.5 else ...)
# bid_ratio=None → 항목 스킵 (0점 아님, 해당 배점 제외하고 나머지로 평가)
```

**적용 대상 case:** S1, S2, S5, S6, S7, S8, S9, S12, S13, S14, S15  
(S3, S4, S10, S11은 scorer에서 bid_ratio 미사용)

---

### Task 3 — scorer.py S10 gradient 개선

> **영향:** 원인 3 해결.

```python
case "S10_NEW_HIGH":
    vol_surge = _safe_float(signal.get("vol_surge_rt", 0))
    if vol_surge == 0:
        vol_ratio_java = _safe_float(signal.get("vol_ratio", 0))
        vol_surge = max(0.0, (vol_ratio_java - 1.0) * 100)
    score += 30 if vol_surge >= 300 else (20 if vol_surge >= 200 else (10 if vol_surge >= 100 else 0))
    score += 20 if 2 <= flu_rt <= 8 else (10 if 0 < flu_rt <= 15 else (-10 if flu_rt > 15 else 0))

    cntr_sig_s10 = _safe_float(signal.get("cntr_strength", 0))
    effective_str_s10 = cntr_sig_s10 if cntr_sig_s10 > 0 else strength

    # 현재 (절벽 구조) → 변경 후 (gradient)
    score += 8   # ← 신규: 52주 신고가 돌파 자체 기본 보너스
    score += (30 if effective_str_s10 > 130
              else 20 if effective_str_s10 > 110
              else 12 if effective_str_s10 > 90   # ← 신규 구간
              else 6  if effective_str_s10 > 70   # ← 신규 구간
              else 0)
```

---

### Task 4 — S12 buy_req/sel_req 활용

> **영향:** S12 WS 미구독 bid_ratio 보완.

#### `strategy_12_closing.py` 변경:

```python
results.append({
    "stk_cd": stk_cd, "stk_nm": stk_nm,
    "cur_prc": int(cur_prc),
    "strategy": "S12_CLOSING",
    "flu_rt": round(flu_rt, 2),
    "cntr_strength": round(cntr_str, 1),
    "score": round(score, 2),
    # ↓ 신규 추가 (ka10027 응답에 이미 있음)
    "buy_req": float(str(item.get("buy_req", "0")).replace(",", "") or "0"),
    "sel_req": float(str(item.get("sel_req", "1")).replace(",", "") or "1"),
    # ↑ 신규 추가
    "entry_type": "15:20_장마감_전_진입",
    "target_pct": 5.0,
    "stop_pct": -3.0
})
```

#### `scorer.py` S12 case 변경:

```python
case "S12_CLOSING":
    cntr_str_sig = _safe_float(signal.get("cntr_strength", 0))
    effective_str = cntr_str_sig if cntr_str_sig > 0 else strength

    # buy_req/sel_req 있으면 bid_ratio 대체로 사용
    buy_req = _safe_float(signal.get("buy_req", 0))
    sel_req = _safe_float(signal.get("sel_req", 0))
    if sel_req > 0 and buy_req > 0:
        local_bid_ratio = buy_req / sel_req
    elif bid_ratio is not None:
        local_bid_ratio = bid_ratio
    else:
        local_bid_ratio = None

    score += 30 if 4 <= flu_rt <= 10 else (15 if 10 < flu_rt <= 15 else (-10 if flu_rt > 15 else 0))
    score += 35 if effective_str >= 130 else (25 if effective_str >= 110 else (10 if effective_str >= 100 else 0))
    if local_bid_ratio is not None:
        score += 20 if local_bid_ratio > 1.5 else (10 if local_bid_ratio > 1.2 else 0)
```

---

### Task 5 — scorer.py S8/S9 기술지표 활용

> **영향:** T1에서 추가한 signal 필드를 scorer에서 실제 배점에 반영.

#### scorer.py S8 case 추가:

```python
case "S8_GOLDEN_CROSS":
    flu_rt_s8 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
    cntr_sig = _safe_float(signal.get("cntr_strength", 0))
    effective_str = cntr_sig if cntr_sig > 0 else strength
    vol_ratio_s8 = _safe_float(signal.get("vol_ratio", 0))

    score += 25 if 1 <= flu_rt_s8 <= 5 else (15 if 5 < flu_rt_s8 <= 10 else 0)
    score += 20 if vol_ratio_s8 >= 3.0 else (12 if vol_ratio_s8 >= 1.5 else (5 if vol_ratio_s8 >= 1.0 else 0))
    score += 30 if effective_str > 130 else (20 if effective_str > 110 else (10 if effective_str > 100 else 0))
    if bid_ratio is not None:
        score += 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)
    if rsi > 0:
        score += 10 if rsi > 55 else (5 if rsi > 50 else 0)

    # ↓ 신규 추가 (T1에서 signal에 포함)
    is_today_cross = bool(signal.get("is_today_cross", False))
    score += 10 if is_today_cross else 0          # 당일 크로스 가점

    is_macd_accel = bool(signal.get("is_macd_accel", False))
    score += 8 if is_macd_accel else 0            # MACD 가속 보너스
    # ↑ 신규 추가
```

#### scorer.py S9 case 추가:

```python
case "S9_PULLBACK_SWING":
    flu_rt_s9 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
    cntr_sig = _safe_float(signal.get("cntr_strength", 0))
    effective_str = cntr_sig if cntr_sig > 0 else strength

    score += 30 if 0.5 <= flu_rt_s9 <= 3 else (20 if 3 < flu_rt_s9 <= 6 else (10 if 6 < flu_rt_s9 <= 10 else 0))
    score += 35 if effective_str > 130 else (25 if effective_str > 110 else (10 if effective_str > 100 else 0))
    if bid_ratio is not None:
        score += 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.2 else 0)
    if rsi > 0:
        score += 10 if 40 <= rsi <= 60 else (5 if 60 < rsi <= 70 else 0)

    # ↓ 신규 추가 (T1에서 signal에 포함)
    pct_ma5 = _safe_float(signal.get("pct_ma5", 999))
    if pct_ma5 != 999:
        score += 15 if -1.0 <= pct_ma5 <= 2.0 else (8 if abs(pct_ma5) <= 4.0 else 0)

    stoch_gc = bool(signal.get("stoch_gc", False))
    score += 10 if stoch_gc else 0
    # ↑ 신규 추가
```

---

### Task 6 — http_utils.py fetch_hoga() 추가 (ka10004)

> **영향:** WS 비구독 종목에 REST로 실시간 호가 비율 보완.  
> **선택적 적용:** 호출 비용 고려, S10/S12에서만 우선 적용.

```python
# http_utils.py에 추가
async def fetch_hoga(token: str, stk_cd: str, rdb=None) -> float | None:
    """
    ka10004 주식호가요청 → 매수/매도 잔량 비율 반환.
    Redis 캐시 ws:hoga:{stk_cd} 있으면 캐시 사용 (WS 데이터 우선).
    캐시 없으면 REST 조회.

    반환: bid_ratio (float) 또는 None (조회 실패)
    """
    # 1. Redis 캐시 우선 (WS 구독 종목)
    if rdb:
        try:
            cached = await rdb.hgetall(f"ws:hoga:{stk_cd}")
            if cached:
                bid = _safe_float_local(cached.get("total_buy_bid_req", 0))
                ask = _safe_float_local(cached.get("total_sel_bid_req", 1))
                return bid / ask if ask > 0 else None
        except Exception:
            pass

    # 2. REST 조회 (WS 미구독 종목)
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={
                    "api-id": "ka10004",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd, "stex_tp": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10004", logger):
                return None

            hoga_info = data.get("hoga_info", {})
            if not hoga_info:
                return None

            bid = _safe_float_local(hoga_info.get("total_buy_bid_req", 0))
            ask = _safe_float_local(hoga_info.get("total_sel_bid_req", 1))
            return bid / ask if ask > 0 else None

    except Exception as e:
        logger.debug("[http_utils] fetch_hoga [%s] 실패: %s", stk_cd, e)
        return None


def _safe_float_local(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return default
```

**호출 위치:**

```python
# strategy_10_new_high.py — cntr_str 조회 직후
from http_utils import fetch_cntr_strength, validate_kiwoom_response, fetch_hoga  # 추가

# scan_new_high_swing() 내부 종목별 루프에서
cntr_str = await fetch_cntr_strength(token, stk_cd)
bid_ratio = await fetch_hoga(token, stk_cd, rdb)  # ← 추가

results.append({
    # ...기존 필드...
    "cntr_strength": round(cntr_str, 1),
    "bid_ratio": round(bid_ratio, 3) if bid_ratio is not None else None,  # ← 추가
})
```

---

### Task 7 — scorer.py S11 cntr_strength 우선 사용

```python
case "S11_FRGN_CONT":
    dm1 = _safe_float(signal.get("dm1", 0))
    dm2 = _safe_float(signal.get("dm2", 0))
    dm3 = _safe_float(signal.get("dm3", 0))
    cont_days = sum(1 for d in (dm1, dm2, dm3) if d > 0)
    score += 30 if cont_days >= 3 else (20 if cont_days >= 2 else 0)
    score += 20 if flu_rt > 0 else (-10 if flu_rt < -3 else 0)

    # 현재: strength (market_ctx, WS = 100.0 기본) 사용
    # 변경: signal.cntr_strength 우선
    cntr_sig_s11 = _safe_float(signal.get("cntr_strength", 0))
    effective_str_s11 = cntr_sig_s11 if cntr_sig_s11 > 0 else strength
    score += 30 if effective_str_s11 > 120 else (20 if effective_str_s11 > 100 else 0)
```

---

### Task 8 — scorer.py S13 보너스 필드 활용

```python
case "S13_BOX_BREAKOUT":
    # 기존 코드 유지
    # ↓ 신규 추가 (signal에 이미 있음)
    bollinger_squeeze = bool(signal.get("bollinger_squeeze", False))
    mfi_confirmed = bool(signal.get("mfi_confirmed", False))
    score += 10 if bollinger_squeeze else 0   # 수렴 패턴 보너스
    score += 8  if mfi_confirmed else 0       # 자금 유입 확인 보너스
    # ↑ 신규 추가
```

---

## 5. 수정 파일 목록 및 예상 점수 변화

| 파일 | Task | 변경 내용 | 우선순위 |
|------|------|----------|---------|
| `strategy_8_golden_cross.py` | T1-A | `cntr_strength`, `vol_ratio`, `is_today_cross`, `is_macd_accel` 추가 | **P1** |
| `strategy_9_pullback.py` | T1-B | `cntr_strength`, `vol_ratio`, `flu_rt` 추가 | **P1** |
| `strategy_13_box_breakout.py` | T1-C | `rsi` 계산 및 추가 | **P1** |
| `strategy_14_oversold_bounce.py` | T1-D | `cntr_strength`, `vol_ratio`, `atr_pct`, `flu_rt`, `cond_count`(int) 추가 | **P1** |
| `strategy_12_closing.py` | T4 | `buy_req`, `sel_req` 추가 | **P1** |
| `scorer.py` | T2 | `bid_ratio` None 중립화 (전체 case) | **P1** |
| `scorer.py` | T3 | S10 gradient 개선 + 기본 보너스 | **P1** |
| `scorer.py` | T4 | S12 `local_bid_ratio` 처리 | **P1** |
| `scorer.py` | T5 | S8 `is_today_cross`, `is_macd_accel` 활용 | **P2** |
| `scorer.py` | T5 | S9 `pct_ma5`, `stoch_gc` 활용 | **P2** |
| `scorer.py` | T7 | S11 `cntr_strength` 우선 사용 | **P2** |
| `scorer.py` | T8 | S13 `bollinger_squeeze`, `mfi_confirmed` 활용 | **P2** |
| `http_utils.py` | T6 | `fetch_hoga()` 추가 (ka10004) | **P3** |
| `strategy_10_new_high.py` | T6 | `fetch_hoga()` 호출, `bid_ratio` signal 포함 | **P3** |

---

### 전략별 예상 점수 변화

| 전략 | 현재 예상 점수 | 개선 후 예상 점수 | 주요 개선 원인 |
|------|-------------|---------------|-------------|
| S1_GAP_OPEN | 55~70 | 55~70 | 변경 없음 (bid_ratio None 안전처리만) |
| S2_VI_PULLBACK | 50~70 | 50~72 | bid_ratio None 처리 |
| S3_INST_FRGN | 50~65 | 50~65 | 변경 없음 |
| S4_BIG_CANDLE | 55~75 | 55~75 | 변경 없음 |
| S5_PROG_FRGN | 55~70 | 55~70 | 변경 없음 |
| S6_THEME_LAGGARD | 50~65 | 50~65 | 변경 없음 |
| S7_AUCTION | 55~75 | 55~75 | 변경 없음 |
| **S8_GOLDEN_CROSS** | **35~45** | **65~90** | cntr+vol+cross 복구 |
| **S9_PULLBACK_SWING** | **25~45** | **60~90** | cntr+pct_ma5+stoch 복구 |
| **S10_NEW_HIGH** | **25~45** | **50~78** | gradient + 기본 보너스 |
| **S11_FRGN_CONT** | **40~55** | **55~75** | cntr_strength 우선 사용 |
| **S12_CLOSING** | **30~50** | **60~80** | buy_req/sel_req bid 보완 |
| **S13_BOX_BREAKOUT** | **45~60** | **65~90** | RSI+bollinger+mfi 보너스 |
| **S14_OVERSOLD_BOUNCE** | **25~40** | **55~75** | cntr+atr+vol 복구 |
| S15_MOMENTUM_ALIGN | **55~75** | **60~80** | bid None 처리로 안정화 |

---

## 6. 임계값(CLAUDE_THRESHOLDS) 재설정

Task 1~8 적용 후 예상 점수 범위 기반으로 threshold 조정:

```python
CLAUDE_THRESHOLDS = {
    # 데이 트레이딩 전략 — 현행 유지
    "S1_GAP_OPEN":      70,   # 유지
    "S2_VI_PULLBACK":   65,   # 유지
    "S3_INST_FRGN":     60,   # 유지
    "S4_BIG_CANDLE":    75,   # 유지
    "S5_PROG_FRGN":     65,   # 유지
    "S6_THEME_LAGGARD": 60,   # 유지
    "S7_AUCTION":       70,   # 유지

    # 스윙 전략 — 조정
    "S8_GOLDEN_CROSS":     60,   # 65 → 60 (cntr+vol 복구, 최대 ~90)
    "S9_PULLBACK_SWING":   55,   # 60 → 55 (stoch+pct_ma5 추가, 최대 ~90)
    "S10_NEW_HIGH":        58,   # 65 → 58 (gradient 개선, 최대 ~78)
    "S11_FRGN_CONT":       58,   # 60 → 58 (cntr 우선 사용, 최대 ~75)
    "S12_CLOSING":         60,   # 65 → 60 (buy_req/sel_req 보완, 최대 ~80)
    "S13_BOX_BREAKOUT":    62,   # 65 → 62 (RSI+bollinger 보너스, 최대 ~90)
    "S14_OVERSOLD_BOUNCE": 58,   # 65 → 58 (cntr+atr+vol 복구, 최대 ~75)
    "S15_MOMENTUM_ALIGN":  65,   # 70 → 65 (bid None 처리, 최대 ~80)
}
```

> **근거:** 임계값을 너무 낮추면 Claude API 호출이 급증한다.  
> `MAX_CLAUDE_CALLS_PER_DAY` (기본 100회)를 함께 모니터링할 것.  
> 초기 1~2주는 CANCEL 로그(`[Scorer] action=CANCEL`)와 실제 신호 품질을 비교해 미세 조정.

---

## 7. 구현 순서 및 의존관계

```
Phase 1 (P1 — 즉시 효과, 2시간 이내):
  1. scorer.py: bid_ratio None 중립화 (T2)
  2. strategy_8_golden_cross.py: signal dict 보완 (T1-A)
  3. strategy_9_pullback.py: signal dict 보완 (T1-B)
  4. strategy_14_oversold_bounce.py: signal dict 보완 (T1-D)
  5. strategy_12_closing.py: buy_req/sel_req 추가 (T4)
  6. scorer.py: S10 gradient + S12 local_bid_ratio (T3+T4)
  7. CLAUDE_THRESHOLDS 재설정

Phase 2 (P2 — 지표 활용 고도화):
  8. strategy_13_box_breakout.py: RSI 추가 (T1-C)
  9. scorer.py: S8 is_today_cross/is_macd_accel 활용 (T5)
  10. scorer.py: S9 pct_ma5/stoch_gc 활용 (T5)
  11. scorer.py: S11 cntr_strength 우선 (T7)
  12. scorer.py: S13 bollinger/mfi 활용 (T8)

Phase 3 (P3 — REST 호가 보완):
  13. http_utils.py: fetch_hoga() 추가 (T6)
  14. strategy_10_new_high.py: fetch_hoga() 호출 (T6)
```

### 의존관계

```
T1 (signal 필드 추가) → T5 (scorer가 해당 필드 활용) 순으로 필수 진행
T2 (bid_ratio None)   → 모든 case 공통, T1과 독립적으로 먼저 적용 가능
T4 (S12 buy_req)      → strategy_12 변경 후 scorer S12 변경
T6 (fetch_hoga)       → http_utils 추가 후 strategy_10 변경
```

---

## 부록 — cond_count 필드 타입 불일치 주의

| 전략 | cond_count 현재 타입 | scorer.py 처리 |
|------|-------------------|--------------|
| S14_OVERSOLD_BOUNCE | `"2/3"` (str) | `int("2/3" or 0)` → `0` ← **버그** |
| S15_MOMENTUM_ALIGN | `4` (int) | `int(4 or 0)` → `4` ← 정상 |

S14의 `cond_count`를 `"2/3"` → `int`로 변경 시 `cond_cnt >= 4` 보너스(+10점) 활용 가능.  
S14는 선택조건 최대 3개이므로 `>= 3` 보너스 구간을 별도 고려:

```python
# scorer.py — cond_cnt 보너스 조항 (현재 전략 무관 공통 적용)
if cond_cnt >= 4: score += 10
elif cond_cnt == 3: score += 5
# S14는 최대 3개이므로 cond_cnt=3 → +5점만 가능
# S15는 최대 4개이므로 cond_cnt=4 → +10점 가능
```
