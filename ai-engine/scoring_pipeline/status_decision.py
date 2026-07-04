from __future__ import annotations


def select_pre_ai_decision(
    *,
    skip_ai: bool,
    rescue_reason: str | None,
    rule_score_value: float,
    threshold: float,
    quality_score: float,
    watch_min_quality: float,
    rr_prefilter_reason: str | None,
    s8_zone_gate_reason: str | None,
    s1_fallback_quality_reason: str | None,
    s1_execution_policy: tuple[str, str, str] | None,
    hard_gate_reason: str | None,
    program_flow_reason: str | None,
    stale_reason: str | None,
    strategy: str,
    current_s8_zone_status: str | None = None,
) -> dict:
    """Resolve the pre-AI action and metric plan for a scored signal."""
    metrics: list[str] = []
    signal_updates: dict = {}

    if skip_ai and not rescue_reason:
        blocking_gate = s8_zone_gate_reason or s1_fallback_quality_reason or hard_gate_reason or program_flow_reason or stale_reason
        if quality_score >= watch_min_quality and not blocking_gate:
            return {
                "terminal": True,
                "action": "HOLD",
                "confidence": "LOW",
                "reason": f"Rule score {rule_score_value:.1f} below Claude threshold {threshold:.1f}; WATCH for improvement",
                "cancel_reason": None,
                "cancel_type": None,
                "decision_stage": "WATCH_RULE_THRESHOLD",
                "metrics": ["watch_rule_threshold"],
                "signal_updates": signal_updates,
            }
        return {
            "terminal": True,
            "action": "CANCEL",
            "confidence": "LOW",
            "reason": f"Rule score {rule_score_value:.1f} below threshold",
            "cancel_reason": "Rule threshold not met",
            "cancel_type": "RULE_THRESHOLD",
            "decision_stage": None,
            "metrics": ["cancel_score"],
            "signal_updates": signal_updates,
        }

    if rescue_reason:
        signal_updates.update({
            "rule_threshold_rescued": True,
            "decision_stage": "AI_REVIEW",
            "rule_threshold_rescue_reason": rescue_reason,
        })
        metrics.append("rule_threshold_rescue")

    if rr_prefilter_reason:
        if strategy == "S8_GOLDEN_CROSS":
            signal_updates.update({
                "s8_zone_status": current_s8_zone_status or "wait_pullback",
                "s8_zone_entry_policy": "wait_pullback",
            })
            cancel_type = "S8_WAIT_PULLBACK"
        else:
            cancel_type = None
        return {
            "terminal": True,
            "action": "HOLD",
            "confidence": "LOW",
            "reason": f"{rr_prefilter_reason}; WATCH until R:R improves",
            "cancel_reason": None,
            "cancel_type": cancel_type,
            "decision_stage": "WATCH_RR",
            "metrics": metrics + ["watch_rr"],
            "signal_updates": signal_updates,
        }

    for reason_value, cancel_type, metric in (
        (s8_zone_gate_reason, "S8_BUY_ZONE", "cancel_s8_buy_zone"),
        (s1_fallback_quality_reason, "S1_FALLBACK_QUALITY", "cancel_s1_fallback_quality"),
    ):
        if reason_value:
            return {
                "terminal": True,
                "action": "CANCEL",
                "confidence": "LOW",
                "reason": reason_value,
                "cancel_reason": reason_value,
                "cancel_type": cancel_type,
                "decision_stage": None,
                "metrics": metrics + [metric],
                "signal_updates": signal_updates,
            }

    if s1_execution_policy and s1_execution_policy[0] == "CANCEL":
        _policy_action, policy_reason, policy_type = s1_execution_policy
        return {
            "terminal": True,
            "action": "CANCEL",
            "confidence": "LOW",
            "reason": policy_reason,
            "cancel_reason": policy_reason,
            "cancel_type": policy_type,
            "decision_stage": None,
            "metrics": metrics + ["cancel_s1_execution_policy"],
            "signal_updates": signal_updates,
        }

    for reason_value, prefix, cancel_type, metric in (
        (hard_gate_reason, "Hard gate failed", "HARD_GATE", "cancel_hard_gate"),
        (program_flow_reason, "Program flow gate failed", "PROGRAM_FLOW", "cancel_program_flow"),
    ):
        if reason_value:
            reason = f"{prefix}: {reason_value}"
            return {
                "terminal": True,
                "action": "CANCEL",
                "confidence": "LOW",
                "reason": reason,
                "cancel_reason": reason,
                "cancel_type": cancel_type,
                "decision_stage": None,
                "metrics": metrics + [metric],
                "signal_updates": signal_updates,
            }

    if stale_reason:
        return {
            "terminal": True,
            "action": "CANCEL",
            "confidence": "LOW",
            "reason": stale_reason,
            "cancel_reason": stale_reason,
            "cancel_type": "FRESHNESS_STALE",
            "decision_stage": None,
            "metrics": metrics + ["cancel_freshness"],
            "signal_updates": signal_updates,
        }

    if s1_execution_policy:
        policy_action, policy_reason, _policy_type = s1_execution_policy
        return {
            "terminal": True,
            "action": policy_action,
            "confidence": "LOW",
            "reason": policy_reason,
            "cancel_reason": policy_reason,
            "cancel_type": None,
            "decision_stage": None,
            "metrics": metrics + ["hold_s1_execution_policy"],
            "signal_updates": signal_updates,
        }

    return {
        "terminal": False,
        "metrics": metrics + ["rule_pass"],
        "signal_updates": signal_updates,
    }
