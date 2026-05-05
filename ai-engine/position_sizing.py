from __future__ import annotations

"""
position_sizing.py

비계좌 기반 진입 강도 산출 모듈.

원칙:
  - 계좌잔고, 총자산, 주문가능금액, 계좌 리스크 %, 실제 보유 포지션 금액을 절대 사용하지 않는다.
  - 모델 상대 강도(0~100)만 산출하여 진입 사이즈 티어(SIZE_0~SIZE_4)를 결정한다.
  - ENABLE_MODEL_RELATIVE_POSITION_SIZE=false 시 queue_worker.py 에서 호출 자체를 생략한다.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ENABLE_MODEL_RELATIVE_POSITION_SIZE: bool = (
    os.getenv("ENABLE_MODEL_RELATIVE_POSITION_SIZE", "false").lower() == "true"
)

# ── 등급 매핑 ─────────────────────────────────────────────────────────────────
_TIER_MAP = [
    (90, "SIZE_4", 1.00),
    (80, "SIZE_3", 0.75),
    (70, "SIZE_2", 0.50),
    (55, "SIZE_1", 0.25),
    (0,  "SIZE_0", 0.00),
]

# ── 전략별 상한 ───────────────────────────────────────────────────────────────
STRATEGY_SIZE_CAPS: dict[str, str] = {
    "S1_GAP_OPEN":        "SIZE_3",
    "S2_VI_PULLBACK":     "SIZE_3",
    "S4_BIG_CANDLE":      "SIZE_3",
    "S10_NEW_HIGH":       "SIZE_2",   # A품질+낮은추격리스크 시 SIZE_3 허용(별도 로직)
    "S13_BOX_BREAKOUT":   "SIZE_2",   # A품질+낮은추격리스크 시 SIZE_3 허용(별도 로직)
    "S15_MOMENTUM_ALIGN": "SIZE_2",
}
DEFAULT_CAP = "SIZE_4"

# ── 티어 순서(강도 비교용) ────────────────────────────────────────────────────
_TIER_ORDER = {"SIZE_0": 0, "SIZE_1": 1, "SIZE_2": 2, "SIZE_3": 3, "SIZE_4": 4}

# ── 장세-전략 궁합 점수표 ─────────────────────────────────────────────────────
_REGIME_FIT: dict[str, dict[str, float]] = {
    "bull": {
        "S1_GAP_OPEN": 5.0, "S4_BIG_CANDLE": 5.0,
        "S6_THEME_LAGGARD": 5.0, "S8_GOLDEN_CROSS": 5.0,
        "S10_NEW_HIGH": 5.0, "S13_BOX_BREAKOUT": 5.0,
    },
    "bear": {
        "S14_OVERSOLD_BOUNCE": 5.0,
        "S9_PULLBACK_SWING": 5.0,
        "S11_FRGN_CONT": 5.0,
    },
    "sideways": {
        "S7_ICHIMOKU_BREAKOUT": 5.0, "S13_BOX_BREAKOUT": 5.0,
        "S8_GOLDEN_CROSS": 5.0, "S11_FRGN_CONT": 5.0,
        "S15_MOMENTUM_ALIGN": 5.0,
    },
    "neutral": {},
}


def _calc_liquidity_score(
    trde_amt: Optional[float],
    spread_pct: Optional[float],
) -> float:
    """
    유동성·호가 점수 산출 (최대 15점).

    trde_amt  : 거래대금(원). 10억 기준 만점.
    spread_pct: 스프레드 %. 낮을수록 좋음.
    """
    score = 0.0

    # 거래대금 점수 (0~8)
    if trde_amt is not None and trde_amt > 0:
        if trde_amt >= 10_000_000_000:      # 100억+
            score += 8.0
        elif trde_amt >= 5_000_000_000:     # 50억+
            score += 6.0
        elif trde_amt >= 1_000_000_000:     # 10억+
            score += 4.0
        elif trde_amt >= 500_000_000:       # 5억+
            score += 2.0
        # 5억 미만 → 0

    # 스프레드 점수 (0~7)
    if spread_pct is not None:
        if spread_pct <= 0.05:
            score += 7.0
        elif spread_pct <= 0.1:
            score += 5.0
        elif spread_pct <= 0.2:
            score += 3.0
        elif spread_pct <= 0.5:
            score += 1.0
        # 0.5% 초과 → 0

    return min(15.0, score)


def _calc_stop_stability(
    stop_pct: float,
    atr_pct: Optional[float],
) -> float:
    """
    손절 안정성 점수 산출 (최대 15점).

    손절폭이 작을수록, ATR 대비 손절이 합리적일수록 높은 점수.
    """
    score = 0.0

    # 손절폭 점수 (0~10)
    if stop_pct <= 1.0:
        score += 10.0
    elif stop_pct <= 1.5:
        score += 8.0
    elif stop_pct <= 2.0:
        score += 6.0
    elif stop_pct <= 3.0:
        score += 4.0
    elif stop_pct <= 5.0:
        score += 2.0
    # 5% 초과 → 0

    # ATR 대비 보너스/패널티 (0~5 or -5~0)
    if atr_pct is not None and atr_pct > 0:
        # 손절폭/ATR 비율: 1~3배 범위가 이상적
        ratio = stop_pct / atr_pct
        if 1.0 <= ratio <= 3.0:
            score += 5.0    # 적정 손절
        elif ratio < 1.0:
            score += 2.0    # 손절폭이 너무 작음 (너무 타이트)
        else:
            score -= 2.0    # ATR 대비 손절폭 과도

    return max(0.0, min(15.0, score))


def _calc_regime_fit(strategy_id: str, market_regime: str) -> float:
    """장세-전략 궁합 점수 (최대 5점)."""
    regime_table = _REGIME_FIT.get(market_regime, {})
    return regime_table.get(strategy_id, 0.0)


def _score_to_tier(score: float) -> tuple[str, float]:
    """점수 → (tier, weight) 변환."""
    for threshold, tier, weight in _TIER_MAP:
        if score >= threshold:
            return tier, weight
    return "SIZE_0", 0.00


def _apply_cap(
    tier: str,
    strategy_id: str,
    candidate_quality: str,
    chase_risk_score: float,
) -> tuple[str, bool]:
    """
    전략별 상한을 적용한 최종 티어 반환.
    S10/S13: candidate_quality="A" AND chase_risk_score < 30 이면 SIZE_3 허용.
    반환: (최종 tier, cap_적용_여부)
    """
    cap_str = STRATEGY_SIZE_CAPS.get(strategy_id, DEFAULT_CAP)

    # S10/S13 조건부 SIZE_3 허용
    if strategy_id in ("S10_NEW_HIGH", "S13_BOX_BREAKOUT"):
        if candidate_quality == "A" and chase_risk_score < 30:
            cap_str = "SIZE_3"

    cap_order = _TIER_ORDER.get(cap_str, 4)
    tier_order = _TIER_ORDER.get(tier, 0)

    if tier_order > cap_order:
        return cap_str, True
    return tier, False


def _tier_to_weight(tier: str) -> float:
    for _, t, w in _TIER_MAP:
        if t == tier:
            return w
    return 0.00


def calculate_entry_size(
    ai_score: float,
    rule_score: float,
    confidence: str,
    candidate_quality: str,
    quality_score: float = 50.0,
    chase_risk_score: float = 50.0,
    execution_quality: str = "B",
    rr_ratio: float = 1.0,
    rr_quality_bucket: str = "FAIR",
    stop_pct: float = 3.0,
    atr_pct: Optional[float] = None,
    trde_amt: Optional[float] = None,
    spread_pct: Optional[float] = None,
    strategy_id: str = "",
    market_regime: str = "neutral",
    strategy_count: int = 1,
    sector_heat_score: float = 50.0,
    freshness_status: str = "FRESH",
) -> dict:
    """
    비계좌 기반 진입 강도 산출.

    계좌잔고·총자산·주문가능금액·계좌 리스크 %·실제 보유 포지션 금액을
    절대 사용하지 않는다. 모델 상대 강도만 산출한다.

    Returns:
        {
            "entry_size_score":   float,   # 0~100
            "entry_size_tier":    str,     # SIZE_0~SIZE_4
            "entry_size_weight":  float,   # 0.00~1.00
            "entry_size_basis":   str,     # 항상 "model_relative_not_account"
            "size_downgrade_flags": list,
        }
    """
    flags: list[str] = []

    # ── execution_quality REJECT 즉시 SIZE_0 ────────────────────────────────
    if execution_quality == "REJECT":
        flags.append("execution_quality_reject")
        return {
            "entry_size_score":     0.0,
            "entry_size_tier":      "SIZE_0",
            "entry_size_weight":    0.00,
            "entry_size_basis":     "model_relative_not_account",
            "size_downgrade_flags": flags,
        }

    # ── STALE 데이터 패널티 플래그 ───────────────────────────────────────────
    if freshness_status == "STALE":
        flags.append("stale_data")

    # ── 신호 품질 (최대 25점) ─────────────────────────────────────────────────
    # ai_score 15% + rule_score 10% 가중
    signal_quality = min(25.0, ai_score * 0.15 + rule_score * 0.10)

    # ── 후보 품질 (최대 20점) ─────────────────────────────────────────────────
    _cq_map = {"A": 20.0, "B": 14.0, "C": 8.0, "REJECT": 0.0}
    candidate_quality_score = _cq_map.get(candidate_quality, 8.0)
    if candidate_quality in ("C", "REJECT"):
        flags.append("poor_candidate_quality")

    # ── 유동성·호가 (최대 15점) ──────────────────────────────────────────────
    liquidity_score = _calc_liquidity_score(trde_amt, spread_pct)

    # 스프레드 과도 플래그
    if spread_pct is not None and spread_pct > 0.5:
        flags.append("spread_too_wide")
    # 낮은 거래대금 플래그
    if trde_amt is not None and trde_amt > 0 and trde_amt < 1_000_000_000:
        flags.append("low_liquidity")

    # ── 손절 안정성 (최대 15점) ──────────────────────────────────────────────
    stop_stability = _calc_stop_stability(stop_pct, atr_pct)

    if stop_pct > 5.0:
        flags.append("high_stop_pct")

    # ── 추격 역점수 (최대 15점) ──────────────────────────────────────────────
    # 추격 위험 낮을수록 높은 점수
    chase_inverse = max(0.0, 15.0 - chase_risk_score * 0.15)
    if chase_risk_score >= 70:
        flags.append("high_chase_risk")

    # ── 장세-전략 궁합 (최대 5점) ────────────────────────────────────────────
    regime_fit = _calc_regime_fit(strategy_id, market_regime)

    # ── 다중전략 보너스 (최대 5점) ───────────────────────────────────────────
    multi_bonus = min(5.0, (strategy_count - 1) * 2.5)

    # ── 섹터 과열 패널티 (최대 -15점) ────────────────────────────────────────
    sector_penalty = -max(0.0, (sector_heat_score - 70.0) * 0.5)
    if sector_heat_score >= 70:
        flags.append("sector_overheated")

    # ── STALE 시 추가 패널티 ─────────────────────────────────────────────────
    stale_penalty = -5.0 if freshness_status == "STALE" else 0.0

    # ── 최종 점수 합산 ───────────────────────────────────────────────────────
    raw_score = (
        signal_quality
        + candidate_quality_score
        + liquidity_score
        + stop_stability
        + chase_inverse
        + regime_fit
        + multi_bonus
        + sector_penalty
        + stale_penalty
    )
    entry_size_score = round(max(0.0, min(100.0, raw_score)), 1)

    # ── 티어 결정 ────────────────────────────────────────────────────────────
    tier, weight = _score_to_tier(entry_size_score)

    # ── 전략별 상한 적용 ─────────────────────────────────────────────────────
    final_tier, cap_applied = _apply_cap(tier, strategy_id, candidate_quality, chase_risk_score)
    if cap_applied:
        flags.append("strategy_cap_applied")
        weight = _tier_to_weight(final_tier)

    return {
        "entry_size_score":     entry_size_score,
        "entry_size_tier":      final_tier,
        "entry_size_weight":    weight,
        "entry_size_basis":     "model_relative_not_account",
        "size_downgrade_flags": flags,
    }
