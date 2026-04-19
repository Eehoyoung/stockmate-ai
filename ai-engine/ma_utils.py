from __future__ import annotations
"""
ma_utils.py
이동평균선 유틸리티 – ka10081 주식일봉차트 기반

MA5/MA20/MA60/MA120 계산, 정배열 판단, 지지/저항 근접도 검사,
골든크로스·눌림목·박스권 돌파 감지 헬퍼 제공.

모든 함수는 실패 시 안전 기본값을 반환하여 호출처의 예외 처리 부담을 줄인다.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from http_utils import validate_kiwoom_response, kiwoom_client

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_DEFAULT_TIMEOUT = 10.0
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))


# ──────────────────────────────────────────────────────────────
# MAContext – 이동평균 컨텍스트 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class MAContext:
    """ka10081 일봉 기반 이동평균 컨텍스트"""
    stk_cd:   str   = ""
    cur_prc:  float = 0.0          # 최근 종가 (index 0)
    ma5:      Optional[float] = None
    ma20:     Optional[float] = None
    ma60:     Optional[float] = None
    ma120:    Optional[float] = None
    vol_ma20: Optional[float] = None  # 거래량 20일 평균

    @property
    def valid(self) -> bool:
        """MA20 이상 유효 데이터 보유 여부"""
        return self.ma20 is not None

    @property
    def is_bullish_aligned(self) -> bool:
        """정배열: MA5 > MA20 > MA60 (상승 추세 최소 조건)"""
        return bool(self.ma5 and self.ma20 and self.ma60
                    and self.ma5 > self.ma20 > self.ma60)

    @property
    def is_above_ma20(self) -> bool:
        """현재가 ≥ MA20"""
        return bool(self.ma20 and self.cur_prc >= self.ma20)

    @property
    def is_above_ma60(self) -> bool:
        """현재가 ≥ MA60"""
        return bool(self.ma60 and self.cur_prc >= self.ma60)

    def pct_from_ma20(self) -> Optional[float]:
        """(현재가 - MA20) / MA20 × 100 (%)
        양수 = MA20 위, 음수 = MA20 아래"""
        if self.ma20 and self.ma20 > 0:
            return (self.cur_prc - self.ma20) / self.ma20 * 100
        return None

    def pct_from_ma60(self) -> Optional[float]:
        if self.ma60 and self.ma60 > 0:
            return (self.cur_prc - self.ma60) / self.ma60 * 100
        return None

    def near_ma_support(self, ma_val: Optional[float],
                        tolerance_pct: float = 5.0) -> bool:
        """현재가가 ma_val 위 0% ~ tolerance_pct% 이내 (지지선 근접 매수 구간)"""
        if ma_val and ma_val > 0:
            d = (self.cur_prc - ma_val) / ma_val * 100
            return 0.0 <= d <= tolerance_pct
        return False

    def is_overextended(self, threshold_pct: float = 25.0) -> bool:
        """MA20 대비 threshold_pct% 이상 이격 (과열·버블권 진입 경보)"""
        d = self.pct_from_ma20()
        return d is not None and d > threshold_pct


# ──────────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────────

def _calc_ma(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return sum(prices[:period]) / period


def _safe_price(raw) -> float:
    try:
        return abs(float(str(raw).replace(",", "").replace("+", "") or "0"))
    except (ValueError, TypeError):
        return 0.0


def _safe_vol(raw) -> float:
    try:
        return float(str(raw).replace(",", "").replace("+", "") or "0")
    except (ValueError, TypeError):
        return 0.0


# ──────────────────────────────────────────────────────────────
# ka10081 일봉 조회 (인메모리 TTL 캐시)
# ──────────────────────────────────────────────────────────────

import time as _time

# 캐시: {stk_cd: (candles, expire_at)}
# 일봉 데이터는 장 중 변하지 않으므로 1시간 캐시 적용
_CANDLE_CACHE: dict[str, tuple[list[dict], float]] = {}
_CANDLE_CACHE_TTL = int(os.getenv("MA_CACHE_TTL_SEC", "3600"))


def _candle_cache_get(stk_cd: str) -> list[dict] | None:
    entry = _CANDLE_CACHE.get(stk_cd)
    if entry and _time.monotonic() < entry[1]:
        return entry[0]
    return None


def _candle_cache_set(stk_cd: str, candles: list[dict]) -> None:
    _CANDLE_CACHE[stk_cd] = (candles, _time.monotonic() + _CANDLE_CACHE_TTL)


async def fetch_daily_candles(token: str, stk_cd: str, target_count: int = 120) -> list[dict]:
    """
    ka10081 주식일봉차트 조회 - 연속조회 지원
    :param stk_cd:
    :param token:
    :param target_count: 최소로 확보하고자 하는 봉 수 (기본 120봉)
    """
    cached = _candle_cache_get(stk_cd)
    if cached is not None and len(cached) >= target_count:
        return cached

    all_candles = []
    cont_yn = "N"
    next_key = ""
    base_dt = datetime.now().strftime("%Y%m%d")

    async with kiwoom_client() as client:
        while len(all_candles) < target_count:
            headers = {
                "api-id": "ka10081",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
                "cont-yn": cont_yn,
                "next-key": next_key
            }

            body = {
                "stk_cd": stk_cd.strip(),
                "base_dt": base_dt,
                "upd_stkpc_tp": "1"
            }

            try:
                resp = await client.post(
                    f"{KIWOOM_BASE_URL}/api/dostk/chart",
                    headers=headers,
                    json=body
                )
                resp.raise_for_status()
                data = resp.json()

                if not validate_kiwoom_response(data, "ka10081", logger):
                    break

                candles = data.get("stk_dt_pole_chart_qry", [])
                if not candles:
                    break

                all_candles.extend(candles)

                # 응답 헤더에서 연속조회 정보 추출
                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "")

                if cont_yn != "Y" or not next_key:
                    break

                # API 호출 간격 준수 (연속조회 시에도 과부하 방지)
                import asyncio
                await asyncio.sleep(_API_INTERVAL)

            except Exception as e:
                logger.error(f"[ma] ka10081 연속조회 중 오류 [%s]: %s", stk_cd, e)
                break

    if all_candles:
        _candle_cache_set(stk_cd, all_candles)

    return all_candles


# ──────────────────────────────────────────────────────────────
# 이동평균 컨텍스트 조회
# ──────────────────────────────────────────────────────────────

async def get_ma_context(token: str, stk_cd: str) -> MAContext:
    """
    종목의 이동평균 컨텍스트 반환 (ka10081 기반).
    실패 시 ctx.valid = False 인 빈 MAContext 반환.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    if not candles:
        return MAContext(stk_cd=stk_cd)

    closes: list[float] = []
    vols:   list[float] = []
    for c in candles:
        p = _safe_price(c.get("cur_prc"))
        v = _safe_vol(c.get("trde_qty"))
        if p > 0:
            closes.append(p)
            vols.append(v)

    if not closes:
        return MAContext(stk_cd=stk_cd)

    return MAContext(
        stk_cd=stk_cd,
        cur_prc=closes[0],
        ma5=_calc_ma(closes, 5),
        ma20=_calc_ma(closes, 20),
        ma60=_calc_ma(closes, 60),
        ma120=_calc_ma(closes, 120),
        vol_ma20=_calc_ma(vols, 20),
    )


# ──────────────────────────────────────────────────────────────
# 패턴 감지 헬퍼 (candles 직접 수신 – API 재호출 없음)
# ──────────────────────────────────────────────────────────────

def detect_golden_cross(candles: list[dict], lookback_days: int = 3) -> tuple[bool, bool, float]:
    """
    최근 n일 이내에 골든크로스가 발생했는지 확인
    """
    closes = [_safe_price(c.get("cur_prc")) for c in candles]
    if len(closes) < 25: return False, False, 0.0

    # 1. 오늘 기준 이격률 계산
    ma5_now = sum(closes[:5]) / 5
    ma20_now = sum(closes[:20]) / 20
    gap_pct = (ma5_now / ma20_now - 1) * 100 if ma20_now > 0 else 0.0

    # 2. 오늘 발생 여부
    is_today = (sum(closes[0:5])/5 > sum(closes[0:20])/20) and \
               (sum(closes[1:6])/5 <= sum(closes[1:21])/20)

    # 3. 최근 n일 내 발생 여부
    is_recent = False
    for i in range(lookback_days):
        m5_t = sum(closes[i:i+5]) / 5
        m20_t = sum(closes[i:i+20]) / 20
        m5_y = sum(closes[i+1:i+6]) / 5
        m20_y = sum(closes[i+1:i+21]) / 20
        if m5_t > m20_t and m5_y <= m20_y:
            is_recent = True
            break

    return is_today, (is_recent and gap_pct <= 5.0), gap_pct


def detect_pullback_setup(candles: list[dict]) -> tuple[bool, float, float]:
    """
    정배열 눌림목 감지 (일봉 기반).

    반환: (is_setup, pct_from_ma5, pct_from_ma20)
    - is_setup      : 정배열 + 현재가 MA5 근접(-3%~+3%) 조건 만족 여부
    - pct_from_ma5  : MA5 대비 현재가 위치 (%)
    - pct_from_ma20 : MA20 대비 현재가 위치 (%)
    """
    closes: list[float] = []
    for c in candles:
        p = _safe_price(c.get("cur_prc"))
        if p > 0:
            closes.append(p)

    if len(closes) < 61:
        return False, 0.0, 0.0

    cur  = closes[0]
    ma5  = sum(closes[:5])  / 5
    ma20 = sum(closes[:20]) / 20
    ma60 = sum(closes[:60]) / 60

    pct_ma5  = (cur - ma5)  / ma5  * 100 if ma5  > 0 else 0.0
    pct_ma20 = (cur - ma20) / ma20 * 100 if ma20 > 0 else 0.0

    if not (ma5 > ma20 > ma60):         # 정배열 미충족
        return False, pct_ma5, pct_ma20
    if not (-3.0 <= pct_ma5 <= 3.0):    # MA5 근접 구간 이탈
        return False, pct_ma5, pct_ma20

    return True, pct_ma5, pct_ma20


def detect_box_breakout(candles: list[dict],
                        box_period: int = 15,
                        max_range_pct: float = 8.0,
                        vol_mul: float = 2.0) -> tuple[bool, float]:
    """
    박스권 돌파 감지 (일봉 기반).

    반환: (is_breakout, box_range_pct)
    - is_breakout    : 박스권 상단 돌파 + 양봉 + 거래량 급증 동시 충족
    - box_range_pct  : 박스권 폭 (%)
    """
    if len(candles) < box_period + 2:
        return False, 0.0

    today  = candles[0]
    box_cs = candles[1:box_period + 1]

    t_close = _safe_price(today.get("cur_prc"))
    t_open  = _safe_price(today.get("open_pric"))
    t_high  = _safe_price(today.get("high_pric"))
    t_vol   = _safe_vol(today.get("trde_qty"))

    if t_close <= 0 or t_open <= 0:
        return False, 0.0

    highs, lows, vols = [], [], []
    for c in box_cs:
        h = _safe_price(c.get("high_pric"))
        l = _safe_price(c.get("low_pric"))
        v = _safe_vol(c.get("trde_qty"))
        if h > 0 and l > 0:
            highs.append(h)
            lows.append(l)
            vols.append(v)

    if not highs:
        return False, 0.0

    box_high = max(highs)
    box_low  = min(lows)
    box_range_pct = (box_high - box_low) / box_low * 100 if box_low > 0 else 0.0

    # 박스권 확인
    if box_range_pct > max_range_pct:
        return False, box_range_pct

    # 돌파 조건: 오늘 종가 > 박스 상단 + 양봉
    if t_close <= box_high or t_close <= t_open:
        return False, box_range_pct

    # 거래량 급증
    vol_avg = sum(vols) / len(vols) if vols else 0
    if vol_avg > 0 and t_vol < vol_avg * vol_mul:
        return False, box_range_pct

    return True, box_range_pct
