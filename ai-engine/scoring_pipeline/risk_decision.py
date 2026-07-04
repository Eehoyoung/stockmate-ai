from __future__ import annotations


def rr_quality_bucket(
    rr: float | None,
    *,
    hard_cancel_threshold: float,
    caution_threshold: float,
) -> str:
    if rr is None:
        return "unknown"
    if rr < hard_cancel_threshold:
        return "hard_cancel"
    if rr < caution_threshold:
        return "caution"
    if rr < 1.5:
        return "acceptable"
    return "strong"


def keep_hold_as_watch(
    *,
    action: str,
    confidence: str,
    reason: str,
    cancel_reason: str | None,
    ai_score: float | None,
) -> tuple[str, str, str, str | None]:
    """Keep Claude HOLD as WATCH; score alone must never promote to ENTER."""
    if str(action).upper() != "HOLD":
        return action, confidence, reason, cancel_reason
    watch_reason = str(reason or "Claude HOLD").strip()
    if ai_score is not None:
        watch_reason = f"{watch_reason} | WATCH retained; ai_score alone cannot promote to ENTER"
    return "HOLD", confidence or "MEDIUM", watch_reason, cancel_reason

