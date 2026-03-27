"""
전술 9: 정배열 눌림목 지지 반등 스윙
유형: 스윙 / 보유기간: 3~5거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. MA5 > MA20 > MA60 정배열 (상승 추세 확인)
  2. 현재가가 MA5 기준 -3% ~ +3% 범위 (눌림 구간 진입)
  3. 당일 양봉 (현재가 > 시가) + 등락률 > 0
  4. 당일 거래량 ≥ 전일 거래량 × 1.1 (반등 거래량 소폭 확인)
  5. MA20 대비 이격 ≤ 15% (추세 내 눌림, 과열 버블 제외)

NOTE: ka10172 HTS 조건검색 의존도 제거 → ka10081 일봉 직접 계산
"""

import asyncio
import logging
import os

from ma_utils import fetch_daily_candles, detect_pullback_setup, _safe_price, _safe_vol

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))


async def scan_pullback_swing(token: str, rdb=None) -> list:
    """정배열 눌림목 지지 반등 스윙 전략 스캔 (Redis candidates 기반)"""
    candidates: list[str] = []
    if rdb:
        try:
            kospi  = await rdb.lrange("candidates:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:25]
        except Exception as e:
            logger.warning("[S9] Redis candidates 조회 실패: %s", e)

    if not candidates:
        logger.debug("[S9] 후보 없음")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)
        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 62:
            continue

        # ── 정배열 + 눌림목 감지 ────────────────────────────────
        is_setup, pct_ma5, pct_ma20 = detect_pullback_setup(candles)
        if not is_setup:
            continue

        # MA20 과도 이격 제외 (15% 이상 위에 있으면 눌림목이 아님)
        if pct_ma20 > 15.0:
            continue

        # ── 거래량 증가 확인 ─────────────────────────────────────
        vols: list[float] = []
        for c in candles:
            v = _safe_vol(c.get("trde_qty"))
            vols.append(v)

        vol_today = vols[0] if vols else 0
        vol_yday  = vols[1] if len(vols) > 1 else 0
        if vol_yday > 0 and vol_today < vol_yday * 1.1:  # 기존 1.2 → 1.1 (유연화)
            continue

        # ── 당일 양봉 확인 ───────────────────────────────────────
        today = candles[0]
        t_close = _safe_price(today.get("cur_prc"))
        t_open  = _safe_price(today.get("open_pric"))
        if t_open > 0 and t_close <= t_open:
            continue

        # ── 실시간 등락률·체결강도 ────────────────────────────────
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

        if flu_rt <= 0 or flu_rt > 12.0:
            continue
        if cntr_str < 95.0:   # 기존 100 → 95 (유연화)
            continue

        score = (
            flu_rt * 0.5
            + max(cntr_str - 100, 0) * 0.2
            + max(5.0 - abs(pct_ma5), 0) * 2     # MA5 근접할수록 가산
            + (10 if -1.0 <= pct_ma5 <= 2.0 else 0)  # MA5 직상 최적 구간 보너스
        )

        results.append({
            "stk_cd":       stk_cd,
            "cur_prc":      round(t_close) if t_close > 0 else None,
            "strategy":     "S9_PULLBACK_SWING",
            "flu_rt":       round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "pct_from_ma5":  round(pct_ma5, 2),
            "pct_from_ma20": round(pct_ma20, 2),
            "score":        round(score, 2),
            "entry_type":   "당일종가_또는_익일시가",
            "holding_days": "3~5거래일",
            "target_pct":   6.0,
            "stop_pct":    -4.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
