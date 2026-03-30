"""
indicator_volume.py
거래량 기반 지표 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청 (ma_utils.fetch_daily_candles 재사용)
  - 분봉: ka10080 주식분봉차트조회요청 (indicator_rsi.fetch_minute_candles 재사용)

구현 지표:
  OBV  (On Balance Volume)       : 누적 거래량 방향성 지표
  MFI  (Money Flow Index)        : 거래대금 기반 RSI 형 지표
  VWAP (Volume Weighted Avg Price): 거래량 가중 평균 가격 (당일 분봉 기반)
  VR   (Volume Ratio)            : 현재 거래량 / N일 평균 거래량
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol
from indicator_rsi import fetch_minute_candles

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class OBVResult:
    """OBV 계산 결과"""
    stk_cd:  str   = ""
    obv:     Optional[float] = None   # 최신 OBV
    obv_prev: Optional[float] = None  # 직전 봉 OBV
    obv_ma:  Optional[float] = None   # OBV 20봉 이동평균

    def is_rising(self) -> bool:
        """OBV 상승 (매집 신호)"""
        if self.obv is None or self.obv_prev is None:
            return False
        return self.obv > self.obv_prev

    def is_above_ma(self) -> bool:
        """OBV > OBV MA (상승 추세 확인)"""
        return (self.obv is not None and self.obv_ma is not None
                and self.obv > self.obv_ma)


@dataclass
class MFIResult:
    """MFI (Money Flow Index) 계산 결과"""
    stk_cd:   str   = ""
    period:   int   = 14
    mfi:      Optional[float] = None   # MFI (0~100)
    mfi_prev: Optional[float] = None   # 직전 봉 MFI

    @property
    def is_oversold(self) -> bool:
        """MFI < 20 : 과매도"""
        return self.mfi is not None and self.mfi < 20.0

    @property
    def is_overbought(self) -> bool:
        """MFI > 80 : 과매수"""
        return self.mfi is not None and self.mfi > 80.0

    def is_turning_up(self) -> bool:
        """과매도권(20 미만)에서 반등"""
        if self.mfi is None or self.mfi_prev is None:
            return False
        return self.mfi_prev < 20.0 and self.mfi > self.mfi_prev


@dataclass
class VWAPResult:
    """VWAP 계산 결과 (당일 분봉 기반)"""
    stk_cd:  str   = ""
    vwap:    Optional[float] = None   # VWAP
    cur_prc: float = 0.0

    @property
    def is_above_vwap(self) -> bool:
        """현재가 > VWAP (기관/세력 매수 구간)"""
        return self.vwap is not None and self.cur_prc > self.vwap

    def pct_from_vwap(self) -> Optional[float]:
        """(현재가 - VWAP) / VWAP × 100 (%)"""
        if self.vwap and self.vwap > 0:
            return (self.cur_prc - self.vwap) / self.vwap * 100
        return None


@dataclass
class VolumeRatioResult:
    """거래량 비율 결과"""
    stk_cd:     str   = ""
    period:     int   = 20
    cur_vol:    float = 0.0    # 당일 거래량
    avg_vol:    float = 0.0    # N일 평균 거래량
    ratio:      Optional[float] = None  # cur_vol / avg_vol

    @property
    def is_surge(self) -> bool:
        """거래량 2배 이상 급증"""
        return self.ratio is not None and self.ratio >= 2.0

    @property
    def is_dry(self) -> bool:
        """거래량 0.5배 이하 (거래 위축)"""
        return self.ratio is not None and self.ratio <= 0.5


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수 – OBV
# ──────────────────────────────────────────────────────────────

def calc_obv(
    closes: list[float],
    volumes: list[float],
) -> list[float]:
    """
    OBV 계산.

    Args:
        closes:  종가 리스트 (최신순)
        volumes: 거래량 리스트 (최신순)

    Returns:
        OBV 리스트 (최신순).

    규칙:
        close > prev_close → +volume
        close < prev_close → -volume
        close == prev_close → ±0
    """
    if len(closes) < 2 or len(volumes) < 2:
        return [0.0] * len(closes)

    rev_c = list(reversed(closes))
    rev_v = list(reversed(volumes))

    obv_rev: list[float] = [0.0]
    running = 0.0
    for i in range(1, len(rev_c)):
        if rev_c[i] > rev_c[i - 1]:
            running += rev_v[i]
        elif rev_c[i] < rev_c[i - 1]:
            running -= rev_v[i]
        obv_rev.append(running)

    return list(reversed(obv_rev))


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수 – MFI
# ──────────────────────────────────────────────────────────────

def calc_mfi(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    period: int = 14,
) -> list[float]:
    """
    MFI (Money Flow Index) 계산.

    Args:
        highs:   고가 리스트 (최신순)
        lows:    저가 리스트 (최신순)
        closes:  종가 리스트 (최신순)
        volumes: 거래량 리스트 (최신순)
        period:  기간 (기본 14)

    Returns:
        MFI 값 리스트 (최신순, 0~100). 데이터 부족 구간은 0.0.

    공식:
        TP  = (high + low + close) / 3
        MF  = TP × volume
        PMF = Σ(positive MF, period)
        NMF = Σ(negative MF, period)
        MFR = PMF / NMF
        MFI = 100 - 100 / (1 + MFR)
    """
    n = len(closes)
    if n < period + 1:
        return [0.0] * n

    rev_h = list(reversed(highs))
    rev_l = list(reversed(lows))
    rev_c = list(reversed(closes))
    rev_v = list(reversed(volumes))

    tps = [(rev_h[i] + rev_l[i] + rev_c[i]) / 3 for i in range(n)]
    mfs = [tps[i] * rev_v[i] for i in range(n)]

    mfi_rev: list[float] = [0.0] * period
    for i in range(period, n):
        pmf = sum(mfs[j] for j in range(i - period + 1, i + 1)
                  if tps[j] > tps[j - 1])
        nmf = sum(mfs[j] for j in range(i - period + 1, i + 1)
                  if tps[j] < tps[j - 1])
        if nmf == 0:
            mfi_rev.append(100.0)
        elif pmf == 0:
            mfi_rev.append(0.0)
        else:
            mfr = pmf / nmf
            mfi_rev.append(100.0 - 100.0 / (1.0 + mfr))

    return list(reversed(mfi_rev))


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수 – VWAP
# ──────────────────────────────────────────────────────────────

def calc_vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> float:
    """
    VWAP 계산 (전체 기간 누적).

    Args:
        highs, lows, closes: OHLC (최신순)
        volumes: 거래량 (최신순)

    Returns:
        VWAP 값 (float). 데이터 없으면 0.0.

    공식: Σ(TP × volume) / Σ(volume)
    """
    total_vol = sum(volumes)
    if total_vol <= 0:
        return 0.0
    total_tp_vol = sum(
        (highs[i] + lows[i] + closes[i]) / 3 * volumes[i]
        for i in range(len(closes))
    )
    return total_tp_vol / total_vol


# ──────────────────────────────────────────────────────────────
# 일봉 OBV
# ──────────────────────────────────────────────────────────────

async def get_obv_daily(
    token: str,
    stk_cd: str,
    obv_ma_period: int = 20,
) -> OBVResult:
    """
    일봉 기반 OBV 반환 (ka10081).

    Args:
        token:         Bearer 인증 토큰
        stk_cd:        종목코드
        obv_ma_period: OBV 이동평균 기간 (기본 20)

    Returns:
        OBVResult – obv, obv_prev, obv_ma 포함.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    closes, volumes = [], []
    for c in candles:
        p = _safe_price(c.get("cur_prc"))
        v = _safe_vol(c.get("trde_qty"))
        if p > 0:
            closes.append(p)
            volumes.append(v)

    if len(closes) < 2:
        return OBVResult(stk_cd=stk_cd)

    obv_vals = calc_obv(closes, volumes)

    obv_ma: Optional[float] = None
    if len(obv_vals) >= obv_ma_period:
        obv_ma = sum(obv_vals[:obv_ma_period]) / obv_ma_period

    return OBVResult(
        stk_cd=stk_cd,
        obv=obv_vals[0] if obv_vals else None,
        obv_prev=obv_vals[1] if len(obv_vals) > 1 else None,
        obv_ma=obv_ma,
    )


# ──────────────────────────────────────────────────────────────
# 일봉 MFI
# ──────────────────────────────────────────────────────────────

async def get_mfi_daily(
    token: str,
    stk_cd: str,
    period: int = 14,
) -> MFIResult:
    """
    일봉 기반 MFI 반환 (ka10081).

    Returns:
        MFIResult – mfi, mfi_prev 포함.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    highs, lows, closes, volumes = [], [], [], []
    for c in candles:
        h = _safe_price(c.get("high_pric"))
        l = _safe_price(c.get("low_pric"))
        p = _safe_price(c.get("cur_prc"))
        v = _safe_vol(c.get("trde_qty"))
        if h > 0 and l > 0 and p > 0:
            highs.append(h)
            lows.append(l)
            closes.append(p)
            volumes.append(v)

    if len(closes) < period + 1:
        return MFIResult(stk_cd=stk_cd, period=period)

    mfi_vals = calc_mfi(highs, lows, closes, volumes, period)

    def _val(lst: list[float], idx: int) -> Optional[float]:
        v = lst[idx] if idx < len(lst) else 0.0
        return v if v != 0.0 else None

    return MFIResult(
        stk_cd=stk_cd,
        period=period,
        mfi=_val(mfi_vals, 0),
        mfi_prev=_val(mfi_vals, 1),
    )


# ──────────────────────────────────────────────────────────────
# 분봉 VWAP (당일 기준)
# ──────────────────────────────────────────────────────────────

async def get_vwap_minute(
    token: str,
    stk_cd: str,
    tic_scope: str = "1",
) -> VWAPResult:
    """
    당일 분봉 기반 VWAP 반환 (ka10080).

    Args:
        token:     Bearer 인증 토큰
        stk_cd:    종목코드
        tic_scope: 분봉 단위 (VWAP 용으로는 "1" 또는 "3" 권장)

    Returns:
        VWAPResult – vwap, cur_prc 포함.

    주의:
        ka10080 는 base_dt 당일 전체 분봉을 반환하므로
        당일 분봉 전체를 사용해 VWAP 계산.
    """
    candles = await fetch_minute_candles(token, stk_cd, tic_scope)
    if not candles:
        return VWAPResult(stk_cd=stk_cd)

    highs, lows, closes, volumes = [], [], [], []
    for c in candles:
        h = _safe_price(c.get("high_pric"))
        l = _safe_price(c.get("low_pric"))
        p = _safe_price(c.get("cur_prc"))
        v = _safe_vol(c.get("trde_qty"))
        if h > 0 and l > 0 and p > 0:
            highs.append(h)
            lows.append(l)
            closes.append(p)
            volumes.append(v)

    if not closes:
        return VWAPResult(stk_cd=stk_cd)

    vwap = calc_vwap(highs, lows, closes, volumes)
    return VWAPResult(
        stk_cd=stk_cd,
        vwap=vwap if vwap > 0 else None,
        cur_prc=closes[0],
    )


# ──────────────────────────────────────────────────────────────
# 일봉 거래량 비율 (VR)
# ──────────────────────────────────────────────────────────────

async def get_volume_ratio_daily(
    token: str,
    stk_cd: str,
    period: int = 20,
) -> VolumeRatioResult:
    """
    일봉 기반 거래량 비율 반환 (ka10081).

    Args:
        token:  Bearer 인증 토큰
        stk_cd: 종목코드
        period: 평균 거래량 기간 (기본 20)

    Returns:
        VolumeRatioResult – cur_vol, avg_vol, ratio 포함.
        index 0 = 오늘(최신), index 1~period = 과거 평균 기준.

    계산 방식:
        cur_vol = candles[0].trde_qty
        avg_vol = SMA(trde_qty[1:period+1]) — 오늘 제외 N일 평균
        ratio   = cur_vol / avg_vol
    """
    candles = await fetch_daily_candles(token, stk_cd)
    volumes: list[float] = []
    for c in candles:
        v = _safe_vol(c.get("trde_qty"))
        volumes.append(v)

    if len(volumes) < period + 1:
        return VolumeRatioResult(stk_cd=stk_cd, period=period)

    cur_vol = volumes[0]
    avg_vol = sum(volumes[1: period + 1]) / period
    ratio = cur_vol / avg_vol if avg_vol > 0 else None

    return VolumeRatioResult(
        stk_cd=stk_cd,
        period=period,
        cur_vol=cur_vol,
        avg_vol=avg_vol,
        ratio=ratio,
    )
