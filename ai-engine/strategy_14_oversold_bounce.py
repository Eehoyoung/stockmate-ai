"""
전술 14: 과매도 오실레이터 수렴 반등
유형: 스윙 / 보유기간: 3~5거래일
활성화: 09:30 ~ 14:00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
설계 철학 – 탑트레이더의 "바닥매수" 알고리즘화
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  애널리스트 : "RSI 35 이하면 과매도, 기술적 반등 여지"
  탑트레이더 : "여러 오실레이터가 동시에 바닥 신호 → 세력도 본다"
  알고 시스템 : "2/3 이상 과매도 지표 충족 → 진입 규칙 발동"

핵심 원칙: 과매도이되 추세 붕괴(MA60 -15% 이하)는 제외.
  진짜 바닥 = "일시적 과매도 + 추세 살아있음 + 반등 신호 2개 이상"

필수 조건 (AND):
  1. RSI(14) ≤ 38 – 과매도권 진입 (단 RSI < 20 = 폭락 → 제외)
  2. 현재가 ≥ MA60 × 0.88 – 장기 추세 아직 살아있음
  3. ATR%(14) ≤ 4.0% – 패닉 매물 소강, 변동성 정상화 중
  4. 당일 하락폭 ≤ 5% (낙폭과대 급락 당일은 제외 – 아직 추가 하락 가능)

선택 조건 (3개 중 2개 이상 충족 → 진입, 모두 충족 → 점수 대폭 상승):
  A. Stochastic: %K가 %D를 하단(20 미만)에서 상향 돌파 (바닥 탈출 확인)
  B. Williams %R > -80 (과매도 탈출 시작, -80 돌파 상향)
  C. MFI < 30 → 최근 반등 (mfi > mfi_prev 이거나 mfi > 25)
     = 세력이 저가에서 매집 시작하는 자금 흐름

보너스 점수:
  · RSI 반등 중 (rsi > rsi_prev)                             +10점
  · 모든 선택 조건 충족 (3/3)                                +15점
  · 거래량 비율 ≥ 1.5x (반등 거래량 확인)                    +8점
  · 체결강도 ≥ 105%                                          +8점

손절: ATR × 2.0 (동적 손절) 또는 -4% 고정
목표: ATR × 3.5 (비대칭 수익) 또는 +7%
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol, _calc_ma
from indicator_rsi import calc_rsi
from indicator_atr import calc_atr, calc_williams_r
from indicator_bollinger import calc_bollinger
from indicator_stochastic import calc_stochastic
from indicator_volume import calc_mfi
from http_utils import fetch_cntr_strength_cached, fetch_stk_nm
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)

async def scan_oversold_bounce(token: str, rdb=None) -> list:
    """
    S14: 과매도 오실레이터 수렴 반등 전략
    - RSI/Stoch/MFI/W%R 등 복수 오실레이터가 바닥권에서 동시 반등할 때 진입
    """
    candidates: list[str] = []
    if rdb:
        try:
            # S14 전용 풀 (과매도 후보군)
            kospi = await rdb.lrange("candidates:s14:001", 0, 49)
            kosdaq = await rdb.lrange("candidates:s14:101", 0, 49)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:40]
        except Exception as e:
            logger.warning(f"[S14] 후보 풀 로드 실패: {e}")

    if not candidates: return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(float(os.getenv("KIWOOM_API_INTERVAL", "0.25")))

        candles = await fetch_daily_candles(token, stk_cd, target_count=65)
        if len(candles) < 60: continue

        # 데이터 파싱
        closes = [_safe_price(c.get("cur_prc")) for c in candles]
        highs  = [_safe_price(c.get("high_pric")) for c in candles]
        lows   = [_safe_price(c.get("low_pric")) for c in candles]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles]
        cur_prc = closes[0]

        # ── 필수 조건 1 & 2: RSI 과매도(20~38) & MA60 추세 생존 ──
        rsi_vals = calc_rsi(closes, 14)
        rsi_now, rsi_prev = rsi_vals[0], rsi_vals[1]
        if not (18 <= rsi_now <= 42): continue

        ma60 = sum(closes[:60]) / 60
        if cur_prc < ma60 * 0.88: continue # 추세 완전 붕괴 제외

        # ── 필수 조건 3 & 4: ATR 변동성 안정 & 당일 급락(-5%) 제외 ──
        atr_vals = calc_atr(highs, lows, closes, 14)
        atr_now = atr_vals[0]
        atr_pct = (atr_now / cur_prc) * 100
        if atr_pct > 4.0: continue # 변동성 과다(패닉) 구간 제외

        # 실시간 데이터 (Redis)
        flu_rt, cntr_str = 0.0, 100.0
        if rdb:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            if tick:
                flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", ""))
                cntr_str = float(str(tick.get("cntr_str", "100")))
        if cntr_str <= 100:
            cntr_str, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)

        if flu_rt < -5.0: continue # 하락 진행 중인 칼날 제외

        # ── 선택 조건 A: Stochastic 골든크로스 ──
        sk, sd = calc_stochastic(highs, lows, closes, 14, 3, 3)
        cond_stoch = (sk[0] > sd[0] and sk[1] <= sd[1] and sk[1] < 25)

        # ── 선택 조건 B: Williams %R -80 상향 돌파 ──
        wr = calc_williams_r(highs, lows, closes, 14)
        cond_wr = (wr[1] < -80 and wr[0] > -80)

        # ── 선택 조건 C: MFI 바닥 탈출 ──
        mfi = calc_mfi(highs, lows, closes, vols, 14)
        cond_mfi = (mfi[0] < 30 and (mfi[0] > mfi[1] or mfi[0] > 25))

        # ── 선택 조건 집계 및 스코어링 ──
        cond_count = sum([cond_stoch, cond_wr, cond_mfi])
        if cond_count < 1: continue # RSI/ATR/추세 필터를 통과한 종목은 반등 단서 1개만 보여도 재평가 허용

        vol_ma20 = sum(vols[1:21]) / 20
        vol_ratio = vols[0] / vol_ma20 if vol_ma20 > 0 else 1.0

        # 점수 산정
        score = (38 - rsi_now) * 0.5 + (cond_count * 10)
        if rsi_now > rsi_prev: score += 10
        if cond_count == 3: score += 15
        if vol_ratio >= 1.5: score += 8
        if cntr_str >= 105: score += 8

        # 동적 TP/SL — swing_low/MA20/MA60 기반 구조적 손절 (tp_sl_engine)
        ma20_val = sum(closes[:20]) / 20 if len(closes) >= 20 else None
        bb_lower_val = None
        bands = calc_bollinger(closes, period=20, num_std=2.0)
        if bands and len(bands) > 0:
            bb_lower_val = bands[0][2]  # (upper, middle, lower)
        tp_sl = calc_tp_sl(
            "S14_OVERSOLD_BOUNCE", cur_prc, highs, lows, closes,
            stk_cd=stk_cd, atr=atr_now, ma20=ma20_val, ma60=ma60,
            bb_lower=bb_lower_val, compute_zones=True,
        )
        results.append({
            "stk_cd": stk_cd,
            "stk_nm": await fetch_stk_nm(rdb, token, stk_cd),
            "cur_prc": round(cur_prc),
            "strategy": "S14_OVERSOLD_BOUNCE",
            "score": round(score, 2),
            "rsi": round(rsi_now, 1),
            "cond_count": cond_count,
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio": round(vol_ratio, 2),
            "atr_pct": round(atr_pct, 2),
            "flu_rt": round(flu_rt, 2),
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "3~5거래일",
            **tp_sl.to_signal_fields(),
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
