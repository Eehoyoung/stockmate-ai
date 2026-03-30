"""
indicator_macd.py
MACD (Moving Average Convergence Divergence) 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청 (ma_utils.fetch_daily_candles 재사용)
  - 분봉: ka10080 주식분봉차트조회요청 (indicator_rsi.fetch_minute_candles 재사용)

표준 파라미터: fast=12, slow=26, signal=9
순수 계산 함수(calc_ema, calc_macd)는 외부 의존성 없이 사용 가능.
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
class MACDResult:
    """MACD 계산 결과 (최신 봉 기준)"""
    stk_cd:       str   = ""
    fast:         int   = 12
    slow:         int   = 26
    signal_span:  int   = 9
    macd:         Optional[float] = None   # MACD 선 (fast EMA - slow EMA)
    signal:       Optional[float] = None   # Signal 선 (MACD 의 EMA)
    histogram:    Optional[float] = None   # MACD - Signal
    macd_prev:    Optional[float] = None   # 직전 봉 MACD
    signal_prev:  Optional[float] = None   # 직전 봉 Signal
    hist_prev:    Optional[float] = None   # 직전 봉 Histogram

    @property
    def is_bullish(self) -> bool:
        """MACD > Signal (골든크로스 상태)"""
        return (self.macd is not None and self.signal is not None
                and self.macd > self.signal)

    @property
    def is_above_zero(self) -> bool:
        """MACD > 0 (중심선 위, 상승 추세)"""
        return self.macd is not None and self.macd > 0

    def is_golden_cross(self) -> bool:
        """이번 봉에서 MACD 가 Signal 을 상향 돌파"""
        if any(v is None for v in [self.macd, self.signal,
                                    self.macd_prev, self.signal_prev]):
            return False
        return (self.macd > self.signal               # 현재: MACD > Signal
                and self.macd_prev <= self.signal_prev)  # 직전: MACD ≤ Signal

    def is_dead_cross(self) -> bool:
        """이번 봉에서 MACD 가 Signal 을 하향 돌파"""
        if any(v is None for v in [self.macd, self.signal,
                                    self.macd_prev, self.signal_prev]):
            return False
        return (self.macd < self.signal
                and self.macd_prev >= self.signal_prev)

    def is_histogram_expanding_up(self) -> bool:
        """히스토그램 양전환 또는 양 방향 확대 (상승 모멘텀 가속)"""
        if self.histogram is None or self.hist_prev is None:
            return False
        return self.histogram > 0 and self.histogram > self.hist_prev

    def is_histogram_shrinking_down(self) -> bool:
        """히스토그램 음전환 또는 음 방향 확대 (하락 모멘텀 가속)"""
        if self.histogram is None or self.hist_prev is None:
            return False
        return self.histogram < 0 and self.histogram < self.hist_prev


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수
# ──────────────────────────────────────────────────────────────

def calc_ema(prices: list[float], period: int) -> list[float]:
    """
    지수이동평균(EMA) 계산 – 최신순 입력/출력.

    Args:
        prices: 종가 리스트 (최신순, index 0 = 가장 최근)
        period: EMA 기간

    Returns:
        EMA 값 리스트 (최신순). 데이터 부족 구간은 0.0.

    계산 방식:
        초기값 = SMA(period), 이후 alpha = 2 / (period + 1) EMA.
    """
    if len(prices) < period:
        return [0.0] * len(prices)

    # 오래된 순으로 뒤집어 계산
    rev = list(reversed(prices))

    ema_rev: list[float] = [0.0] * (period - 1)
    ema_rev.append(sum(rev[:period]) / period)  # 초기 SMA

    alpha = 2.0 / (period + 1)
    for i in range(period, len(rev)):
        ema_rev.append(ema_rev[-1] * (1 - alpha) + rev[i] * alpha)

    return list(reversed(ema_rev))


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_span: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """
    MACD / Signal / Histogram 계산.

    Args:
        closes:      종가 리스트 (최신순)
        fast:        단기 EMA 기간 (기본 12)
        slow:        장기 EMA 기간 (기본 26)
        signal_span: Signal EMA 기간 (기본 9)

    Returns:
        (macd_line, signal_line, histogram) – 모두 최신순 리스트.
        데이터 부족 구간은 0.0.

    필요 데이터 수: slow + signal_span - 1 이상.
    """
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)

    macd_line: list[float] = []
    for f, s in zip(ema_fast, ema_slow):
        if f == 0.0 or s == 0.0:
            macd_line.append(0.0)
        else:
            macd_line.append(f - s)

    # Signal 선은 macd_line 의 EMA
    signal_line = calc_ema(macd_line, signal_span)

    histogram: list[float] = []
    for m, sig in zip(macd_line, signal_line):
        if m == 0.0 or sig == 0.0:
            histogram.append(0.0)
        else:
            histogram.append(m - sig)

    return macd_line, signal_line, histogram


# ──────────────────────────────────────────────────────────────
# 일봉 MACD
# ──────────────────────────────────────────────────────────────

async def get_macd_daily(
    token: str,
    stk_cd: str,
    fast: int = 12,
    slow: int = 26,
    signal_span: int = 9,
) -> MACDResult:
    """
    일봉 기반 MACD 반환 (ka10081).

    Args:
        token:       Bearer 인증 토큰
        stk_cd:      종목코드
        fast:        단기 EMA 기간
        slow:        장기 EMA 기간
        signal_span: Signal EMA 기간

    Returns:
        MACDResult – 최신 봉 + 직전 봉 MACD/Signal/Histogram 포함.
        데이터 부족 또는 오류 시 macd=None.

    필요 캔들 수: slow + signal_span + 1 이상 (현재 + 직전 비교용).
    """
    candles = await fetch_daily_candles(token, stk_cd)
    return _build_macd_result(stk_cd, candles, fast, slow, signal_span,
                              price_key="cur_prc")


# ──────────────────────────────────────────────────────────────
# 분봉 MACD
# ──────────────────────────────────────────────────────────────

async def get_macd_minute(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
    fast: int = 12,
    slow: int = 26,
    signal_span: int = 9,
) -> MACDResult:
    """
    분봉 기반 MACD 반환 (ka10080).

    Args:
        token:       Bearer 인증 토큰
        stk_cd:      종목코드
        tic_scope:   분봉 단위 ("1","3","5","10","15","30","45","60")
        fast:        단기 EMA 기간
        slow:        장기 EMA 기간
        signal_span: Signal EMA 기간

    Returns:
        MACDResult.
    """
    candles = await fetch_minute_candles(token, stk_cd, tic_scope)
    return _build_macd_result(stk_cd, candles, fast, slow, signal_span,
                              price_key="cur_prc")


# ──────────────────────────────────────────────────────────────
# 내부 공통 빌더
# ──────────────────────────────────────────────────────────────

def _build_macd_result(
    stk_cd: str,
    candles: list[dict],
    fast: int,
    slow: int,
    signal_span: int,
    price_key: str = "cur_prc",
) -> MACDResult:
    closes: list[float] = []
    for c in candles:
        p = _safe_price(c.get(price_key))
        if p > 0:
            closes.append(p)

    min_required = slow + signal_span + 1
    if len(closes) < min_required:
        return MACDResult(stk_cd=stk_cd, fast=fast, slow=slow,
                          signal_span=signal_span)

    macd_line, signal_line, histogram = calc_macd(closes, fast, slow, signal_span)

    def _val(lst: list[float], idx: int) -> Optional[float]:
        v = lst[idx] if idx < len(lst) else 0.0
        return v if v != 0.0 else None

    return MACDResult(
        stk_cd=stk_cd,
        fast=fast,
        slow=slow,
        signal_span=signal_span,
        macd=_val(macd_line, 0),
        signal=_val(signal_line, 0),
        histogram=_val(histogram, 0),
        macd_prev=_val(macd_line, 1),
        signal_prev=_val(signal_line, 1),
        hist_prev=_val(histogram, 1),
    )
