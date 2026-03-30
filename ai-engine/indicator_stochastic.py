"""
indicator_stochastic.py
스토캐스틱 오실레이터 (Stochastic Oscillator) 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청 (ma_utils.fetch_daily_candles 재사용)
  - 분봉: ka10080 주식분봉차트조회요청 (indicator_rsi.fetch_minute_candles 재사용)

표준 파라미터: k_period=14, d_period=3, slowing=3
%K = (현재가 - N일 최저가) / (N일 최고가 - N일 최저가) × 100
%D = %K 의 M일 SMA (Signal)
Slow %K = 원래 %K 의 slowing 일 SMA, Slow %D = Slow %K 의 d_period 일 SMA
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ma_utils import fetch_daily_candles, _safe_price
from indicator_rsi import fetch_minute_candles

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class StochasticResult:
    """스토캐스틱 계산 결과 (최신 봉 기준)"""
    stk_cd:   str   = ""
    k_period: int   = 14
    d_period: int   = 3
    slowing:  int   = 3
    k:        Optional[float] = None   # Slow %K (0~100)
    d:        Optional[float] = None   # Slow %D (0~100)
    k_prev:   Optional[float] = None   # 직전 봉 %K
    d_prev:   Optional[float] = None   # 직전 봉 %D

    @property
    def is_oversold(self) -> bool:
        """%K < 20 : 과매도"""
        return self.k is not None and self.k < 20.0

    @property
    def is_overbought(self) -> bool:
        """%K > 80 : 과매수"""
        return self.k is not None and self.k > 80.0

    def is_golden_cross(self) -> bool:
        """%K 가 %D 를 상향 돌파 (과매도권에서 신뢰도 높음)"""
        if any(v is None for v in [self.k, self.d, self.k_prev, self.d_prev]):
            return False
        return self.k > self.d and self.k_prev <= self.d_prev  # type: ignore[operator]

    def is_dead_cross(self) -> bool:
        """%K 가 %D 를 하향 돌파 (과매수권에서 신뢰도 높음)"""
        if any(v is None for v in [self.k, self.d, self.k_prev, self.d_prev]):
            return False
        return self.k < self.d and self.k_prev >= self.d_prev  # type: ignore[operator]

    def is_oversold_golden_cross(self) -> bool:
        """과매도 구간(20 미만)에서의 골든크로스 – 강력 매수 신호"""
        return self.is_golden_cross() and (self.k_prev or 100.0) < 20.0


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수
# ──────────────────────────────────────────────────────────────

def _sma_list(values: list[float], period: int) -> list[float]:
    """SMA 리스트 계산 (오래된순 입력, 오래된순 출력)"""
    result: list[float] = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        result.append(sum(window) / period)
    return result


def calc_stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    k_period: int = 14,
    d_period: int = 3,
    slowing: int = 3,
) -> tuple[list[float], list[float]]:
    """
    Slow Stochastic Oscillator 계산.

    Args:
        highs:    고가 리스트 (최신순)
        lows:     저가 리스트 (최신순)
        closes:   종가 리스트 (최신순)
        k_period: Raw %K 계산 기간 (기본 14)
        d_period: %D SMA 기간 (기본 3)
        slowing:  Slow %K 평활화 기간 (기본 3)

    Returns:
        (slow_k, slow_d) – 모두 최신순 리스트 (0.0 = 데이터 부족).

    계산 방식:
        Raw %K  = (close - lowest_low) / (highest_high - lowest_low) × 100
        Slow %K = Raw %K 의 slowing 일 SMA
        Slow %D = Slow %K 의 d_period 일 SMA
    """
    n = len(closes)
    if n < k_period + slowing + d_period - 1:
        return [0.0] * n, [0.0] * n

    # 오래된순으로 뒤집어 계산
    rev_h = list(reversed(highs))
    rev_l = list(reversed(lows))
    rev_c = list(reversed(closes))

    raw_k_rev: list[float] = [0.0] * (k_period - 1)
    for i in range(k_period - 1, n):
        hh = max(rev_h[i - k_period + 1: i + 1])
        ll = min(rev_l[i - k_period + 1: i + 1])
        denom = hh - ll
        raw_k_rev.append(
            (rev_c[i] - ll) / denom * 100.0 if denom > 0 else 50.0
        )

    slow_k_rev = _sma_list(raw_k_rev, slowing)
    slow_d_rev = _sma_list(slow_k_rev, d_period)

    return list(reversed(slow_k_rev)), list(reversed(slow_d_rev))


# ──────────────────────────────────────────────────────────────
# 일봉 스토캐스틱
# ──────────────────────────────────────────────────────────────

async def get_stochastic_daily(
    token: str,
    stk_cd: str,
    k_period: int = 14,
    d_period: int = 3,
    slowing: int = 3,
) -> StochasticResult:
    """
    일봉 기반 스토캐스틱 반환 (ka10081).

    Args:
        token:    Bearer 인증 토큰
        stk_cd:   종목코드
        k_period: Raw %K 기간
        d_period: %D SMA 기간
        slowing:  Slow %K 평활화 기간

    Returns:
        StochasticResult – k, d, k_prev, d_prev 포함.
        데이터 부족 또는 오류 시 k=None.

    필요 캔들 수: k_period + slowing + d_period 이상.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    return _build_stoch_result(stk_cd, candles, k_period, d_period, slowing)


# ──────────────────────────────────────────────────────────────
# 분봉 스토캐스틱
# ──────────────────────────────────────────────────────────────

async def get_stochastic_minute(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
    k_period: int = 14,
    d_period: int = 3,
    slowing: int = 3,
) -> StochasticResult:
    """
    분봉 기반 스토캐스틱 반환 (ka10080).

    Args:
        token:     Bearer 인증 토큰
        stk_cd:    종목코드
        tic_scope: 분봉 단위
        k_period:  Raw %K 기간
        d_period:  %D SMA 기간
        slowing:   Slow %K 평활화 기간

    Returns:
        StochasticResult.
    """
    candles = await fetch_minute_candles(token, stk_cd, tic_scope)
    return _build_stoch_result(stk_cd, candles, k_period, d_period, slowing)


# ──────────────────────────────────────────────────────────────
# 내부 공통 빌더
# ──────────────────────────────────────────────────────────────

def _build_stoch_result(
    stk_cd: str,
    candles: list[dict],
    k_period: int,
    d_period: int,
    slowing: int,
) -> StochasticResult:
    highs, lows, closes = [], [], []
    for c in candles:
        h = _safe_price(c.get("high_pric"))
        l = _safe_price(c.get("low_pric"))
        p = _safe_price(c.get("cur_prc"))
        if h > 0 and l > 0 and p > 0:
            highs.append(h)
            lows.append(l)
            closes.append(p)

    min_req = k_period + slowing + d_period
    if len(closes) < min_req:
        return StochasticResult(stk_cd=stk_cd, k_period=k_period,
                                d_period=d_period, slowing=slowing)

    slow_k, slow_d = calc_stochastic(highs, lows, closes,
                                      k_period, d_period, slowing)

    def _val(lst: list[float], idx: int) -> Optional[float]:
        v = lst[idx] if idx < len(lst) else 0.0
        return v if v != 0.0 else None

    return StochasticResult(
        stk_cd=stk_cd,
        k_period=k_period,
        d_period=d_period,
        slowing=slowing,
        k=_val(slow_k, 0),
        d=_val(slow_d, 0),
        k_prev=_val(slow_k, 1),
        d_prev=_val(slow_d, 1),
    )
