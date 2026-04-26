"""
indicator_atr.py
ATR (Average True Range) 및 Williams %R 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청 (ma_utils.fetch_daily_candles 재사용)
  - 분봉: ka10080 주식분봉차트조회요청 (ma_utils.fetch_minute_candles 재사용)

ATR       : 시장 변동성 측정 (손절/목표가 설정에 활용)
Williams %R: 과매도/과매수 오실레이터 (-100~0, -80 미만 = 과매도)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ma_utils import fetch_daily_candles, fetch_minute_candles, _safe_price

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class ATRResult:
    """ATR 계산 결과"""
    stk_cd:   str   = ""
    period:   int   = 14
    atr:      Optional[float] = None   # ATR 절대값 (원)
    atr_pct:  Optional[float] = None   # ATR / 현재가 × 100 (%)
    cur_prc:  float = 0.0

    @property
    def is_high_volatility(self) -> bool:
        """ATR% > 3% : 고변동성 구간"""
        return self.atr_pct is not None and self.atr_pct > 3.0

    @property
    def is_low_volatility(self) -> bool:
        """ATR% < 1% : 저변동성 구간 (스퀴즈/눌림 상태)"""
        return self.atr_pct is not None and self.atr_pct < 1.0

    def stop_loss_price(self, multiplier: float = 2.0) -> Optional[float]:
        """ATR 기반 손절가: 현재가 - multiplier × ATR"""
        if self.atr is None or self.cur_prc <= 0:
            return None
        return self.cur_prc - multiplier * self.atr

    def target_price(self, multiplier: float = 3.0) -> Optional[float]:
        """ATR 기반 목표가: 현재가 + multiplier × ATR"""
        if self.atr is None or self.cur_prc <= 0:
            return None
        return self.cur_prc + multiplier * self.atr


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수 – ATR
# ──────────────────────────────────────────────────────────────

def calc_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """
    ATR (Wilder's Smoothed) 계산.

    Args:
        highs:  고가 리스트 (최신순)
        lows:   저가 리스트 (최신순)
        closes: 종가 리스트 (최신순)
        period: ATR 기간 (기본 14)

    Returns:
        ATR 값 리스트 (최신순). 데이터 부족 구간은 0.0.

    계산 방식:
        TR = max(high - low,
                 |high - prev_close|,
                 |low  - prev_close|)
        초기 ATR = SMA(TR, period)
        이후 ATR = (prev_ATR × (period-1) + TR) / period
    """
    n = len(closes)
    if n < period + 1:
        return [0.0] * n

    rev_h = list(reversed(highs))
    rev_l = list(reversed(lows))
    rev_c = list(reversed(closes))

    trs: list[float] = [0.0]  # index 0: 데이터 없음
    for i in range(1, n):
        tr = max(
            rev_h[i] - rev_l[i],
            abs(rev_h[i] - rev_c[i - 1]),
            abs(rev_l[i] - rev_c[i - 1]),
        )
        trs.append(tr)

    atr_rev: list[float] = [0.0] * period
    atr_rev.append(sum(trs[1: period + 1]) / period)

    for i in range(period + 1, n):
        atr_rev.append((atr_rev[-1] * (period - 1) + trs[i]) / period)

    return list(reversed(atr_rev))


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수 – Williams %R
# ──────────────────────────────────────────────────────────────

def calc_williams_r(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """
    Williams %R 계산.

    Args:
        highs:  고가 리스트 (최신순)
        lows:   저가 리스트 (최신순)
        closes: 종가 리스트 (최신순)
        period: 기간 (기본 14)

    Returns:
        %R 값 리스트 (최신순, -100 ~ 0). 데이터 부족 구간은 0.0.

    공식: %R = (HH - close) / (HH - LL) × -100
    """
    n = len(closes)
    if n < period:
        return [0.0] * n

    rev_h = list(reversed(highs))
    rev_l = list(reversed(lows))
    rev_c = list(reversed(closes))

    wr_rev: list[float] = [0.0] * (period - 1)
    for i in range(period - 1, n):
        hh = max(rev_h[i - period + 1: i + 1])
        ll = min(rev_l[i - period + 1: i + 1])
        denom = hh - ll
        wr_rev.append(
            (hh - rev_c[i]) / denom * -100.0 if denom > 0 else -50.0
        )

    return list(reversed(wr_rev))


# ──────────────────────────────────────────────────────────────
# 일봉 ATR
# ──────────────────────────────────────────────────────────────

async def get_atr_daily(
    token: str,
    stk_cd: str,
    period: int = 14,
) -> ATRResult:
    """
    일봉 기반 ATR 반환 (ka10081).

    Returns:
        ATRResult – atr, atr_pct 포함.
        데이터 부족 또는 오류 시 atr=None.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    return _build_atr_result(stk_cd, candles, period)


async def get_atr_minute(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
    period: int = 14,
) -> ATRResult:
    """분봉 기반 ATR 반환 (ka10080)."""
    candles = await fetch_minute_candles(token, stk_cd, tic_scope)
    return _build_atr_result(stk_cd, candles, period)


def _build_atr_result(
    stk_cd: str,
    candles: list[dict],
    period: int,
) -> ATRResult:
    highs, lows, closes = [], [], []
    for c in candles:
        h = _safe_price(c.get("high_pric"))
        l = _safe_price(c.get("low_pric"))
        p = _safe_price(c.get("cur_prc"))
        if h > 0 and l > 0 and p > 0:
            highs.append(h)
            lows.append(l)
            closes.append(p)

    if len(closes) < period + 1:
        return ATRResult(stk_cd=stk_cd, period=period)

    atr_vals = calc_atr(highs, lows, closes, period)
    atr = atr_vals[0] if atr_vals[0] != 0.0 else None
    cur_prc = closes[0]
    atr_pct = (atr / cur_prc * 100) if atr and cur_prc > 0 else None

    return ATRResult(stk_cd=stk_cd, period=period, atr=atr,
                     atr_pct=atr_pct, cur_prc=cur_prc)


