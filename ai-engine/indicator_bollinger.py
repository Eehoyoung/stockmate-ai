"""
indicator_bollinger.py
볼린저 밴드 (Bollinger Bands) 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청 (ma_utils.fetch_daily_candles 재사용)
  - 분봉: ka10080 주식분봉차트조회요청 (indicator_rsi.fetch_minute_candles 재사용)

표준 파라미터: period=20, num_std=2.0
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from ma_utils import fetch_daily_candles, _safe_price
from indicator_rsi import fetch_minute_candles

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class BollingerResult:
    """볼린저 밴드 계산 결과 (최신 봉 기준)"""
    stk_cd:    str   = ""
    period:    int   = 20
    num_std:   float = 2.0
    cur_prc:   float = 0.0    # 현재가
    upper:     Optional[float] = None  # 상단 밴드
    middle:    Optional[float] = None  # 중심선 (MA20)
    lower:     Optional[float] = None  # 하단 밴드
    bandwidth: Optional[float] = None  # (upper - lower) / middle × 100 (%)
    pct_b:     Optional[float] = None  # %B = (가격 - lower) / (upper - lower)

    @property
    def is_above_upper(self) -> bool:
        """현재가가 상단 밴드 돌파 (과매수 신호)"""
        return self.upper is not None and self.cur_prc > self.upper

    @property
    def is_below_lower(self) -> bool:
        """현재가가 하단 밴드 이탈 (과매도 신호)"""
        return self.lower is not None and self.cur_prc < self.lower

    @property
    def is_near_lower(self) -> bool:
        """%B ≤ 0.2 : 하단 밴드 근접 (반등 후보)"""
        return self.pct_b is not None and self.pct_b <= 0.2

    @property
    def is_near_upper(self) -> bool:
        """%B ≥ 0.8 : 상단 밴드 근접 (매도 후보)"""
        return self.pct_b is not None and self.pct_b >= 0.8

    @property
    def is_squeeze(self) -> bool:
        """밴드폭 < 5% : 스퀴즈(압축) 구간 – 큰 방향성 이탈 예고"""
        return self.bandwidth is not None and self.bandwidth < 5.0


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수
# ──────────────────────────────────────────────────────────────

def calc_bollinger(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> list[tuple[float, float, float]]:
    """
    볼린저 밴드 계산.

    Args:
        closes:  종가 리스트 (최신순, index 0 = 가장 최근)
        period:  MA 기간 (기본 20)
        num_std: 표준편차 배수 (기본 2.0)

    Returns:
        (upper, middle, lower) 튜플 리스트 (최신순).
        데이터 부족 구간은 (0.0, 0.0, 0.0).

    계산 방식:
        middle = SMA(period)
        std    = 표준편차 (모표준편차, ddof=0)
        upper  = middle + num_std × std
        lower  = middle - num_std × std
    """
    rev = list(reversed(closes))
    result_rev: list[tuple[float, float, float]] = []

    for i in range(len(rev)):
        if i < period - 1:
            result_rev.append((0.0, 0.0, 0.0))
            continue
        window = rev[i - period + 1: i + 1]
        mid = sum(window) / period
        variance = sum((x - mid) ** 2 for x in window) / period
        std = math.sqrt(variance)
        result_rev.append((mid + num_std * std, mid, mid - num_std * std))

    return list(reversed(result_rev))


# ──────────────────────────────────────────────────────────────
# 일봉 볼린저 밴드
# ──────────────────────────────────────────────────────────────

async def get_bollinger_daily(
    token: str,
    stk_cd: str,
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerResult:
    """
    일봉 기반 볼린저 밴드 반환 (ka10081).

    Args:
        token:   Bearer 인증 토큰
        stk_cd:  종목코드
        period:  MA 기간 (기본 20)
        num_std: 표준편차 배수 (기본 2.0)

    Returns:
        BollingerResult – upper/middle/lower/bandwidth/%B 포함.
        데이터 부족 또는 오류 시 upper=None.

    필요 캔들 수: period 이상.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    return _build_bollinger_result(stk_cd, candles, period, num_std,
                                   price_key="cur_prc")


# ──────────────────────────────────────────────────────────────
# 분봉 볼린저 밴드
# ──────────────────────────────────────────────────────────────

async def get_bollinger_minute(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerResult:
    """
    분봉 기반 볼린저 밴드 반환 (ka10080).

    Args:
        token:     Bearer 인증 토큰
        stk_cd:    종목코드
        tic_scope: 분봉 단위 ("1","3","5","10","15","30","45","60")
        period:    MA 기간 (기본 20)
        num_std:   표준편차 배수 (기본 2.0)

    Returns:
        BollingerResult.
    """
    candles = await fetch_minute_candles(token, stk_cd, tic_scope)
    return _build_bollinger_result(stk_cd, candles, period, num_std,
                                   price_key="cur_prc")


# ──────────────────────────────────────────────────────────────
# 내부 공통 빌더
# ──────────────────────────────────────────────────────────────

def _build_bollinger_result(
    stk_cd: str,
    candles: list[dict],
    period: int,
    num_std: float,
    price_key: str = "cur_prc",
) -> BollingerResult:
    closes: list[float] = []
    for c in candles:
        p = _safe_price(c.get(price_key))
        if p > 0:
            closes.append(p)

    if len(closes) < period:
        return BollingerResult(stk_cd=stk_cd, period=period, num_std=num_std)

    bands = calc_bollinger(closes, period, num_std)
    upper, middle, lower = bands[0]

    if upper == 0.0:
        return BollingerResult(stk_cd=stk_cd, period=period, num_std=num_std)

    cur_prc = closes[0]
    bandwidth = (upper - lower) / middle * 100 if middle > 0 else None
    pct_b = ((cur_prc - lower) / (upper - lower)
             if (upper - lower) > 0 else None)

    return BollingerResult(
        stk_cd=stk_cd,
        period=period,
        num_std=num_std,
        cur_prc=cur_prc,
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        pct_b=pct_b,
    )
