from __future__ import annotations

from typing import Awaitable, Callable


async def evaluate_ai_decision(
    *,
    signal: dict,
    ctx: dict,
    rule_score_value: float,
    rdb,
    check_daily_limit_fn: Callable[[object], Awaitable[bool]],
    analyze_signal_fn: Callable[..., Awaitable[dict]],
    normalize_score_fn: Callable[[object], float],
    hold_policy_fn: Callable[..., tuple[str, str, str, str | None]],
) -> dict:
    """Run the AI decision step and normalize success/limit/failure outcomes."""
    can_call = await check_daily_limit_fn(rdb)
    if not can_call:
        if signal.get("hold_monitor_recheck"):
            return {
                "action": "HOLD",
                "confidence": "LOW",
                "reason": "HOLD recheck AI budget reached; monitoring retained",
                "cancel_reason": None,
                "cancel_type": None,
                "ai_score": rule_score_value,
                "ai_result": {},
                "hold_promoted_to_enter": False,
                "metrics": ["hold_recheck_ai_limit"],
            }
        return {
            "action": "CANCEL",
            "confidence": "LOW",
            "reason": "Claude daily limit reached",
            "cancel_reason": "AI daily limit reached",
            "cancel_type": "AI_DAILY_LIMIT",
            "ai_score": rule_score_value,
            "ai_result": {},
            "hold_promoted_to_enter": False,
            "metrics": ["cancel_ai_limit"],
        }

    try:
        ai_result = await analyze_signal_fn(signal, ctx, rule_score_value, rdb=rdb)
        ai_score = normalize_score_fn(ai_result.get("ai_score", rule_score_value))
        original_action = str(ai_result.get("action", "ENTER") or "ENTER").upper()
        action = original_action
        confidence = ai_result.get("confidence", "HIGH")
        reason = ai_result.get("reason", f"Rule score {rule_score_value:.1f} passed")
        cancel_reason = ai_result.get("cancel_reason")
        action, confidence, reason, cancel_reason = hold_policy_fn(
            strategy=str(signal.get("strategy") or ""),
            action=action,
            confidence=confidence,
            reason=reason,
            cancel_reason=cancel_reason,
            ai_score=ai_score,
        )
        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "cancel_reason": cancel_reason,
            "cancel_type": ai_result.get("cancel_type"),
            "ai_score": ai_score,
            "ai_result": ai_result,
            "hold_promoted_to_enter": original_action == "HOLD" and action == "ENTER",
            "metrics": ["ai_pass" if action == "ENTER" else "cancel_ai"],
        }
    except Exception as exc:
        return {
            "action": "CANCEL",
            "confidence": "LOW",
            "reason": f"Claude unavailable: {type(exc).__name__}",
            "cancel_reason": "AI analysis unavailable",
            "cancel_type": "AI_UNAVAILABLE",
            "ai_score": rule_score_value,
            "ai_result": {},
            "hold_promoted_to_enter": False,
            "metrics": ["cancel_ai_unavailable"],
            "error": exc,
        }
