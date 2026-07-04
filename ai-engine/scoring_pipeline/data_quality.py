from __future__ import annotations


def compute_freshness_decision(
    freshness: dict,
    strategy: str,
    *,
    strict_cancel_gate: set[str],
    vi_stale_cancel_strategies: set[str] | None = None,
) -> str:
    """Convert live-data freshness state into PASS/CAUTION/SHADOW/SIZE_DOWN/CANCEL."""
    rest_strategies = {"S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT"}

    tick_state = (freshness.get("tick") or {}).get("state", "missing")
    hoga_state = (freshness.get("hoga") or {}).get("state", "missing")
    strength_state = (freshness.get("strength") or {}).get("state", "missing")

    if strategy in strict_cancel_gate:
        if tick_state == "cancel" or hoga_state == "cancel":
            return "CANCEL"
        if tick_state in ("caution", "missing") or hoga_state in ("caution", "missing"):
            return "CAUTION"
    elif strategy in rest_strategies:
        if tick_state == "cancel":
            return "SHADOW"
        if hoga_state == "cancel":
            return "SIZE_DOWN"
    else:
        if tick_state == "cancel":
            return "SHADOW"
        if hoga_state == "cancel":
            return "CAUTION"
        if strength_state == "cancel":
            return "CAUTION"

    if tick_state == "caution" or hoga_state == "caution":
        return "CAUTION"

    return "PASS"


def freshness_status_from_decision(decision: str) -> str:
    """Map freshness decision into the freshness_status consumed by sizing."""
    if decision == "PASS":
        return "FRESH"
    if decision in ("CAUTION", "SIZE_DOWN"):
        return "CAUTION"
    return "STALE"


def compute_data_quality(missing_flags: list[str], freshness_decision: str, signal: dict) -> dict:
    """Compute the score and decision used by the scoring pipeline."""
    score = 100.0
    hard_missing = {"cur_prc", "rr_ratio"}
    for flag in missing_flags:
        if flag in hard_missing:
            score -= 30.0
        else:
            score -= 10.0

    freshness_penalty = {
        "CANCEL": 40.0,
        "SHADOW": 20.0,
        "SIZE_DOWN": 10.0,
        "CAUTION": 5.0,
        "PASS": 0.0,
    }
    score -= freshness_penalty.get(freshness_decision, 0.0)
    score = max(0.0, min(100.0, score))

    if score >= 80:
        decision = "PASS"
    elif score >= 60:
        decision = "SHADOW"
    elif score >= 40:
        decision = "SIZE_DOWN"
    else:
        decision = "CANCEL"

    fallback_used = bool(signal.get("fallback_source") or signal.get("fallback_used"))
    return {
        "data_quality_score": round(score, 1),
        "data_quality_decision": decision,
        "missing_feature_flags": missing_flags,
        "fallback_used": fallback_used,
    }

