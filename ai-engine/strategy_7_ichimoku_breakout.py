"""
전술 7: 일목균형표 구름대 돌파 스윙 (S7_ICHIMOKU_BREAKOUT)
유형: 스윙 / 보유기간: 3~7거래일
활성화: 10:00 ~ 14:30

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
설계 철학 — 일목균형표 구조적 돌파 포착
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  애널리스트 : "구름 상단 돌파 = 중장기 추세 전환 확인"
  알고 시스템 : "전환선·기준선·구름 3중 배열 일치 → 추세 방향 확실"
  탑트레이더 : "구름 돌파 후 눌림 없는 양봉 = 세력이 구름을 방패로 쓰는 구간"

핵심 원칙:
  - 구름 두께가 얇을수록 돌파 이후 저항 없음 → 진입 우선순위 높음
  - 후행스팬까지 26일 전 종가 위에 있으면 3중 확인 완성
  - 스윙 (3~7거래일) 특성상 일봉 기준 지표만 사용

필수 조건 (AND, 모두 충족 시 진입):
  1. price_above_cloud = True  — 현재가가 구름대 완전 돌파
  2. tenkan_above_kijun = True — 전환선 > 기준선 (단기 상승 배열)
  3. is_bullish_cloud = True   — 양운 (구름 자체가 상승 전망)

선택 조건 4개 중 2개 이상 충족:
  A. chikou_above_price = True  — 후행스팬 확인 (26일 전 종가 초과)
  B. 거래량 > 20일 평균 × 1.5  — 자금 유입 확인
  C. RSI(14) 45 ~ 70            — 과매도/과매수 중간 구간 (추세 지속)
  D. kijun_rising = True        — 기준선 상승 중

보너스 점수 (hard gate 아님):
  · 구름 두께 < 2% (cloud_thickness_pct)       +12점
  · 선택조건 4개 모두 충족                      +15점
  · ATR% 1~3%                                  +8점
  · 체결강도 > 105%                             +8점
  · VWAP 위 현재가                              +7점
  · flu_rt 1~8%                                +5점

손절: 구름 상단 이탈 (kijun 기준 ATR × 1.5)
목표: +8~15% (3~7거래일 스윙)
"""

from __future__ import annotations

import asyncio
import logging
import os

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol, _calc_ma
from indicator_ichimoku import calc_ichimoku
from indicator_rsi import calc_rsi
from indicator_atr import calc_atr
from indicator_volume import get_vwap_minute
from http_utils import fetch_cntr_strength_cached, fetch_stk_nm
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

# 일목균형표 최소 필요 봉 수
_ICHIMOKU_MIN_BARS = 78  # senkou_b_period(52) + displacement(26)


async def scan_ichimoku_breakout(token: str, rdb=None) -> list[dict]:
    """일목균형표 구름대 돌파 스윙 전략 스캔.

    Redis candidates:s7:{001,101} 후보군에서 일목균형표 3중 배열(구름 돌파 +
    전환선 > 기준선 + 양운)이 일치하는 종목을 선별한다.
    """
    candidates: list[str] = []
    if rdb:
        try:
            kospi  = await rdb.lrange("candidates:s7:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s7:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30]
        except Exception as e:
            logger.warning("[S7] Redis candidates 조회 실패: %s", e)

    if not candidates:
        logger.debug("[S7] 후보 없음")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)

        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < _ICHIMOKU_MIN_BARS:
            logger.debug("[S7] %s 일봉 부족: %d봉", stk_cd, len(candles))
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

        if len(closes) < _ICHIMOKU_MIN_BARS:
            continue

        cur_prc = closes[0]

        # ── 일목균형표 계산 ──────────────────────────────────────
        ichi = calc_ichimoku(highs, lows, closes)
        if ichi is None:
            continue

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 필수 조건 — 3개 모두 충족 필수
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if not ichi.price_above_cloud:
            continue
        if not ichi.tenkan_above_kijun:
            continue
        if not ichi.is_bullish_cloud:
            continue

        # ── 실시간 등락률·체결강도 ───────────────────────────────
        flu_rt: float = 0.0
        cntr_str: float | None = None
        if rdb:
            try:
                tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                if tick:
                    flu_rt = float(
                        str(tick.get("flu_rt", "0")).replace("+", "").replace(",", "")
                    )
                strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 4)
                if strength_data:
                    cntr_str = sum(float(s) for s in strength_data) / len(strength_data)
                elif tick:
                    raw = tick.get("cntr_str", "")
                    if raw:
                        cntr_str = float(str(raw).replace("+", "").replace(",", ""))
            except Exception:
                pass

        # S7 스윙 — WS 미구독 시 일봉 시가 대비 등락률로 폴백
        if flu_rt == 0.0:
            t_open = _safe_price(candles[0].get("open_pric"))
            if t_open > 0:
                flu_rt = (cur_prc - t_open) / t_open * 100

        if cntr_str is None:
            await asyncio.sleep(_API_INTERVAL)
            cntr_str, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)

        # cntr_str 기본값 보정
        if cntr_str is None:
            cntr_str = 100.0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # RSI 계산
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        rsi_vals = calc_rsi(closes, 14)
        rsi_now  = rsi_vals[0] if rsi_vals and rsi_vals[0] != 0.0 else None

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 거래량 비율
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        vol_ma20  = _calc_ma(vols[1:], 20)
        vol_ratio = vols[0] / vol_ma20 if (vol_ma20 and vol_ma20 > 0) else 1.0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 선택 조건 평가
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        cond_a = ichi.chikou_above_price
        cond_b = vol_ratio >= 1.5
        cond_c = bool(rsi_now and 45.0 <= rsi_now <= 70.0)
        cond_d = ichi.kijun_rising

        cond_count = sum([cond_a, cond_b, cond_c, cond_d])
        if cond_count < 2:
            continue

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ATR 계산
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        atr_vals = calc_atr(highs, lows, closes, 14)
        atr_now  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
        atr_pct  = (atr_now / cur_prc * 100) if atr_now else None
        atr_ok   = atr_pct is not None and 1.0 <= atr_pct <= 3.0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # VWAP (분봉 당일 강세 확인) — 실패 시 점수 미반영
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        vwap_above = False
        try:
            vwap_result = await get_vwap_minute(token, stk_cd, tic_scope="5")
            if vwap_result.vwap:
                vwap_above = cur_prc > vwap_result.vwap
        except Exception:
            pass

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 점수 계산
        # base_score=50 (필수 3개 통과), 선택조건 ×8, 보너스
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        score = (
            50.0
            + cond_count * 8
            + (15 if cond_count == 4 else 0)
            + (12 if ichi.cloud_thickness_pct < 2.0 else 0)
            + (8  if atr_ok else 0)
            + (8  if cntr_str >= 105.0 else 0)
            + (7  if vwap_above else 0)
            + (5  if 1.0 <= flu_rt <= 8.0 else 0)
        )

        # ── 동적 TP/SL ──────────────────────────────────────────
        tp_sl = calc_tp_sl(
            "S7_ICHIMOKU_BREAKOUT", cur_prc, highs, lows, closes,
            stk_cd=stk_cd, atr=atr_now,
        )

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        results.append({
            "stk_cd":               stk_cd,
            "stk_nm":               stk_nm,
            "cur_prc":              round(cur_prc),
            "strategy":             "S7_ICHIMOKU_BREAKOUT",
            "flu_rt":               round(flu_rt, 2),
            "tenkan":               round(ichi.tenkan, 0),
            "kijun":                round(ichi.kijun, 0),
            "cloud_top":            round(ichi.cloud_top, 0),
            "cloud_bottom":         round(ichi.cloud_bottom, 0),
            "cloud_thickness_pct":  round(ichi.cloud_thickness_pct, 2),
            "chikou_above":         ichi.chikou_above_price,
            "rsi":                  round(rsi_now, 1) if rsi_now else None,
            "vol_ratio":            round(vol_ratio, 2),
            "cntr_strength":        round(cntr_str, 1),
            "cond_count":           cond_count,
            "score":                round(score, 2),
            "entry_type":           "당일종가_또는_익일시가",
            "holding_days":         "3~7거래일",
            **tp_sl.to_signal_fields(),
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
