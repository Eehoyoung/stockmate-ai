from __future__ import annotations

"""Shadow-only normalized G-family scoring.

This module does not authorize ENTER and does not replace the legacy scorer.
It produces comparable 0-100 components plus explicit blocking/degraded
reasons for the WP-10 shadow report.
"""

from dataclasses import dataclass
from typing import Iterable

from strategy_catalog import FAMILY_BY_SETUP, family_for_setup


SCORING_VERSION = "family_rule_shadow_v1_2026_08_16"
COMPONENT_CAPS = {
    "setup_edge": 35.0,
    "execution_quality": 20.0,
    "regime_timing": 15.0,
    "liquidity_data_quality": 10.0,
    "risk_structure": 20.0,
}

# Same underlying indicator/source lineage receives discounted confirmation.
_CORRELATED_GROUPS = (
    frozenset({"S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT"}),
    frozenset({"S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S15_MOMENTUM_ALIGN"}),
    frozenset({"S7_ICHIMOKU_BREAKOUT", "S10_NEW_HIGH", "S13_BOX_BREAKOUT"}),
    frozenset({"S4_BIG_CANDLE", "S6_THEME_LAGGARD"}),
)


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _unique_known_setups(values: Iterable[object], primary_setup: str) -> list[str]:
    result = []
    for value in (primary_setup, *values):
        setup = str(value or "")
        if setup in FAMILY_BY_SETUP and setup not in result:
            result.append(setup)
    return result


def confirmation_bonus(primary_setup: str, matched_setup_ids: Iterable[object]) -> tuple[float, list[dict]]:
    setups = _unique_known_setups(matched_setup_ids, primary_setup)
    bonus = 0.0
    evidence = []
    for setup in setups[1:]:
        correlated = any(primary_setup in group and setup in group for group in _CORRELATED_GROUPS)
        increment = 4.0 if correlated else 6.0
        increment = min(increment, 8.0 - bonus)
        if increment <= 0:
            break
        bonus += increment
        evidence.append({"setup_id": setup, "correlated": correlated, "bonus": increment})
    return bonus, evidence


def _freshness_states(ctx: dict) -> list[str]:
    states = []
    for status in (ctx.get("freshness") or {}).values():
        if isinstance(status, dict):
            states.append(str(status.get("state") or "missing").lower())
    return states


def compute_family_shadow_score(
    signal: dict,
    ctx: dict,
    *,
    legacy_rule_score: float,
    legacy_components: dict | None = None,
    failed_gates: Iterable[object] = (),
) -> dict:
    setup_id = str(signal.get("primary_setup_id") or signal.get("strategy") or "")
    family = family_for_setup(setup_id)
    legacy_components = legacy_components if isinstance(legacy_components, dict) else {}

    blocking = [str(reason) for reason in failed_gates if str(reason or "").strip()]
    degraded = []
    freshness = _freshness_states(ctx)
    if any(state in {"cancel", "missing", "blocked"} for state in freshness):
        blocking.append("REQUIRED_MARKET_DATA_UNUSABLE")
    elif any(state in {"caution", "stale", "degraded"} for state in freshness):
        degraded.append("MARKET_DATA_DEGRADED")

    if not ctx.get("toss_risk") and setup_id not in {
        "S1_GAP_OPEN", "S2_VI_PULLBACK", "S4_BIG_CANDLE", "S6_THEME_LAGGARD",
    }:
        degraded.append("TOSS_RISK_MISSING")

    # Normalize existing evidence into bounded, comparable axes. Each component
    # is independently clamped; a strong setup cannot erase a blocking reason.
    setup_edge = _clamp(_number(legacy_rule_score) / 100.0 * 35.0, 0.0, 35.0)
    execution_raw = _number(signal.get("signal_quality_score"), 50.0)
    execution_quality = _clamp(execution_raw / 100.0 * 20.0, 0.0, 20.0)

    regime = str(signal.get("market_regime") or ctx.get("market_regime") or "neutral").lower()
    regime_base = 7.5 if regime == "neutral" else 10.0
    if signal.get("time_bonus"):
        regime_base += min(5.0, _number(signal.get("time_bonus")))
    regime_timing = _clamp(regime_base, 0.0, 15.0)

    if not freshness:
        liquidity_data_quality = 0.0
        blocking.append("FRESHNESS_STATUS_MISSING")
    elif blocking:
        liquidity_data_quality = 0.0
    elif degraded:
        liquidity_data_quality = 5.0
    else:
        liquidity_data_quality = 10.0

    rr = _number(signal.get("effective_rr", signal.get("rr_ratio")))
    min_rr = _number(signal.get("min_rr_ratio"))
    if min_rr <= 0:
        min_rr = 1.0
    rr_fraction = _clamp(rr / min_rr, 0.0, 1.0) if rr > 0 else 0.0
    risk_structure = rr_fraction * 14.0
    if signal.get("sl_price") and signal.get("tp1_price"):
        risk_structure += 6.0
    else:
        degraded.append("STRUCTURAL_PLAN_INCOMPLETE")
    risk_structure = _clamp(risk_structure, 0.0, 20.0)

    components = {
        "setup_edge": round(setup_edge, 2),
        "execution_quality": round(execution_quality, 2),
        "regime_timing": round(regime_timing, 2),
        "liquidity_data_quality": round(liquidity_data_quality, 2),
        "risk_structure": round(risk_structure, 2),
    }
    bonus, confirmation_evidence = confirmation_bonus(
        setup_id, signal.get("matched_setup_ids") or [],
    )
    score = _clamp(sum(components.values()) + bonus, 0.0, 100.0)
    return {
        "strategy_family": family.family_id,
        "strategy_family_name": family.name,
        "primary_setup_id": setup_id,
        "matched_setup_ids": _unique_known_setups(signal.get("matched_setup_ids") or [], setup_id),
        "family_rule_score": round(score, 2),
        "family_rule_threshold": family.rule_threshold,
        "family_rule_components": components,
        "family_confirmation_bonus": round(bonus, 2),
        "family_confirmation_evidence": confirmation_evidence,
        "blocking_reasons": sorted(set(blocking)),
        "degraded_reasons": sorted(set(degraded)),
        "family_scoring_version": SCORING_VERSION,
        "family_shadow_only": True,
        "legacy_components_observed": bool(legacy_components),
    }
