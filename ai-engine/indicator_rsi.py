"""
indicator_rsi.py
RSI (Relative Strength Index) 계산 모듈

데이터 소스:
  - 일봉: ka10081 주식일봉차트조회요청  (ma_utils.fetch_daily_candles 재사용)
  - 분봉: ka10080 주식분봉차트조회요청  (이 모듈에서 직접 조회)

순수 계산 함수(calc_rsi)는 외부 의존성 없이 사용 가능.
API 조회 함수는 실패 시 None 을 반환하며 예외를 raise하지 않는다.
"""

from __future__ import annotations

import logging
import os
import time as _time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from http_utils import validate_kiwoom_response

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol

logger = logging.getLogger(__name__)

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_DEFAULT_TIMEOUT = 10.0

# 분봉 캐시: {(stk_cd, tic_scope): (candles, expire_at)}
_MIN_CANDLE_CACHE: dict[tuple[str, str], tuple[list[dict], float]] = {}
_MIN_CACHE_TTL = int(os.getenv("RSI_MIN_CACHE_TTL_SEC", "300"))  # 5분


# ──────────────────────────────────────────────────────────────
# 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class RSIResult:
    """RSI 계산 결과"""
    stk_cd:   str   = ""
    period:   int   = 14
    rsi:      Optional[float] = None   # 최신 RSI (0~100)
    rsi_prev: Optional[float] = None   # 직전 봉 RSI

    @property
    def is_oversold(self) -> bool:
        """RSI < 30 : 과매도 구간"""
        return self.rsi is not None and self.rsi < 30.0

    @property
    def is_overbought(self) -> bool:
        """RSI > 70 : 과매수 구간"""
        return self.rsi is not None and self.rsi > 70.0

    @property
    def is_neutral(self) -> bool:
        """30 ≤ RSI ≤ 70"""
        return self.rsi is not None and 30.0 <= self.rsi <= 70.0

    def is_turning_up(self) -> bool:
        """과매도권(30 미만)에서 반등 시작 여부"""
        if self.rsi is None or self.rsi_prev is None:
            return False
        return self.rsi_prev < 30.0 and self.rsi > self.rsi_prev

    def is_turning_down(self) -> bool:
        """과매수권(70 초과)에서 하락 시작 여부"""
        if self.rsi is None or self.rsi_prev is None:
            return False
        return self.rsi_prev > 70.0 and self.rsi < self.rsi_prev


# ──────────────────────────────────────────────────────────────
# 순수 계산 함수
# ──────────────────────────────────────────────────────────────

def calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    """
    Wilder's Smoothed RSI 계산.

    Args:
        closes: 종가 리스트 (최신순, index 0 = 가장 최근)
        period: RSI 기간 (기본 14)

    Returns:
        RSI 값 리스트 (closes 와 동일 인덱스, 데이터 부족 구간은 0.0).
        최신순 정렬 유지 (index 0 = 가장 최근 RSI).

    계산 방식:
        Wilder's Smoothed Moving Average 사용 (pandas-ta 표준과 동일).
        최초 평균: 단순평균(SMA) → 이후 EMA 방식(alpha = 1/period).
    """
    if len(closes) < period + 1:
        return [0.0] * len(closes)

    # 오래된 순으로 뒤집어 계산
    rev = list(reversed(closes))
    changes = [rev[i] - rev[i - 1] for i in range(1, len(rev))]

    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    # 초기 평균 (SMA)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_rev: list[float] = [0.0] * period  # 데이터 부족 구간

    def _rsi(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    rsi_rev.append(_rsi(avg_gain, avg_loss))

    alpha = 1.0 / period
    for i in range(period, len(changes)):
        avg_gain = avg_gain * (1 - alpha) + gains[i] * alpha
        avg_loss = avg_loss * (1 - alpha) + losses[i] * alpha
        rsi_rev.append(_rsi(avg_gain, avg_loss))

    # 최신순으로 다시 뒤집기
    return list(reversed(rsi_rev))


# ──────────────────────────────────────────────────────────────
# 분봉 조회 (ka10080)
# ──────────────────────────────────────────────────────────────

async def fetch_minute_candles(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
) -> list[dict]:
    """
    ka10080 주식분봉차트조회요청.

    Args:
        token:     Bearer 인증 토큰
        stk_cd:    종목코드 (예: "005930")
        tic_scope: 틱범위 ("1","3","5","10","15","30","45","60")

    Returns:
        분봉 리스트 (최신순, index 0 = 가장 최근 봉).
        오류 시 빈 리스트.

    Response 필드:
        cur_prc(종가), open_pric, high_pric, low_pric,
        trde_qty(거래량), cntr_tm(체결시간 YYYYMMDDHHmmss)
    """
    key = (stk_cd, tic_scope)
    entry = _MIN_CANDLE_CACHE.get(key)
    if entry and _time.monotonic() < entry[1]:
        logger.debug("[rsi] 분봉 캐시 히트 [%s/%s]", stk_cd, tic_scope)
        return entry[0]

    base_dt = datetime.now().strftime("%Y%m%d")
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/chart",
                headers={
                    "api-id": "ka10080",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "stk_cd": stk_cd.strip(),
                    "tic_scope": tic_scope,
                    "upd_stkpc_tp": "1",
                    "base_dt": base_dt,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10080", logger):
                return []
            candles = data.get("stk_min_pole_chart_qry", [])
            if candles:
                _MIN_CANDLE_CACHE[key] = (
                    candles,
                    _time.monotonic() + _MIN_CACHE_TTL,
                )
            return candles
    except Exception as e:
        logger.debug("[rsi] ka10080 실패 [%s/%s]: %s", stk_cd, tic_scope, e)
        return []


# ──────────────────────────────────────────────────────────────
# 일봉 RSI
# ──────────────────────────────────────────────────────────────

async def get_rsi_daily(
    token: str,
    stk_cd: str,
    period: int = 14,
) -> RSIResult:
    """
    일봉 기반 RSI 반환 (ka10081).

    Args:
        token:  Bearer 인증 토큰
        stk_cd: 종목코드
        period: RSI 기간 (기본 14)

    Returns:
        RSIResult – rsi, rsi_prev 포함.
        데이터 부족 또는 오류 시 rsi=None.

    필요 캔들 수: period + 2 이상 (최신 2봉 RSI 비교용).
    """
    candles = await fetch_daily_candles(token, stk_cd)
    return _build_rsi_result(stk_cd, candles, period, price_key="cur_prc")


# ──────────────────────────────────────────────────────────────
# 분봉 RSI
# ──────────────────────────────────────────────────────────────

async def get_rsi_minute(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
    period: int = 14,
) -> RSIResult:
    """
    분봉 기반 RSI 반환 (ka10080).

    Args:
        token:     Bearer 인증 토큰
        stk_cd:    종목코드
        tic_scope: 분봉 단위 ("1","3","5","10","15","30","45","60")
        period:    RSI 기간 (기본 14)

    Returns:
        RSIResult – rsi, rsi_prev 포함.
    """
    candles = await fetch_minute_candles(token, stk_cd, tic_scope)
    return _build_rsi_result(stk_cd, candles, period, price_key="cur_prc")


# ──────────────────────────────────────────────────────────────
# 내부 공통 빌더
# ──────────────────────────────────────────────────────────────

def _build_rsi_result(
    stk_cd: str,
    candles: list[dict],
    period: int,
    price_key: str = "cur_prc",
) -> RSIResult:
    closes: list[float] = []
    for c in candles:
        p = _safe_price(c.get(price_key))
        if p > 0:
            closes.append(p)

    if len(closes) < period + 2:
        return RSIResult(stk_cd=stk_cd, period=period)

    rsi_vals = calc_rsi(closes, period)
    rsi_latest = rsi_vals[0] if rsi_vals[0] != 0.0 else None
    rsi_prev   = rsi_vals[1] if len(rsi_vals) > 1 and rsi_vals[1] != 0.0 else None

    return RSIResult(
        stk_cd=stk_cd,
        period=period,
        rsi=rsi_latest,
        rsi_prev=rsi_prev,
    )
