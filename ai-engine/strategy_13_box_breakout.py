"""
전술 13: 거래량 폭발 박스권 돌파 스윙
유형: 스윙 / 보유기간: 3~7거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. 최근 15거래일 (고가 - 저가) / 저가 ≤ 8% (박스권 형성 확인)
  2. 오늘 종가 > 15일 최고가 (박스 상단 돌파)
  3. 오늘 양봉 (종가 > 시가)
  4. 오늘 거래량 ≥ 15일 평균 거래량 × 2.0 (거래량 폭발 확인)
  5. 현재가 ≥ MA20 (추세 위 돌파만 유효)
  6. 체결강도 ≥ 120% (기존 130 → 유연화)
  7. 당일 등락률 ≤ 20% (상한가 노이즈 제외)

보너스 점수:
  · 볼린저 밴드폭(20일) < 6% – 스퀴즈 → 폭발 패턴 (수익 기대치 높음)  +15점
  · MFI(14) > 55 – 자금 실제 유입 확인 (거래량 품질 검증)               +10점

NOTE: ka10172 HTS 조건검색 의존도 제거 → ka10081 일봉 직접 계산
"""

import asyncio
import logging
import os
import statistics

from ma_utils import fetch_daily_candles, detect_box_breakout, _safe_price, _safe_vol, _calc_ma
from indicator_bollinger import calc_bollinger
from indicator_volume import calc_mfi

logger = logging.getLogger(__name__)
_API_INTERVAL  = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
MIN_CNTR_STR   = float(os.getenv("S13_MIN_CNTR_STR", "120.0"))  # 기존 130 → 120


async def scan_box_breakout(token: str, rdb=None) -> list:
    """거래량 폭발 박스권 돌파 스윙 전략 스캔 (Redis candidates 기반)"""
    candidates: list[str] = []
    if rdb:
        try:
            # S13 전용 풀 (S8∪S10 합산: ka10027 소폭상승 + ka10016 52주신고가)
            kospi  = await rdb.lrange("candidates:s13:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s13:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:25]
        except Exception as e:
            logger.warning("[S13] Redis candidates 조회 실패: %s", e)

    if not candidates:
        logger.debug("[S13] 후보 없음")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)
        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 22:
            continue

        # ── 박스권 돌파 감지 ─────────────────────────────────────
        is_breakout, box_range_pct = detect_box_breakout(
            candles, box_period=15, max_range_pct=8.0, vol_mul=2.0
        )
        if not is_breakout:
            continue

        # ── MA20 위 돌파만 유효 ──────────────────────────────────
        closes = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
        if len(closes) < 20:
            continue

        cur_prc = closes[0]
        ma20    = sum(closes[:20]) / 20
        if cur_prc < ma20:           # MA20 아래 박스 돌파는 약세 패턴
            continue

        vols  = [_safe_vol(c.get("trde_qty")) for c in candles]
        highs = [_safe_price(c.get("high_pric")) for c in candles]
        lows  = [_safe_price(c.get("low_pric"))  for c in candles]

        vol_today = vols[0] if vols else 0
        vol_ma20  = _calc_ma(vols[1:], 20)  # 오늘 제외한 20일 평균
        vol_ratio = vol_today / vol_ma20 if (vol_ma20 and vol_ma20 > 0) else 1.0

        # ── 볼린저 밴드폭 – 스퀴즈 확인 (박스권 돌파 전 압축) ────
        bollinger_squeeze = False
        if len(closes) >= 20:
            bands = calc_bollinger(closes, period=20, num_std=2.0)
            upper, middle, lower = bands[0]
            if middle > 0 and upper > 0:
                bandwidth = (upper - lower) / middle * 100
                bollinger_squeeze = bandwidth < 6.0  # 밴드 압축 → 폭발 에너지 축적

        # ── MFI – 자금 실제 유입 확인 ────────────────────────────
        mfi_confirmed = False
        if len(closes) >= 15 and all(h > 0 for h in highs[:15]) and all(l > 0 for l in lows[:15]):
            mfi_vals = calc_mfi(highs, lows, closes, vols, period=14)
            if mfi_vals and mfi_vals[0] != 0.0:
                mfi_confirmed = mfi_vals[0] > 55.0  # MFI > 55 = 실제 자금 유입

        # ── 실시간 체결강도·등락률 ────────────────────────────────
        flu_rt   = 0.0
        cntr_str = 100.0
        if rdb:
            try:
                strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 4)
                if strength_data:
                    cntr_str = statistics.mean([float(s) for s in strength_data])
                else:
                    tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                    if tick:
                        flu_rt   = float(str(tick.get("flu_rt",   "0")).replace("+", "").replace(",", ""))
                        cntr_str = float(str(tick.get("cntr_str", "100")).replace("+", "").replace(",", ""))
            except Exception:
                pass

        if flu_rt > 20.0 or flu_rt <= 0:
            continue
        if cntr_str < MIN_CNTR_STR:
            continue

        score = (
            flu_rt * 0.5
            + (cntr_str - 100) * 0.3
            + min(vol_ratio, 10.0) * 2
            + max(8.0 - box_range_pct, 0) * 1.5    # 박스 좁을수록 보너스
            + (15 if bollinger_squeeze else 0)       # 스퀴즈 → 폭발 패턴 (수익 기대치↑)
            + (10 if mfi_confirmed else 0)           # MFI 자금 유입 확인
        )

        results.append({
            "stk_cd":            stk_cd,
            "cur_prc":           round(cur_prc),
            "strategy":          "S13_BOX_BREAKOUT",
            "flu_rt":            round(flu_rt, 2),
            "cntr_strength":     round(cntr_str, 1),
            "vol_ratio":         round(vol_ratio, 2),
            "box_range_pct":     round(box_range_pct, 2),
            "bollinger_squeeze": bollinger_squeeze,
            "mfi_confirmed":     mfi_confirmed,
            "score":             round(score, 2),
            "entry_type":        "당일종가_또는_익일시가",
            "holding_days":      "3~7거래일",
            "target_pct":        10.0,
            "stop_pct":         -5.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
