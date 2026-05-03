from __future__ import annotations
"""
box_zone_engine.py
매수/매도 박스(Zone) 계산 엔진

지지·저항 클러스터를 단일 포인트가 아닌 가격대(Zone)로 표현한다.
트레이더는 존 하단부터 분할 진입, 존 상단 도달 전 분할 청산하는 방식으로 활용한다.

Zone 계산 원칙:
  매수 박스 = cur_prc 아래 지지 레벨 클러스터 (MA, BB 하단, 스윙 저점)
  매도 박스 = cur_prc 위 저항 레벨 클러스터 (MA120, BB 상단, 스윙 고점, Fib)
  클러스터링 = 2% 이내 레벨 병합 → 가장 많은 anchor를 가진 클러스터가 최강 존

Phase 1 대상: S8/S9/S13/S14/S15 (스윙 전략)
Phase 2 예정: S7(Ichimoku), S10(신고가), S11(외인 연속)
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────

CLUSTER_PCT = float(os.getenv("ZONE_CLUSTER_PCT", "2.0"))   # 2% 이내 레벨 → 병합
SL_BUFFER   = float(os.getenv("ZONE_SL_BUFFER",   "0.01"))  # zone SL = buy_zone.low × (1 - 0.01)
MIN_ZONE_THICKNESS_PCT = 0.3   # 존 두께 최소 0.3% (너무 얇으면 의미 없음)


# ──────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class TradingZone:
    """지지 또는 저항 존 (가격대)"""
    low:           float
    high:          float
    center:        float
    anchors:       list[str] = field(default_factory=list)
    strength:      int       = 1      # 1~5, anchor 수 기반
    thickness_pct: float     = 0.0   # (high - low) / center × 100

    def to_dict(self) -> dict:
        return {
            "low":           round(self.low),
            "high":          round(self.high),
            "center":        round(self.center),
            "anchors":       list(self.anchors),
            "strength":      self.strength,
            "thickness_pct": round(self.thickness_pct, 3),
        }


# ──────────────────────────────────────────────────────────────
# 내부 유틸: 레벨 클러스터링
# ──────────────────────────────────────────────────────────────

def _cluster_levels(
    levels: list[tuple[float, str]],
    cluster_pct: float = CLUSTER_PCT,
) -> list[tuple[float, list[str]]]:
    """
    가격 레벨 리스트를 cluster_pct(%) 이내 근접 레벨끼리 병합한다.

    Args:
        levels: [(price, anchor_name), ...] — 중복 가능
        cluster_pct: 이 비율(%) 이내면 같은 클러스터로 병합

    Returns:
        [(merged_price, [anchor_names]), ...] 오름차순
        merged_price = 클러스터 내 평균가
    """
    if not levels:
        return []

    # 오름차순 정렬
    sorted_lvls = sorted(levels, key=lambda x: x[0])

    clusters: list[tuple[float, list[str]]] = []
    for price, name in sorted_lvls:
        if price <= 0:
            continue
        if clusters:
            prev_price, prev_names = clusters[-1]
            # 직전 클러스터와 2% 이내이면 병합
            if abs(price - prev_price) / prev_price * 100 <= cluster_pct:
                # 병합: 가중 평균 (모두 동등 weight)
                n = len(prev_names)
                merged_price = (prev_price * n + price) / (n + 1)
                clusters[-1] = (merged_price, prev_names + [name])
                continue
        clusters.append((price, [name]))

    return clusters


def _best_cluster(
    clusters: list[tuple[float, list[str]]],
    prefer_closest: float = 0.0,
) -> Optional[tuple[float, list[str]]]:
    """
    클러스터 중 가장 많은 anchor를 가진 것을 반환.
    동수일 때 prefer_closest(가격)에 더 가까운 클러스터 우선.
    """
    if not clusters:
        return None
    return max(
        clusters,
        key=lambda c: (len(c[1]), -abs(c[0] - prefer_closest) if prefer_closest else 0),
    )


def _zone_from_cluster(
    cluster: tuple[float, list[str]],
    atr: Optional[float] = None,
) -> TradingZone:
    """클러스터 (price, anchors) → TradingZone 변환"""
    center, anchors = cluster
    # 존 너비: ATR × 0.3 또는 center × 0.5% (더 큰 쪽), 최소 MIN_ZONE_THICKNESS_PCT
    half_width = max(
        (atr * 0.3) if atr else 0.0,
        center * 0.005,
        center * (MIN_ZONE_THICKNESS_PCT / 100 / 2),
    )
    low  = center - half_width
    high = center + half_width
    thickness_pct = (high - low) / center * 100 if center > 0 else 0.0
    strength = min(5, max(1, len(anchors)))
    return TradingZone(
        low=low, high=high, center=center,
        anchors=anchors, strength=strength,
        thickness_pct=round(thickness_pct, 3),
    )


# ──────────────────────────────────────────────────────────────
# 공개 API: 매수 박스 계산
# ──────────────────────────────────────────────────────────────

def calc_buy_zone(
    cur_prc: float,
    *,
    highs:    list[float],
    lows:     list[float],
    ma5:      Optional[float] = None,
    ma20:     Optional[float] = None,
    ma60:     Optional[float] = None,
    bb_lower: Optional[float] = None,
    atr:      Optional[float] = None,
) -> Optional[TradingZone]:
    """
    cur_prc 아래 지지 클러스터 → 매수 박스 계산.

    수집 대상:
      - MA5, MA20, MA60 (cur_prc 아래인 것만)
      - 볼린저 하단 (cur_prc 아래인 것만)
      - 스윙 저점 최근 3개 (tp_sl_engine.find_swing_lows 재사용)

    Returns:
        TradingZone 또는 None (지지 레벨 없음)
    """
    # tp_sl_engine 내 함수 재사용 (lazy import — circular 방지)
    from tp_sl_engine import find_swing_lows

    candidates: list[tuple[float, str]] = []

    # MA 레벨
    for val, name in [(ma5, "MA5"), (ma20, "MA20"), (ma60, "MA60")]:
        if val and 0 < val < cur_prc:
            candidates.append((val, name))

    # 볼린저 하단
    if bb_lower and 0 < bb_lower < cur_prc:
        candidates.append((bb_lower, "BB_LOWER"))

    # 스윙 저점 (가장 가까운 3개)
    swing_lows = find_swing_lows(lows, cur_prc, lookback=40, cluster_pct=1.0)
    for lvl in swing_lows[:3]:
        if 0 < lvl < cur_prc:
            candidates.append((lvl, "SWING_LOW"))

    if not candidates:
        return None

    clusters = _cluster_levels(candidates)
    if not clusters:
        return None

    best = _best_cluster(clusters, prefer_closest=cur_prc)
    if not best:
        return None

    zone = _zone_from_cluster(best, atr=atr)
    if zone.high >= cur_prc:
        # 존 상단이 현재가 이상이면 의미 없음 → 존 상단을 cur_prc × 0.995로 제한
        zone.high = cur_prc * 0.995
        if zone.high <= zone.low:
            return None

    return zone


# ──────────────────────────────────────────────────────────────
# 공개 API: 매도 박스 계산
# ──────────────────────────────────────────────────────────────

def calc_sell_zone(
    cur_prc: float,
    *,
    highs:     list[float],
    ma120:     Optional[float] = None,
    bb_upper:  Optional[float] = None,
    atr:       Optional[float] = None,
    fib_low:   Optional[float] = None,
    fib_high:  Optional[float] = None,
) -> Optional[TradingZone]:
    """
    cur_prc 위 저항 클러스터 → 1차 매도 박스 계산.

    수집 대상:
      - MA120 (cur_prc 위인 것만)
      - 볼린저 상단 (cur_prc 위인 것만)
      - 스윙 고점 최근 3개 (tp_sl_engine.find_swing_highs 재사용)
      - 피보나치 1.272/1.618 (fib_low/fib_high 제공 시)

    Returns:
        TradingZone 또는 None
    """
    from tp_sl_engine import find_swing_highs, calc_fibonacci_extension

    candidates: list[tuple[float, str]] = []

    # MA120
    if ma120 and ma120 > cur_prc:
        candidates.append((ma120, "MA120"))

    # 볼린저 상단
    if bb_upper and bb_upper > cur_prc:
        candidates.append((bb_upper, "BB_UPPER"))

    # 스윙 고점 (가장 가까운 3개)
    swing_highs = find_swing_highs(highs, cur_prc, lookback=40, cluster_pct=1.0)
    for lvl in swing_highs[:3]:
        if lvl > cur_prc:
            candidates.append((lvl, "SWING_HIGH"))

    # 피보나치 확장 (박스권 돌파 전략 등)
    if fib_low and fib_high and fib_high > fib_low:
        _, fib_1272, fib_1618 = calc_fibonacci_extension(fib_low, fib_high)
        if fib_1272 > cur_prc:
            candidates.append((fib_1272, "FIB_1.272"))
        if fib_1618 > cur_prc:
            candidates.append((fib_1618, "FIB_1.618"))

    if not candidates:
        return None

    clusters = _cluster_levels(candidates)
    if not clusters:
        return None

    # 가장 가까운 저항 클러스터 선택 (cur_prc 바로 위)
    above_clusters = [(p, a) for p, a in clusters if p > cur_prc]
    if not above_clusters:
        return None

    # 가장 cur_prc와 가까운 클러스터 (= 1차 목표)
    best = min(above_clusters, key=lambda c: c[0])

    zone = _zone_from_cluster(best, atr=atr)
    if zone.low <= cur_prc:
        zone.low = cur_prc * 1.005
        if zone.low >= zone.high:
            return None

    return zone


# ──────────────────────────────────────────────────────────────
# 공개 API: 존 기반 R:R 계산
# ──────────────────────────────────────────────────────────────

def calc_zone_rr(
    buy_zone:   TradingZone,
    sell_zone1: TradingZone,
    slip_fee:   float,
    min_rr:     float,
) -> tuple[float, bool]:
    """
    존 기반 R:R 계산 (최악 진입 기준).

    최악 진입 = buy_zone.high (존 상단에서 진입한 경우)
    SL = buy_zone.low × (1 - SL_BUFFER)  (존 이탈 = 지지 붕괴)
    TP = sell_zone1.low  (저항 존 하단 = 보수적 목표)

    슬리피지 반영:
      실효수익 = (zone_tp - zone_entry) / zone_entry - 2×slip_fee
      실효리스크 = (zone_entry - zone_sl) / zone_entry + 2×slip_fee

    Returns:
        (zone_rr, zone_rr_skip)
    """
    zone_entry = buy_zone.high
    zone_sl    = buy_zone.low * (1.0 - SL_BUFFER)
    zone_tp    = sell_zone1.low

    if zone_entry <= 0 or zone_sl <= 0 or zone_tp <= zone_entry:
        return 0.0, True

    rt = 2 * slip_fee
    reward = (zone_tp - zone_entry) / zone_entry - rt
    risk   = (zone_entry - zone_sl) / zone_entry + rt

    if risk <= 0:
        return 0.0, True

    rr = round(reward / risk, 3)
    return rr, rr < min_rr


# ──────────────────────────────────────────────────────────────
# 공개 API: 현재가 위치 레이블
# ──────────────────────────────────────────────────────────────

def cur_prc_position(cur_prc: float, buy_zone: TradingZone) -> str:
    """
    현재가가 매수 박스 내 어느 위치인지 레이블 반환.

    Returns:
        예: "박스 내부 (하단 35%)", "박스 상단 25%", "박스 미진입", "박스 상단 초과"
    """
    z_low  = buy_zone.low
    z_high = buy_zone.high

    if cur_prc < z_low:
        return "박스 미진입"
    if cur_prc > z_high:
        return "박스 상단 초과"

    zone_width = z_high - z_low
    if zone_width <= 0:
        return "박스 내부"

    top_q = z_low + 0.75 * zone_width
    pct   = (cur_prc - z_low) / zone_width * 100
    if cur_prc >= top_q:
        return f"박스 상단 25% ({pct:.0f}%)"
    return f"박스 내부 (하단 {pct:.0f}%)"


# ──────────────────────────────────────────────────────────────
# 전략별 래퍼
# ──────────────────────────────────────────────────────────────

def calc_zones_s8(
    cur_prc: float,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    ma5:      Optional[float] = None,
    ma20:     Optional[float] = None,
    ma60:     Optional[float] = None,
    bb_upper: Optional[float] = None,
    atr:      Optional[float] = None,
) -> tuple[Optional[TradingZone], Optional[TradingZone]]:
    """
    S8 골든크로스: MA5/MA20 크로스 직후 지지 존 → 매수 박스
    저항 존 = 스윙 고점 + BB 상단
    """
    buy  = calc_buy_zone(cur_prc, highs=highs, lows=lows,
                         ma5=ma5, ma20=ma20, ma60=ma60, atr=atr)
    sell = calc_sell_zone(cur_prc, highs=highs, bb_upper=bb_upper, atr=atr)
    return buy, sell


def calc_zones_s9(
    cur_prc: float,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    ma5:  Optional[float] = None,
    ma20: Optional[float] = None,
    ma60: Optional[float] = None,
    atr:  Optional[float] = None,
) -> tuple[Optional[TradingZone], Optional[TradingZone]]:
    """
    S9 눌림목: MA5 ±3% 밴드 = 이미 존 개념. MA 지지 클러스터로 형식화.
    저항 존 = 직전 스윙 고점
    """
    buy  = calc_buy_zone(cur_prc, highs=highs, lows=lows,
                         ma5=ma5, ma20=ma20, ma60=ma60, atr=atr)
    sell = calc_sell_zone(cur_prc, highs=highs, atr=atr)
    return buy, sell


def calc_zones_s13(
    cur_prc: float,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    ma20: Optional[float] = None,
    atr:  Optional[float] = None,
) -> tuple[Optional[TradingZone], Optional[TradingZone]]:
    """
    S13 박스권 돌파: 돌파 후 박스 상단이 새 지지 존으로 전환.
    매도 존 = 박스권 고저 기준 Fib 1.272/1.618
    """
    BOX_PERIOD = 15
    fib_high = max(highs[1:BOX_PERIOD + 1]) if len(highs) > BOX_PERIOD else None
    fib_low  = min(lows[1:BOX_PERIOD + 1])  if len(lows)  > BOX_PERIOD else None

    buy  = calc_buy_zone(cur_prc, highs=highs, lows=lows,
                         ma20=ma20, atr=atr)
    sell = calc_sell_zone(cur_prc, highs=highs, atr=atr,
                          fib_low=fib_low, fib_high=fib_high)
    return buy, sell


def calc_zones_s14(
    cur_prc: float,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    ma20:     Optional[float] = None,
    ma60:     Optional[float] = None,
    bb_lower: Optional[float] = None,
    atr:      Optional[float] = None,
) -> tuple[Optional[TradingZone], Optional[TradingZone]]:
    """
    S14 과매도 반등: BB 하단 ~ MA20이 자연스러운 매수 존.
    매도 존 = MA60/MA120 클러스터
    """
    buy  = calc_buy_zone(cur_prc, highs=highs, lows=lows,
                         ma20=ma20, ma60=ma60, bb_lower=bb_lower, atr=atr)
    sell = calc_sell_zone(cur_prc, highs=highs, atr=atr)
    return buy, sell


def calc_zones_s15(
    cur_prc: float,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    ma5:      Optional[float] = None,
    ma20:     Optional[float] = None,
    bb_upper: Optional[float] = None,
    atr:      Optional[float] = None,
) -> tuple[Optional[TradingZone], Optional[TradingZone]]:
    """
    S15 모멘텀 정렬: MA 정배열 구간 전체가 매수 존.
    매도 존 = BB 상단 + 스윙 고점
    """
    buy  = calc_buy_zone(cur_prc, highs=highs, lows=lows,
                         ma5=ma5, ma20=ma20, atr=atr)
    sell = calc_sell_zone(cur_prc, highs=highs, bb_upper=bb_upper, atr=atr)
    return buy, sell


# 전략 이름 → 래퍼 매핑 (tp_sl_engine에서 동적 dispatch용)
_ZONE_CALC_MAP = {
    "S8_GOLDEN_CROSS":    calc_zones_s8,
    "S9_PULLBACK_SWING":  calc_zones_s9,
    "S13_BOX_BREAKOUT":   calc_zones_s13,
    "S14_OVERSOLD_BOUNCE": calc_zones_s14,
    "S15_MOMENTUM_ALIGN": calc_zones_s15,
}
