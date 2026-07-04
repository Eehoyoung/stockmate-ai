from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable


KST = timezone(timedelta(hours=9))


def execution_decision_from_action(action: str, *, cancel_type: str | None = None) -> str:
    """Normalize legacy action values into the canonical execution decision."""
    normalized = str(action or "").upper()
    if normalized == "ENTER":
        return "ENTER"
    if normalized == "HOLD":
        return "WATCH"
    return "BLOCK"


def apply_execution_decision(payload: dict, decision: str, *, reason: str | None = None) -> dict:
    """Attach canonical execution decision while preserving legacy action compatibility."""
    canonical = str(decision or "BLOCK").upper()
    if canonical not in {"ENTER", "WATCH", "BLOCK"}:
        canonical = "BLOCK"
    payload["execution_decision"] = canonical
    payload["signal_stage"] = "ENTRY" if canonical == "ENTER" else canonical
    if reason and not payload.get("execution_reason"):
        payload["execution_reason"] = reason
    if canonical == "ENTER":
        payload["action"] = "ENTER"
        payload["skip_entry"] = False
    elif canonical == "WATCH":
        payload["action"] = "HOLD"
        payload["skip_entry"] = True
    else:
        payload["action"] = "CANCEL"
        payload["skip_entry"] = True
    return payload


def canonicalize_execution_payload(payload: dict) -> dict:
    action = str(payload.get("action") or "").upper()
    decision = payload.get("execution_decision")
    if action in {"CANCEL", "HOLD"}:
        decision = execution_decision_from_action(action, cancel_type=payload.get("cancel_type"))
    elif not decision:
        decision = execution_decision_from_action(action, cancel_type=payload.get("cancel_type"))
    return apply_execution_decision(payload, str(decision), reason=payload.get("ai_reason"))


def current_market_session(
    *,
    current_session_func: Callable[[datetime | None], Any] | None = None,
    now: datetime | None = None,
) -> str:
    if current_session_func is not None:
        try:
            session = current_session_func(now)
            value = getattr(session, "value", session)
            return str(value).lower()
        except Exception:
            pass
    now = now or datetime.now(KST)
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if t < datetime.strptime("08:00:00", "%H:%M:%S").time():
        return "closed"
    if t < datetime.strptime("08:50:00", "%H:%M:%S").time():
        return "pre_market"
    if t < datetime.strptime("09:00:30", "%H:%M:%S").time():
        return "opening_auction"
    if t < datetime.strptime("15:20:00", "%H:%M:%S").time():
        return "main_market"
    if t < datetime.strptime("15:30:00", "%H:%M:%S").time():
        return "closing_auction"
    if t < datetime.strptime("15:40:00", "%H:%M:%S").time():
        return "after_preopen"
    if t < datetime.strptime("20:00:00", "%H:%M:%S").time():
        return "after_market"
    if t < datetime.strptime("20:10:00", "%H:%M:%S").time():
        return "post_quiet"
    return "closed"


def normalize_session_value(value) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", value)
    text = str(enum_value).strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def resolve_signal_session(
    payload: dict,
    ctx: dict | None = None,
    *,
    current_session_func: Callable[[datetime | None], Any] | None = None,
) -> str:
    for source in (payload, ctx or {}):
        for field in ("market_session", "session", "ws_session"):
            value = source.get(field)
            if value:
                return normalize_session_value(value)
    return current_market_session(current_session_func=current_session_func)


def is_session_enter_guard_exempt(payload: dict, exempt_types: set[str]) -> bool:
    strategy = str(payload.get("strategy") or "")
    if strategy.startswith("S2"):
        return True

    item_type = str(payload.get("type") or "").upper()
    if item_type in exempt_types:
        return True
    if "REPORT" in item_type or "FORCE_CLOSE" in item_type or "EXIT" in item_type or "CLOSE" in item_type:
        return True

    action = str(payload.get("action") or "").upper()
    return action in {"FORCE_CLOSE", "EXIT", "CLOSE", "SELL"}


def apply_session_enter_guard(
    payload: dict,
    ctx: dict | None = None,
    *,
    enabled: bool,
    enter_sessions: dict[str, set[str]],
    blocklist: set[str],
    exempt_types: set[str],
    current_session_func: Callable[[datetime | None], Any] | None = None,
    null_claude_prices: Callable[[dict], None] | None = None,
) -> dict:
    if not enabled:
        return payload
    if str(payload.get("action") or "").upper() != "ENTER":
        return payload
    if is_session_enter_guard_exempt(payload, exempt_types):
        return payload

    session = resolve_signal_session(payload, ctx, current_session_func=current_session_func)
    strategy = str(payload.get("strategy") or "")
    allowed_sessions = enter_sessions.get(strategy)
    if allowed_sessions is not None and session in allowed_sessions:
        return payload
    if allowed_sessions is None and session not in blocklist:
        return payload

    reason = f"Session enter guard blocked new ENTER during {session}"
    payload["market_session"] = session
    payload["action"] = "CANCEL"
    payload["confidence"] = "LOW"
    payload["cancel_reason"] = reason
    payload["ai_reason"] = reason
    payload["skip_entry"] = True
    payload["cancel_type"] = "SESSION_ENTER_GUARD"
    if null_claude_prices is not None:
        null_claude_prices(payload)
    return payload

