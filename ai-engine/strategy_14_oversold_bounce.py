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

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol, _calc_ma
from indicator_rsi import calc_rsi
from indicator_atr import calc_atr, calc_williams_r
from indicator_stochastic import calc_stochastic
from indicator_volume import calc_mfi

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))


async def scan_oversold_bounce(token: str, rdb=None) -> list:
    """
    과매도 오실레이터 수렴 반등 전략 스캔.

    Redis candidates:{001,101} 후보군에서 과매도 + 복수 반등 신호를 가진
    종목을 선별한다. 전략이 타이트해지지 않도록 선택 조건은 2/3 OR 다수결로
    처리한다.
    """
    candidates: list[str] = []
    if rdb:
        try:
            # S14 전용 풀 (ka10027 하락률 3~10%)
            kospi  = await rdb.lrange("candidates:s14:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s14:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30]
        except Exception as e:
            logger.warning("[S14] Redis candidates 조회 실패: %s", e)

    if not candidates:
        logger.debug("[S14] 후보 없음")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)

        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 30:
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

        if len(closes) < 30:
            continue

        cur_prc = closes[0]

        # ── 필수 1: RSI 과매도권 (20~38) ─────────────────────────
        rsi_vals = calc_rsi(closes, 14)
        rsi_now  = rsi_vals[0] if rsi_vals and rsi_vals[0] != 0.0 else None
        rsi_prev = rsi_vals[1] if len(rsi_vals) > 1 and rsi_vals[1] != 0.0 else None

        if rsi_now is None or rsi_now > 38 or rsi_now < 20:
            continue  # 과매도 구간 밖이거나 폭락 중

        # ── 필수 2: MA60 추세 생존 확인 ─────────────────────────
        if len(closes) >= 60:
            ma60 = sum(closes[:60]) / 60
            if cur_prc < ma60 * 0.88:   # 장기 추세 붕괴 (-12% 이하)
                continue
        else:
            ma60 = None

        # ── 필수 3: ATR% – 변동성 정상화 확인 ───────────────────
        atr_vals = calc_atr(highs, lows, closes, 14)
        atr_now  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
        if atr_now is None:
            continue
        atr_pct = atr_now / cur_prc * 100
        if atr_pct > 4.0:   # 아직 패닉 구간 (변동성 너무 큼)
            continue

        # ── 실시간 등락률·체결강도 ───────────────────────────────
        flu_rt   = 0.0
        cntr_str = 100.0
        if rdb:
            try:
                tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                if tick:
                    flu_rt   = float(str(tick.get("flu_rt",   "0")).replace("+", "").replace(",", ""))
                    cntr_str = float(str(tick.get("cntr_str", "100")).replace("+", "").replace(",", ""))
            except Exception:
                pass

        # ── 필수 4: 당일 낙폭과대 급락 제외 ─────────────────────
        if flu_rt < -5.0:
            continue  # 오늘 -5% 이상 급락 = 아직 하락 진행 중

        # ── 선택 조건 A: Stochastic 하단 골든크로스 ──────────────
        cond_stoch = False
        if len(closes) >= 20:
            slow_k, slow_d = calc_stochastic(highs, lows, closes,
                                             k_period=14, d_period=3, slowing=3)
            if (len(slow_k) > 1 and all(v != 0.0 for v in
                    [slow_k[0], slow_d[0], slow_k[1], slow_d[1]])):
                # %K가 %D 상향 돌파 + 이전 %K가 20 미만 (하단 이탈에서 회복)
                cond_stoch = (slow_k[0] > slow_d[0]
                              and slow_k[1] <= slow_d[1]
                              and slow_k[1] < 25.0)

        # ── 선택 조건 B: Williams %R 탈출 ────────────────────────
        cond_wr = False
        wr_vals = calc_williams_r(highs, lows, closes, 14)
        wr_now  = wr_vals[0] if wr_vals and wr_vals[0] != 0.0 else None
        wr_prev = wr_vals[1] if len(wr_vals) > 1 and wr_vals[1] != 0.0 else None
        if wr_now is not None and wr_prev is not None:
            # Williams %R 이 -80 을 상향 돌파 (과매도 탈출 시작)
            cond_wr = wr_prev < -80.0 and wr_now > wr_prev

        # ── 선택 조건 C: MFI 자금 유입 반등 ─────────────────────
        cond_mfi = False
        if len(closes) >= 15:
            mfi_vals = calc_mfi(highs, lows, closes, vols, 14)
            mfi_now  = mfi_vals[0] if mfi_vals and mfi_vals[0] != 0.0 else None
            mfi_prev = mfi_vals[1] if len(mfi_vals) > 1 and mfi_vals[1] != 0.0 else None
            if mfi_now is not None:
                # MFI 과매도권(30 미만)에서 반등 or 세력 매집 유입(25 초과)
                cond_mfi = (mfi_now < 30.0 and (
                    (mfi_prev is not None and mfi_now > mfi_prev)
                    or mfi_now > 25.0
                ))
        else:
            mfi_now = None

        # ── 선택 조건 집계: 2/3 이상 충족 필요 ──────────────────
        cond_count = sum([cond_stoch, cond_wr, cond_mfi])
        if cond_count < 2:
            continue  # 반등 신호 2개 미만 → 단순 하락 중일 가능성

        # ── 거래량 비율 ──────────────────────────────────────────
        vol_ma20  = _calc_ma(vols[1:], 20)
        vol_ratio = vols[0] / vol_ma20 if (vol_ma20 and vol_ma20 > 0) else 1.0

        # ── 점수 계산 ────────────────────────────────────────────
        # 기준: RSI 깊을수록 + 반등 신호 많을수록 + 거래량 확인 + 강도 확인
        score = (
            (38 - rsi_now) * 0.5                              # RSI 깊을수록 가산 (최대 ~9점)
            + cond_count * 10                                 # 선택 조건 개수 (20 or 30)
            + (10 if rsi_now and rsi_prev and rsi_now > rsi_prev else 0)  # RSI 반등 중
            + (15 if cond_count == 3 else 0)                  # 3/3 완전 수렴 보너스
            + (8 if vol_ratio >= 1.5 else 0)                  # 반등 거래량 확인
            + (8 if cntr_str >= 105 else 0)                   # 체결강도 확인
            + max(cntr_str - 100, 0) * 0.1
        )

        # ── ATR 기반 손절·목표가 ─────────────────────────────────
        stop_price   = round(cur_prc - atr_now * 2.0)
        target_price = round(cur_prc + atr_now * 3.5)
        stop_pct     = round((stop_price - cur_prc) / cur_prc * 100, 2)
        target_pct   = round((target_price - cur_prc) / cur_prc * 100, 2)

        results.append({
            "stk_cd":        stk_cd,
            "cur_prc":       round(cur_prc),
            "strategy":      "S14_OVERSOLD_BOUNCE",
            "flu_rt":        round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "rsi":           round(rsi_now, 1),
            "atr_pct":       round(atr_pct, 2),
            "cond_stoch":    cond_stoch,
            "cond_wr":       cond_wr,
            "cond_mfi":      cond_mfi,
            "cond_count":    cond_count,
            "vol_ratio":     round(vol_ratio, 2),
            "score":         round(score, 2),
            "entry_type":    "당일종가_또는_익일시가",
            "holding_days":  "3~5거래일",
            "target_pct":    target_pct,
            "stop_pct":      stop_pct,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
