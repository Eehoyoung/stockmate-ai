"""
전술 15: 다중지표 모멘텀 동조 스윙
유형: 스윙 / 보유기간: 5~10거래일
활성화: 10:00 ~ 14:30

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
설계 철학 – 애널리스트 + 알고 + 탑트레이더 교집합
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  애널리스트 : "MACD 골든크로스 + RSI 50 돌파 = 추세 전환 확인"
  알고 시스템 : "4개 모멘텀 지표 중 3개 이상 일치 → 진입 규칙"
  탑트레이더 : "VWAP 위에서 거래 + 거래량 확인 = 세력 방향과 일치"

핵심 원칙: 과열(RSI>70, Bollinger 상단 초과)은 이미 늦은 타이밍.
  진입 구간 = "추세 전환 초입~중반, 아직 상승 여력이 있는 구간"
  = 탑트레이더가 "파도 가운데" 라고 부르는 구간.

필수 조건 (AND):
  1. 현재가 ≥ MA20 (기본 추세 위)
  2. 당일 등락률 0% ~ 12% (양봉 + 과열 아님)
  3. RSI(14) < 72 – 아직 과매수 아님 (미과열 상승)

선택 조건 4개 중 3개 이상 충족 (OR-다수결 → 타이트하지 않음):
  A. MACD 모멘텀: 골든크로스 당일 OR (MACD > 0 AND histogram 2봉 연속 확대)
  B. RSI 구간:    48 ≤ RSI ≤ 68  (추세 시작~중반, 추가 상승 여력 충분)
  C. 볼린저 위치: %B 0.45 ~ 0.82 (중심선 위, 상단 미도달 = 여력 있음)
  D. 거래량:      당일 거래량 ≥ 20일 평균 × 1.3 (자금 유입 확인)

보너스 점수 (점수 가산, hard gate 아님):
  · 4/4 조건 모두 충족                                       +20점
  · VWAP 위 현재가 (당일 강세 → 장중 세력 방향과 일치)       +12점
  · ATR% 1~3% (적당한 변동성 = 수익 기회 있음)               +8점
  · Stochastic %K > 50 (오실레이터도 중립 이상)              +6점
  · 체결강도 ≥ 105%                                          +8점

손절: ATR × 2.0 (동적 손절) 또는 -5% 고정
목표: +10~15% (5~10거래일 스윙)
"""

from __future__ import annotations

import asyncio
import logging
import os

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol, _calc_ma
from indicator_rsi import calc_rsi
from indicator_macd import calc_macd
from indicator_bollinger import calc_bollinger
from indicator_atr import calc_atr
from indicator_stochastic import calc_stochastic
from indicator_volume import calc_vwap, get_vwap_minute
from http_utils import fetch_cntr_strength, fetch_stk_nm

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))


async def scan_momentum_align(token: str, rdb=None) -> list:
    """
    다중지표 모멘텀 동조 스윙 전략 스캔.

    Redis candidates:{001,101} 후보군에서 4개 모멘텀 지표 중 3개 이상이
    동일 방향(상승)을 가리키는 종목을 선별한다.
    지표별 hard gate를 최소화하고 점수 중심으로 운영한다.
    """
    candidates: list[str] = []
    if rdb:
        try:
            # S15 전용 풀 (S8 재활용: ka10027 소폭상승 0.5~8%)
            kospi  = await rdb.lrange("candidates:s15:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s15:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30]
        except Exception as e:
            logger.warning("[S15] Redis candidates 조회 실패: %s", e)

    if not candidates:
        logger.debug("[S15] 후보 없음")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)

        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 35:   # MACD slow(26) + signal(9) 최소 요구량
            continue

        # ── OHLCV 파싱 ───────────────────────────────────────────
        highs, lows, closes, vols = [], [], [], []
        for c in candles:
            h = _safe_price(c.get("high_pric"))
            l = _safe_price(c.get("low_pric"))
            p = _safe_price(c.get("cur_prc"))
            v = _safe_vol(c.get("trde_qty"))
            if p > 0:
                highs.append(h if h > 0 else p)
                lows.append(l if l > 0 else p)
                closes.append(p)
                vols.append(v)

        if len(closes) < 35:
            continue

        cur_prc = closes[0]

        # ── 필수 1: 현재가 ≥ MA20 ────────────────────────────────
        ma20 = sum(closes[:20]) / 20
        if cur_prc < ma20:
            continue

        # ── 실시간 등락률·체결강도 ───────────────────────────────
        flu_rt   = 0.0
        cntr_str: float | None = None
        if rdb:
            try:
                tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                if tick:
                    flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", "").replace(",", ""))
                strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 4)
                if strength_data:
                    cntr_str = sum(float(s) for s in strength_data) / len(strength_data)
                elif tick:
                    raw = tick.get("cntr_str", "")
                    if raw:
                        cntr_str = float(str(raw).replace("+", "").replace(",", ""))
            except Exception:
                pass

        # S15는 스윙 전략 — WS 미구독 시 flu_rt=0 → 일봉 시가 대비 등락률로 폴백
        if flu_rt == 0:
            t_open = _safe_price(candles[0].get("open_pric"))
            if t_open > 0:
                flu_rt = (cur_prc - t_open) / t_open * 100

        if cntr_str is None:
            await asyncio.sleep(_API_INTERVAL)
            cntr_str = await fetch_cntr_strength(token, stk_cd)

        # ── 필수 2: 양봉 + 과열 미달 ─────────────────────────────
        if flu_rt <= 0 or flu_rt > 12.0:
            continue

        # ── RSI 계산 ─────────────────────────────────────────────
        rsi_vals = calc_rsi(closes, 14)
        rsi_now  = rsi_vals[0] if rsi_vals and rsi_vals[0] != 0.0 else None
        rsi_prev = rsi_vals[1] if len(rsi_vals) > 1 and rsi_vals[1] != 0.0 else None

        # ── 필수 3: RSI 미과열 ────────────────────────────────────
        if rsi_now and rsi_now > 72:
            continue

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 선택 조건 A: MACD 모멘텀
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        macd_line, signal_line, histogram = calc_macd(closes, 12, 26, 9)

        macd_now   = macd_line[0] if macd_line  and macd_line[0]  != 0.0 else None
        sig_now    = signal_line[0] if signal_line and signal_line[0] != 0.0 else None
        hist_now   = histogram[0] if histogram  and histogram[0]  != 0.0 else None
        hist_prev  = histogram[1] if len(histogram) > 1 and histogram[1] != 0.0 else None
        hist_prev2 = histogram[2] if len(histogram) > 2 and histogram[2] != 0.0 else None

        macd_gc_today = (macd_now and sig_now
                         and macd_now > sig_now
                         and macd_line[1] != 0.0 and signal_line[1] != 0.0
                         and macd_line[1] <= signal_line[1])

        hist_2bar_expand = (hist_now and hist_prev and hist_prev2
                            and hist_now > 0
                            and hist_now > hist_prev
                            and hist_prev > hist_prev2)

        cond_macd = bool(
            macd_gc_today
            or (macd_now and sig_now and macd_now > 0 and hist_2bar_expand)
        )

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 선택 조건 B: RSI 구간
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        cond_rsi = bool(rsi_now and 48 <= rsi_now <= 68)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 선택 조건 C: 볼린저 %B 위치
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        cond_boll = False
        pct_b = None
        if len(closes) >= 20:
            bands = calc_bollinger(closes, 20, 2.0)
            upper, middle, lower = bands[0]
            if upper > lower > 0:
                pct_b = (cur_prc - lower) / (upper - lower)
                cond_boll = 0.45 <= pct_b <= 0.82

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 선택 조건 D: 거래량
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        vol_ma20  = _calc_ma(vols[1:], 20)
        vol_ratio = vols[0] / vol_ma20 if (vol_ma20 and vol_ma20 > 0) else 1.0
        cond_vol  = vol_ratio >= 1.3

        # ── 선택 조건 집계: 4개 중 3개 이상 ──────────────────────
        cond_count = sum([cond_macd, cond_rsi, cond_boll, cond_vol])
        if cond_count < 3:
            continue

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 보너스: ATR (동적 손절·위험 측정)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        atr_vals = calc_atr(highs, lows, closes, 14)
        atr_now  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
        atr_pct  = (atr_now / cur_prc * 100) if atr_now else None
        atr_ok   = atr_pct is not None and 1.0 <= atr_pct <= 3.0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 보너스: Stochastic 중립 이상 확인
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        stoch_ok = False
        if len(closes) >= 20:
            slow_k, slow_d = calc_stochastic(highs, lows, closes,
                                             k_period=14, d_period=3, slowing=3)
            if slow_k and slow_k[0] != 0.0:
                stoch_ok = slow_k[0] > 50.0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 보너스: VWAP (분봉 당일 강세 확인) – 실패해도 점수 미반영
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        vwap_above = False
        try:
            vwap_result = await get_vwap_minute(token, stk_cd, tic_scope="5")
            if vwap_result.vwap:
                vwap_above = cur_prc > vwap_result.vwap
        except Exception:
            pass

        # ── 점수 계산 ────────────────────────────────────────────
        score = (
            flu_rt * 0.6
            + max(cntr_str - 100, 0) * 0.2
            + cond_count * 8                                          # 조건 충족 개수
            + (20 if cond_count == 4 else 0)                          # 4/4 완전 동조
            + (12 if vwap_above else 0)                               # VWAP 위 = 장중 세력 방향
            + (8  if atr_ok else 0)                                   # ATR 적정 변동성
            + (6  if stoch_ok else 0)                                 # Stochastic 중립 이상
            + (8  if cntr_str >= 105 else 0)                          # 체결강도 확인
            + (5  if rsi_now and rsi_prev and rsi_now > rsi_prev else 0)  # RSI 상승 중
        )

        # ── ATR 기반 손절·목표가 ─────────────────────────────────
        if atr_now:
            stop_price   = round(cur_prc - atr_now * 2.0)
            stop_pct     = round((stop_price - cur_prc) / cur_prc * 100, 2)
        else:
            stop_pct = -5.0

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        results.append({
            "stk_cd":        stk_cd,
            "stk_nm":        stk_nm,
            "cur_prc":       round(cur_prc),
            "strategy":      "S15_MOMENTUM_ALIGN",
            "flu_rt":        round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "rsi":           round(rsi_now, 1) if rsi_now else None,
            "macd_gc":       macd_gc_today,
            "pct_b":         round(pct_b, 3) if pct_b is not None else None,
            "vol_ratio":     round(vol_ratio, 2),
            "vwap_above":    vwap_above,
            "atr_pct":       round(atr_pct, 2) if atr_pct else None,
            "cond_macd":     cond_macd,
            "cond_rsi":      cond_rsi,
            "cond_boll":     cond_boll,
            "cond_vol":      cond_vol,
            "cond_count":    cond_count,
            "score":         round(score, 2),
            "entry_type":    "당일종가_또는_익일시가",
            "holding_days":  "5~10거래일",
            "target_pct":    12.0,
            "stop_pct":      stop_pct,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
