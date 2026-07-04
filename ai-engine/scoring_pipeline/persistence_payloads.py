from __future__ import annotations

from collections.abc import Callable
from typing import Any


def resolve_market_flu_rt(
    signal: dict,
    ctx: dict,
    *,
    normalize_market_type_fn: Callable[[str], str],
) -> Any:
    market = normalize_market_type_fn(signal.get("market_type") or ctx.get("market_type", ""))
    if market == "001":
        return ctx.get("kospi_flu_rt")
    if market == "101":
        return ctx.get("kosdaq_flu_rt")
    return None


def resolve_shadow_prices(
    payload: dict,
    *,
    signal: dict | None = None,
    fv_fn: Callable[..., Any],
) -> dict:
    source_signal = signal or {}
    entry = fv_fn(
        payload.get("entry_price")
        or source_signal.get("entry_price")
        or payload.get("cur_prc")
        or source_signal.get("cur_prc")
    )
    tp1 = fv_fn(payload.get("claude_tp1") or payload.get("tp1_price"))
    tp2 = fv_fn(payload.get("claude_tp2") or payload.get("tp2_price"), None)
    sl = fv_fn(payload.get("claude_sl") or payload.get("sl_price"))
    return {
        "entry_price": entry,
        "tp1_price": tp1,
        "tp2_price": tp2,
        "sl_price": sl,
    }


def build_cancel_shadow_detail(
    payload: dict,
    *,
    cancel_type: str | None,
    cancel_reason: str | None,
    fv_fn: Callable[..., Any],
) -> dict:
    return {
        "cancel_type": cancel_type,
        "cancel_reason": cancel_reason,
        "decision_stage": payload.get("decision_stage"),
        "rule_threshold_rescued": bool(payload.get("rule_threshold_rescued")),
        "hard_gate_bid_ratio_rescued": bool(payload.get("hard_gate_bid_ratio_rescued")),
        "s8_zone_entry_policy": payload.get("s8_zone_entry_policy"),
        "entry_size_tier": payload.get("entry_size_tier"),
        "entry_size_weight": payload.get("entry_size_weight"),
        "position_scale": payload.get("position_scale"),
        "rr_ratio": fv_fn(payload.get("rr_ratio"), None),
        "effective_rr": fv_fn(payload.get("effective_rr"), None),
    }
