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

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")
_DEFAULT_TIMEOUT = 10.0


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
# ka10081 일봉 조회
# ──────────────────────────────────────────────────────────────

async def fetch_daily_candles(token: str, stk_cd: str) -> list[dict]:
    """
    ka10081 주식일봉차트 조회 – 최신순 반환 (index 0 = 오늘/가장 최근).
    오류·데이터 없음 시 빈 리스트 반환.
    """
    base_dt = datetime.now().strftime("%Y%m%d")
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/chart",
                headers={
                    "api-id": "ka10081",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd.strip(), "base_dt": base_dt, "upd_stkpc_tp": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") and int(str(data.get("status", 200))) >= 400:
                logger.debug("[ma] ka10081 오류 [%s]: %s", stk_cd, data.get("message"))
                return []
            return data.get("stk_dt_pole_chart_qry", [])
    except Exception as e:
        logger.debug("[ma] ka10081 실패 [%s]: %s", stk_cd, e)
        return []


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

def detect_golden_cross(candles: list[dict]) -> tuple[bool, bool, float]:
    """
    골든크로스 감지 (일봉 기반).

    반환: (crossed_today, near_cross, gap_pct)
    - crossed_today : 오늘 MA5 > MA20 크로스오버 첫 발생 여부
    - near_cross    : MA5 > MA20 이며 이격 ≤ 5% (최근 크로스 유효 범위)
    - gap_pct       : MA5/MA20 이격률 (%)
    """
    closes: list[float] = []
    for c in candles:
        p = _safe_price(c.get("cur_prc"))
        if p > 0:
            closes.append(p)

    if len(closes) < 22:
        return False, False, 0.0

    ma5_t   = sum(closes[:5])  / 5
    ma5_y   = sum(closes[1:6]) / 5
    ma20_t  = sum(closes[:20]) / 20
    ma20_y  = sum(closes[1:21]) / 20

    gap_pct = (ma5_t / ma20_t - 1) * 100 if ma20_t > 0 else 0.0

    crossed_today = (ma5_t > ma20_t) and (ma5_y <= ma20_y)
    near_cross    = (ma5_t > ma20_t) and (gap_pct <= 5.0)

    return crossed_today, near_cross, gap_pct


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
