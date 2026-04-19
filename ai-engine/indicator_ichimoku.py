"""
indicator_ichimoku.py
일목균형표 (Ichimoku Kinko Hyo) 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청 (ma_utils.fetch_daily_candles 재사용)

순수 계산 함수(calc_ichimoku)는 외부 의존성 없이 사용 가능.
API 조회 함수는 실패 시 None을 반환하며 예외를 raise하지 않는다.

데이터 최신순 (index 0 = 오늘) — 모든 indicator_*.py와 동일 규칙.
최소 78봉 필요 (senkou_b_period + displacement = 52 + 26).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class IchimokuResult:
    """일목균형표 계산 결과"""
    tenkan: float                  # 전환선 (현재)
    kijun: float                   # 기준선 (현재)
    span_a: float                  # 선행스팬A (현재 적용 구름)
    span_b: float                  # 선행스팬B (현재 적용 구름)
    cloud_top: float               # max(span_a, span_b) — 구름 상단
    cloud_bottom: float            # min(span_a, span_b) — 구름 하단
    cloud_thickness_pct: float     # (cloud_top - cloud_bottom) / cloud_top * 100
    is_bullish_cloud: bool         # span_a > span_b (양운)
    tenkan_above_kijun: bool       # 전환선 > 기준선
    price_above_cloud: bool        # cur_prc > cloud_top
    chikou_above_price: bool       # 후행스팬 > 26일 전 종가
    kijun_rising: bool             # 기준선 최근 2봉 상승


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수
# ──────────────────────────────────────────────────────────────

def calc_ichimoku(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> Optional[IchimokuResult]:
    """일목균형표 계산. 최신순(index 0=오늘). 부족 시 None 반환."""
    min_len = senkou_b_period + displacement  # 78
    if len(closes) < min_len or len(highs) < min_len or len(lows) < min_len:
        logger.debug(
            "[ichimoku] 데이터 부족: %d봉 (필요 %d봉)", len(closes), min_len
        )
        return None

    try:
        # ── 현재 시점 전환선 / 기준선 ─────────────────────────────
        tenkan_now = (max(highs[0:tenkan_period]) + min(lows[0:tenkan_period])) / 2
        kijun_now  = (max(highs[0:kijun_period]) + min(lows[0:kijun_period])) / 2

        # 기준선 상승 여부: 1봉 전 기준선 계산
        # 1봉 전 = index 1 기준으로 동일 폭 slice
        kijun_1bar_ago = (
            max(highs[1: kijun_period + 1]) + min(lows[1: kijun_period + 1])
        ) / 2
        kijun_rising = kijun_now > kijun_1bar_ago

        # ── 현재 구름 (26일 전 선행스팬A/B) ─────────────────────────
        # 선행스팬A: 26일 전 시점의 전환선 + 기준선 평균
        tenkan_at_26 = (
            max(highs[displacement: displacement + tenkan_period])
            + min(lows[displacement: displacement + tenkan_period])
        ) / 2
        kijun_at_26 = (
            max(highs[displacement: displacement + kijun_period])
            + min(lows[displacement: displacement + kijun_period])
        ) / 2
        span_a = (tenkan_at_26 + kijun_at_26) / 2

        # 선행스팬B: 26일 전 시점의 52일 고저 평균
        span_b = (
            max(highs[displacement: displacement + senkou_b_period])
            + min(lows[displacement: displacement + senkou_b_period])
        ) / 2

        cloud_top    = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)
        cloud_thickness_pct = (
            (cloud_top - cloud_bottom) / cloud_top * 100 if cloud_top > 0 else 0.0
        )

        # ── 신호 판단 ─────────────────────────────────────────────
        cur_prc = closes[0]
        chikou_above_price = cur_prc > closes[displacement]

        return IchimokuResult(
            tenkan=tenkan_now,
            kijun=kijun_now,
            span_a=span_a,
            span_b=span_b,
            cloud_top=cloud_top,
            cloud_bottom=cloud_bottom,
            cloud_thickness_pct=cloud_thickness_pct,
            is_bullish_cloud=span_a > span_b,
            tenkan_above_kijun=tenkan_now > kijun_now,
            price_above_cloud=cur_prc > cloud_top,
            chikou_above_price=chikou_above_price,
            kijun_rising=kijun_rising,
        )

    except Exception as e:
        logger.debug("[ichimoku] 계산 오류: %s", e)
        return None
