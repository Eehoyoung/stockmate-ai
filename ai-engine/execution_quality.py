from __future__ import annotations
"""
execution_quality.py
추격매수 공통 품질 필터 모듈.

역할:
- 호가(ka10004)·분봉(ka10080) 데이터를 받아 추격 리스크 점수를 산출한다.
- 전략 파일에서 dict 형태로 hoga_data / candle_data를 전달받으며, Redis 없이 동작한다.
- feature flag에 따라 shadow(필드 기록만) 또는 hard_gate(REJECT 시 탈락) 모드로 동작한다.

Feature flags:
  ENABLE_EXECUTION_QUALITY_SHADOW   = true  (기본값)
    → REJECT여도 전략에서 None 반환하지 않음. payload에 필드만 포함.
  ENABLE_EXECUTION_QUALITY_HARD_GATE = false (기본값)
    → true로 변경 시 REJECT이면 전략이 해당 종목을 탈락(None 반환)시킬 수 있음.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Feature flags ─────────────────────────────────────────────────────────────
ENABLE_EXECUTION_QUALITY_SHADOW: bool = (
    os.getenv("ENABLE_EXECUTION_QUALITY_SHADOW", "true").lower() == "true"
)
ENABLE_EXECUTION_QUALITY_HARD_GATE: bool = (
    os.getenv("ENABLE_EXECUTION_QUALITY_HARD_GATE", "false").lower() == "true"
)

# ── 기본 임계값 상수 ──────────────────────────────────────────────────────────
_SPREAD_REJECT_PCT: float = 0.5        # 스프레드 reject 기준 (%)
_SPREAD_CAUTION_PCT: float = 0.3       # 스프레드 caution 기준 (%)
_SELL_WALL_REJECT_RATIO: float = 3.0   # 매도 총잔량 / 매수 총잔량 비율 reject
_SELL_WALL_CAUTION_RATIO: float = 2.0  # 매도/매수 caution 비율
_HIGH_REJECTION_REJECT_PCT: float = 5.0   # 당일 고가 대비 현재가 밀림 reject (%)
_HIGH_REJECTION_CAUTION_PCT: float = 3.0  # 당일 고가 대비 현재가 밀림 caution (%)
_FIRST_LOW_VWAP_MARGIN: float = 0.002  # VWAP 이탈 판정 마진 (0.2%)

# ── 등급 경계 ──────────────────────────────────────────────────────────────────
_GRADE_A_MAX: int = 30
_GRADE_B_MAX: int = 55
_GRADE_C_MAX: int = 75


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """부호·콤마 제거 후 float 변환. 실패 시 default 반환."""
    try:
        return float(str(value).replace("+", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _calc_spread_pct(hoga_data: dict) -> Optional[float]:
    """
    ka10004 호가 데이터에서 스프레드 % 산출.
    매도1호가(sel_1st_pre_bid) / 매수1호가(buy_1st_pre_bid) 기반.
    """
    try:
        ask1 = abs(_safe_float(hoga_data.get("sel_1st_pre_bid", 0)))
        bid1 = abs(_safe_float(hoga_data.get("buy_1st_pre_bid", 0)))
        if ask1 <= 0 or bid1 <= 0:
            return None
        return (ask1 - bid1) / bid1 * 100.0
    except Exception:
        return None


def _calc_depth_score(hoga_data: dict) -> int:
    """
    호가 깊이 점수 0~100.
    tot_buy_req / tot_sel_req 비율로 산출.
    매수잔량이 매도잔량보다 많을수록 점수 높음.
    """
    try:
        buy = _safe_float(hoga_data.get("tot_buy_req", 0))
        sel = _safe_float(hoga_data.get("tot_sel_req", 0))
        if sel <= 0:
            return 50
        ratio = buy / sel
        # ratio 1.5 이상 → 100점, 0.5 이하 → 0점, 선형 보간
        score = int(min(100, max(0, (ratio - 0.5) / 1.0 * 100)))
        return score
    except Exception:
        return 50


def _calc_sell_wall_score(hoga_data: dict) -> int:
    """
    매도벽 강도 점수 0~100. 높을수록 위험.
    tot_sel_req / tot_buy_req 비율 기반.
    """
    try:
        buy = _safe_float(hoga_data.get("tot_buy_req", 0))
        sel = _safe_float(hoga_data.get("tot_sel_req", 0))
        if buy <= 0:
            return 50
        ratio = sel / buy
        # ratio 3.0 이상 → 100점(위험), 0.5 이하 → 0점, 선형
        score = int(min(100, max(0, (ratio - 0.5) / 2.5 * 100)))
        return score
    except Exception:
        return 50


def _calc_vwap(candles: list[dict]) -> Optional[float]:
    """
    ka10080 분봉 데이터로 VWAP 계산.
    VWAP = sum(price * volume) / sum(volume)
    price = (high + low + close) / 3
    """
    try:
        cum_pv = 0.0
        cum_vol = 0.0
        for candle in candles:
            h = abs(_safe_float(candle.get("high_pric", 0)))
            l = abs(_safe_float(candle.get("low_pric", 0)))
            c = abs(_safe_float(candle.get("cur_prc", 0)))
            v = abs(_safe_float(candle.get("trde_qty", 0)))
            if h <= 0 or l <= 0 or c <= 0 or v <= 0:
                continue
            typical = (h + l + c) / 3.0
            cum_pv += typical * v
            cum_vol += v
        if cum_vol <= 0:
            return None
        return cum_pv / cum_vol
    except Exception:
        return None


def _calc_first_low_break(
    candles: list[dict],
    current_price: float,
    vwap: Optional[float],
    n_candles: int = 3,
) -> bool:
    """
    첫 1~3분봉 저가 이탈 후 VWAP 아래 여부 판정.
    ka10080 candles는 최신봉이 index 0인 역순 배열 가정.
    """
    try:
        if len(candles) < n_candles:
            return False
        # 최신 n_candles 봉에서 저가 최소값
        recent = candles[:n_candles]
        first_lows = [abs(_safe_float(c.get("low_pric", 0))) for c in recent]
        first_lows = [v for v in first_lows if v > 0]
        if not first_lows:
            return False
        first_low_min = min(first_lows)
        # 현재가가 첫봉 저가군 아래로 이탈 AND VWAP 아래
        if current_price < first_low_min:
            if vwap and current_price < vwap * (1 - _FIRST_LOW_VWAP_MARGIN):
                return True
        return False
    except Exception:
        return False


def _calc_upper_shadow_pct(candles: list[dict]) -> Optional[float]:
    """
    최신봉(index 0)의 윗꼬리 비율 계산.
    upper_shadow_pct = (high - close) / (high - low) * 100
    """
    try:
        if not candles:
            return None
        cur = candles[0]
        h = abs(_safe_float(cur.get("high_pric", 0)))
        l = abs(_safe_float(cur.get("low_pric", 0)))
        c = abs(_safe_float(cur.get("cur_prc", 0)))
        if h <= 0 or h <= l:
            return None
        shadow = h - c
        candle_range = h - l
        if candle_range <= 0:
            return 0.0
        return shadow / candle_range * 100.0
    except Exception:
        return None


def _calc_close_position_pct(
    current_price: float,
    candles: list[dict],
) -> Optional[float]:
    """
    당일 고가 대비 현재가 위치 % (음수 = 고가에서 밀림).
    close_position_pct = (current_price - day_high) / day_high * 100
    """
    try:
        if not candles:
            return None
        # 분봉 전체에서 당일 고가 추출
        day_high = max(
            abs(_safe_float(c.get("high_pric", 0))) for c in candles
        )
        if day_high <= 0:
            return None
        return (current_price - day_high) / day_high * 100.0
    except Exception:
        return None


def _calc_vwap_position(
    current_price: float,
    vwap: Optional[float],
) -> str:
    """VWAP 대비 현재가 위치."""
    if vwap is None or vwap <= 0:
        return "UNKNOWN"
    return "ABOVE_VWAP" if current_price >= vwap else "BELOW_VWAP"


# ─────────────────────────────────────────────────────────────────────────────
# 전략별 추가 컨텍스트 처리
# ─────────────────────────────────────────────────────────────────────────────

def _apply_strategy_context(
    score: int,
    strategy_id: str,
    extra: dict,
    upper_shadow_pct: Optional[float],
    close_position_pct: Optional[float],
    candles: list[dict],
) -> tuple[int, list[str]]:
    """
    전략별 추가 점수 조정.
    반환: (조정된 score, 추가 reject_reasons)
    """
    reasons: list[str] = []

    sid = strategy_id.upper()

    # S1: 갭 구간 감점
    if "S1" in sid:
        gap_pct = extra.get("gap_pct", 0.0) if extra else 0.0
        if gap_pct >= 12.0:
            score += 20   # 과열 갭 → 점수 증가(위험)
            reasons.append("gap_overheat_12pct")
        elif gap_pct >= 8.0:
            score += 10

    # S4: 윗꼬리 감점
    if "S4" in sid:
        if upper_shadow_pct is not None:
            if upper_shadow_pct >= 30.0:
                score += 20
                reasons.append("upper_shadow_ge30pct")
            elif upper_shadow_pct >= 20.0:
                score += 10

    # S10: 고가 이탈 감점/reject
    if "S10" in sid:
        if close_position_pct is not None:
            if close_position_pct <= -5.0:
                score += 25
                reasons.append("high_rejection_ge5pct")
            elif close_position_pct <= -3.0:
                score += 12

    # S13: 박스 상단 대비 추격 감점
    if "S13" in sid:
        box_breakout_ext = extra.get("box_breakout_extension_pct", 0.0) if extra else 0.0
        if box_breakout_ext > 3.0:
            score += 15
            reasons.append("box_breakout_extension_gt3pct")

    return score, reasons


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

def assess_execution_quality(
    stk_cd: str,
    current_price: float,
    hoga_data: Optional[dict],
    candle_data: Optional[dict],
    strategy_id: str,
    extra: Optional[dict] = None,
) -> dict:
    """
    추격매수 공통 품질 필터.

    Parameters
    ----------
    stk_cd : str
        종목코드.
    current_price : float
        현재가.
    hoga_data : dict | None
        ka10004 응답 dict. None이면 호가 관련 필드는 기본값으로 처리.
    candle_data : dict | None
        ka10080 응답 dict. 응답 최상위에 stk_min_pole_chart_qry 키를 포함한 형태.
        None이면 분봉 관련 필드는 기본값으로 처리.
    strategy_id : str
        전략 식별자. "S1", "S4", "S10", "S13" 등.
    extra : dict | None
        전략별 추가 데이터. gap_pct, box_breakout_extension_pct 등.

    Returns
    -------
    dict
        chase_risk_score, execution_quality, spread_pct, depth_score,
        sell_wall_score, vwap_position, first_low_break, breakout_line_break,
        upper_shadow_pct, close_position_pct, reject_reason 포함.
    """
    hoga = hoga_data or {}
    candles: list[dict] = []
    if candle_data:
        raw_candles = candle_data.get("stk_min_pole_chart_qry", [])
        if isinstance(raw_candles, list):
            candles = raw_candles

    reject_reasons: list[str] = []
    chase_risk_score: int = 0

    # ── 1. 호가 스프레드 ────────────────────────────────────────────────────
    if hoga:
        spread_pct = _calc_spread_pct(hoga)
        depth_score = _calc_depth_score(hoga)
        sell_wall_score = _calc_sell_wall_score(hoga)
    else:
        spread_pct = None
        depth_score = 50
        sell_wall_score = 50

    if spread_pct is not None:
        if spread_pct > _SPREAD_REJECT_PCT:
            chase_risk_score += 30
            reject_reasons.append(f"spread_too_wide_{spread_pct:.2f}pct")
        elif spread_pct > _SPREAD_CAUTION_PCT:
            chase_risk_score += 12

    # ── 2. 매도벽 강도 ───────────────────────────────────────────────────────
    if sell_wall_score > 80:
        chase_risk_score += 25
        reject_reasons.append("sell_wall_score_gt80")
    elif sell_wall_score > 65:
        chase_risk_score += 10

    # ── 3. 호가 깊이 역점수 ─────────────────────────────────────────────────
    # depth가 낮을수록 위험
    if depth_score < 30:
        chase_risk_score += 10
    elif depth_score > 60:
        chase_risk_score -= 5  # 깊이가 깊으면 소폭 완화

    # ── 4. 분봉 기반 지표 ───────────────────────────────────────────────────
    if candles:
        vwap = _calc_vwap(candles)
        vwap_position = _calc_vwap_position(current_price, vwap)
        first_low_break = _calc_first_low_break(candles, current_price, vwap)
        upper_shadow_pct = _calc_upper_shadow_pct(candles)
        close_position_pct = _calc_close_position_pct(current_price, candles)
    else:
        vwap = None
        vwap_position = "UNKNOWN"
        first_low_break = False
        upper_shadow_pct = None
        close_position_pct = None

    # first_low_break 페널티
    if first_low_break:
        chase_risk_score += 30
        reject_reasons.append("first_low_break_below_vwap")

    # close_position_pct: 당일 고가 대비 현재가 밀림
    if close_position_pct is not None:
        if close_position_pct < -5.0:
            chase_risk_score += 20
            reject_reasons.append(f"high_rejection_{abs(close_position_pct):.1f}pct")
        elif close_position_pct < -3.0:
            chase_risk_score += 8

    # ── 5. 윗꼬리 페널티 (기본 분봉 기반) ──────────────────────────────────
    if upper_shadow_pct is not None:
        if upper_shadow_pct >= 40.0:
            chase_risk_score += 15
        elif upper_shadow_pct >= 25.0:
            chase_risk_score += 7

    # ── 6. 전략별 추가 컨텍스트 조정 ────────────────────────────────────────
    chase_risk_score, extra_reasons = _apply_strategy_context(
        chase_risk_score,
        strategy_id,
        extra or {},
        upper_shadow_pct,
        close_position_pct,
        candles,
    )
    reject_reasons.extend(extra_reasons)

    # ── 7. 점수 클램프 및 등급 결정 ─────────────────────────────────────────
    chase_risk_score = max(0, min(100, chase_risk_score))

    if reject_reasons or chase_risk_score > _GRADE_C_MAX:
        execution_quality = "REJECT"
    elif chase_risk_score > _GRADE_B_MAX:
        execution_quality = "C"
    elif chase_risk_score > _GRADE_A_MAX:
        execution_quality = "B"
    else:
        execution_quality = "A"

    # REJECT 조건이지만 reject_reasons가 비어도 점수 기반 REJECT이면 유지
    if chase_risk_score > _GRADE_C_MAX and execution_quality != "REJECT":
        execution_quality = "REJECT"

    reject_reason_str = "; ".join(reject_reasons) if reject_reasons else None

    result = {
        "chase_risk_score": chase_risk_score,
        "execution_quality": execution_quality,
        "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
        "depth_score": depth_score,
        "sell_wall_score": sell_wall_score,
        "vwap_position": vwap_position,
        "first_low_break": first_low_break,
        "breakout_line_break": False,  # 향후 확장: 돌파선 재이탈 탐지
        "upper_shadow_pct": round(upper_shadow_pct, 1) if upper_shadow_pct is not None else None,
        "close_position_pct": round(close_position_pct, 2) if close_position_pct is not None else None,
        "reject_reason": reject_reason_str,
    }

    if execution_quality == "REJECT":
        logger.debug(
            "[execution_quality] %s %s REJECT score=%d reasons=%s",
            strategy_id, stk_cd, chase_risk_score, reject_reasons,
        )

    return result


def should_hard_reject(eq_result: dict) -> bool:
    """
    HARD_GATE 모드에서 해당 종목을 탈락시킬지 판단.

    SHADOW=true이면 항상 False(탈락하지 않음).
    HARD_GATE=true이고 SHADOW=false이면 REJECT 등급에서 True 반환.
    """
    if ENABLE_EXECUTION_QUALITY_SHADOW:
        return False
    if ENABLE_EXECUTION_QUALITY_HARD_GATE:
        return eq_result.get("execution_quality") == "REJECT"
    return False
