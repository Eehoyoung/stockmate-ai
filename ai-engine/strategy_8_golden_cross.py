"""
전술 8: 5일선 골든크로스 스윙
유형: 스윙 / 보유기간: 3~7거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. MA5 > MA20 크로스오버 당일 OR 직근 3일 이내 (이격 ≤ 5%)
  2. 현재가 ≥ MA60 × 0.95 (60일선 지지권 이내)
  3. 당일 거래량 ≥ MA20 거래량 × 1.3 (크로스 당일 거래량 확인)
  4. 당일 등락률 0~15% (양봉 + 과열 제외)
  5. MA5/MA20 이격 ≤ 5% (크로스 직후, 추격 진입 방지)

NOTE: ka10172 HTS 조건검색 의존도 제거 → ka10081 일봉 직접 계산
"""

import asyncio
import logging
import os

from ma_utils import fetch_daily_candles, detect_golden_cross, _calc_ma, _safe_price, _safe_vol

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))


async def scan_golden_cross(token: str, rdb=None) -> list:
    """5일선 골든크로스 스윙 전략 스캔 (Redis candidates 기반)"""
    candidates: list[str] = []
    if rdb:
        try:
            kospi  = await rdb.lrange("candidates:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:25]
        except Exception as e:
            logger.warning("[S8] Redis candidates 조회 실패: %s", e)

    if not candidates:
        logger.debug("[S8] 후보 없음")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)
        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 22:
            continue

        # ── 골든크로스 감지 ──────────────────────────────────────
        crossed_today, near_cross, gap_pct = detect_golden_cross(candles)
        if not (crossed_today or near_cross):
            continue

        # ── 가격·거래량 파싱 ─────────────────────────────────────
        closes: list[float] = []
        vols:   list[float] = []
        for c in candles:
            p = _safe_price(c.get("cur_prc"))
            v = _safe_vol(c.get("trde_qty"))
            if p > 0:
                closes.append(p)
                vols.append(v)

        if len(closes) < 22 or closes[0] == 0:
            continue

        cur_prc  = closes[0]
        ma20     = sum(closes[:20]) / 20
        vol_ma20 = _calc_ma(vols, 20)
        vol_today = vols[0] if vols else 0

        # ── MA60 지지선 확인 ─────────────────────────────────────
        if len(closes) >= 60:
            ma60 = sum(closes[:60]) / 60
            if cur_prc < ma60 * 0.95:   # MA60 -5% 이하 → 하락 추세
                continue

        # ── 거래량 확인 ──────────────────────────────────────────
        if vol_ma20 and vol_ma20 > 0:
            if vol_today < vol_ma20 * 1.3:  # 기존 1.5 → 1.3 (유연화)
                continue

        # ── 실시간 등락률 확인 (Redis 틱) ────────────────────────
        flu_rt = 0.0
        cntr_str = 100.0
        if rdb:
            try:
                tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                if tick:
                    flu_rt   = float(str(tick.get("flu_rt",   "0")).replace("+", "").replace(",", ""))
                    cntr_str = float(str(tick.get("cntr_str", "100")).replace("+", "").replace(",", ""))
            except Exception:
                pass

        if flu_rt > 15.0 or flu_rt < 0:
            continue

        vol_ratio = vol_today / vol_ma20 if (vol_ma20 and vol_ma20 > 0) else 1.0

        score = (
            (15 if crossed_today else 5)   # 크로스오버 당일 보너스
            + flu_rt * 0.4
            + min(vol_ratio, 5.0) * 4
            + max(cntr_str - 100, 0) * 0.1
        )

        results.append({
            "stk_cd":       stk_cd,
            "cur_prc":      round(cur_prc),
            "strategy":     "S8_GOLDEN_CROSS",
            "flu_rt":       round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio":    round(vol_ratio, 2),
            "score":        round(score, 2),
            "entry_type":   "당일종가_또는_익일시가",
            "holding_days": "3~7거래일",
            "target_pct":   8.0,
            "stop_pct":    -4.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
