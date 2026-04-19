"""
downtrend_detector.py
하락 추세 전환 감지 모듈 — position_monitor.py 에서 호출

5가지 컴포넌트 점수 합산 (각 0~1점, 합계 0~5점)
  1. 체결강도 하락  — ws:strength 최근 평균 < 70  → 1.0 / < 85  → 0.5
  2. 호가 매도 우위 — sell/buy 잔량비 > 2.0 → 1.0 / > 1.5 → 0.5
  3. 가격 하락 속도 — 진입가 대비 낙폭  > 1.5% → 1.0 / > 1.0% → 0.5
  4. 등락률 음전    — flu_rt < -1.5%  → 1.0 / < -0.5% → 0.5
  5. 체결강도 추세  — 최근 3개 평균이 이전 7개 평균 대비 5pt 이상 하락 → 1.0

score ≥ 3 → TREND_REVERSAL 후보 (Claude 2차 판단 요청)
"""

from __future__ import annotations

import logging
from typing import Optional

from redis_reader import get_tick_data, get_strength_trend, get_hoga_ratio

logger = logging.getLogger(__name__)


async def compute_reversal_score(
    rdb,
    stk_cd:      str,
    *,
    entry_price: int,
    cur_prc:     Optional[int] = None,  # None 이면 ws:tick 에서 읽음
) -> dict:
    """
    하락 추세 점수 계산.

    Returns:
        {
            "score":      float,        # 0~5
            "triggered":  bool,         # score >= 3
            "cur_prc":    int,
            "components": {
                "strength_weak":   float,
                "hoga_sell_bias":  float,
                "price_drop":      float,
                "flu_rt_neg":      float,
                "strength_trend":  float,
            },
            "details": {
                "avg_strength":    float,
                "hoga_ratio":      float,
                "drop_pct":        float,
                "flu_rt":          float,
                "strength_declining": bool,
            }
        }
    """
    components: dict[str, float] = {
        "strength_weak":  0.0,
        "hoga_sell_bias": 0.0,
        "price_drop":     0.0,
        "flu_rt_neg":     0.0,
        "strength_trend": 0.0,
    }
    details: dict = {}

    # ── ws:tick 읽기 ─────────────────────────────────────────
    tick = await get_tick_data(rdb, stk_cd)
    if cur_prc is None:
        try:
            cur_prc = int(float(str(tick.get("cur_prc", 0)).replace(",", "").replace("+", "")))
        except (TypeError, ValueError):
            cur_prc = 0

    try:
        flu_rt = float(str(tick.get("flu_rt", 0)).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        flu_rt = 0.0

    # ── 1. 체결강도 하락 ─────────────────────────────────────
    strength_data = await get_strength_trend(rdb, stk_cd)
    avg_strength  = strength_data["avg_all"]
    details["avg_strength"] = avg_strength
    if avg_strength < 70:
        components["strength_weak"] = 1.0
    elif avg_strength < 85:
        components["strength_weak"] = 0.5

    # ── 2. 호가 매도 우위 ────────────────────────────────────
    hoga_ratio = await get_hoga_ratio(rdb, stk_cd)
    details["hoga_ratio"] = hoga_ratio
    if hoga_ratio > 2.0:
        components["hoga_sell_bias"] = 1.0
    elif hoga_ratio > 1.5:
        components["hoga_sell_bias"] = 0.5

    # ── 3. 가격 하락 속도 ────────────────────────────────────
    drop_pct = 0.0
    if entry_price > 0 and cur_prc > 0:
        drop_pct = (entry_price - cur_prc) / entry_price * 100.0
    details["drop_pct"] = round(drop_pct, 3)
    if drop_pct > 1.5:
        components["price_drop"] = 1.0
    elif drop_pct > 1.0:
        components["price_drop"] = 0.5

    # ── 4. 등락률 음전 ──────────────────────────────────────
    details["flu_rt"] = flu_rt
    if flu_rt < -1.5:
        components["flu_rt_neg"] = 1.0
    elif flu_rt < -0.5:
        components["flu_rt_neg"] = 0.5

    # ── 5. 체결강도 추세 하락 ──────────────────────────────
    details["strength_declining"] = strength_data["declining"]
    if strength_data["declining"] and strength_data["count"] >= 4:
        components["strength_trend"] = 1.0

    score     = round(sum(components.values()), 2)
    triggered = score >= 3.0

    if triggered:
        logger.info(
            "[Downtrend] TREND_REVERSAL 후보 stk_cd=%s score=%.1f components=%s",
            stk_cd, score, components,
        )

    return {
        "score":      score,
        "triggered":  triggered,
        "cur_prc":    cur_prc,
        "components": components,
        "details":    details,
    }
