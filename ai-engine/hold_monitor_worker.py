from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta, timezone

from analyzer import analyze_signal
from price_utils import normalize_signal_prices
from redis_reader import (
    clear_hold_monitor_queue,
    pop_due_hold_monitor_items,
    push_score_only_queue,
    requeue_hold_monitor_item,
)
from scorer import check_daily_limit, get_claude_threshold, rule_score, should_skip_ai
from score_utils import normalize_score_0_100
from tp_sl_engine import compute_rr
from utils import normalize_stock_code, safe_float as _fv

import queue_worker as qw

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

HOLD_MONITOR_INTERVAL_SEC = float(os.getenv("HOLD_MONITOR_INTERVAL_SEC", "5.0"))
HOLD_MONITOR_RECHECK_SEC = float(os.getenv("HOLD_MONITOR_RECHECK_SEC", "10.0"))
HOLD_MONITOR_AI_COOLDOWN_SEC = float(os.getenv("HOLD_MONITOR_AI_COOLDOWN_SEC", "60.0"))
HOLD_MONITOR_BATCH_LIMIT = int(os.getenv("HOLD_MONITOR_BATCH_LIMIT", "20"))
HOLD_MONITOR_CLOSE_HHMM = os.getenv("HOLD_MONITOR_CLOSE_HHMM", "15:30")
HOLD_MONITOR_USE_REST_FALLBACK = os.getenv("HOLD_MONITOR_USE_REST_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}
HOLD_MONITOR_MAX_REST_CALLS_PER_MIN = int(os.getenv("HOLD_MONITOR_MAX_REST_CALLS_PER_MIN", "30"))
_REST_CALL_FIELDS = ("tick", "strength", "hoga")


def _close_time() -> time:
    try:
        hh, mm = HOLD_MONITOR_CLOSE_HHMM.split(":", 1)
        return time(int(hh), int(mm))
    except Exception:
        return time(15, 30)


def _now_kst() -> datetime:
    return datetime.now(KST)


def _is_weekday(now: datetime | None = None) -> bool:
    target = now or _now_kst()
    return target.weekday() < 5


def _is_after_close(now: datetime | None = None) -> bool:
    target = now or _now_kst()
    return (not _is_weekday(target)) or target.time() >= _close_time()


def _is_before_main_monitor_window(now: datetime | None = None) -> bool:
    target = now or _now_kst()
    return target.time() < time(9, 0)


def _current_price_from_ctx(ctx: dict, fallback) -> float | None:
    tick = ctx.get("tick") or {}
    for key in ("cur_prc", "curPrc", "stck_prpr", "price"):
        value = _fv(tick.get(key), None)
        if value and value > 0:
            return abs(value)
    value = _fv(fallback, None)
    return abs(value) if value and value > 0 else None


def _refresh_rr(payload: dict) -> None:
    entry = _fv(payload.get("cur_prc") or payload.get("entry_price"), None)
    tp = _fv(payload.get("claude_tp1") or payload.get("tp1_price") or payload.get("target_price"), None)
    sl = _fv(payload.get("claude_sl") or payload.get("sl_price") or payload.get("stop_price"), None)
    if entry is None or tp is None or sl is None:
        return
    rr, skip = compute_rr(str(payload.get("stk_cd", "")), entry, tp, sl, min_rr=None)
    payload["rr_ratio"] = rr
    payload["effective_rr"] = rr
    if skip and not payload.get("rr_skip_reason"):
        payload["rr_skip_reason"] = "hold monitor recomputed R:R below advisory strategy threshold"


def _recent_ai_call(payload: dict) -> bool:
    last = _fv(payload.get("hold_monitor_last_ai_at"), None)
    if last is None:
        return False
    return (_now_kst().timestamp() - last) < HOLD_MONITOR_AI_COOLDOWN_SEC


def _rest_budget_key(now: datetime | None = None) -> str:
    target = now or _now_kst()
    return f"hold_monitor:rest_budget:{target.strftime('%Y%m%d%H%M')}"


def _count_rest_attempts(meta: dict | None) -> int:
    attempted = (meta or {}).get("data_refresh_attempted") or {}
    sources = (meta or {}).get("market_data_sources") or {}
    count = 0
    for field in _REST_CALL_FIELDS:
        if field in attempted or sources.get(field) == "rest":
            count += 1
    return count


async def _rest_budget_available(rdb, *, needed: int = 1) -> bool:
    if HOLD_MONITOR_MAX_REST_CALLS_PER_MIN <= 0:
        return False
    key = _rest_budget_key()
    current = await rdb.get(key)
    try:
        used = int(current or 0)
    except (TypeError, ValueError):
        used = 0
    return used + max(1, needed) <= HOLD_MONITOR_MAX_REST_CALLS_PER_MIN


async def _record_rest_budget(rdb, count: int) -> None:
    if count <= 0:
        return
    key = _rest_budget_key()
    await rdb.incrby(key, count)
    await rdb.expire(key, 90)


async def _refresh_ctx_for_hold_monitor(ctx: dict, stk_cd: str, rdb, payload: dict, strategy: str) -> None:
    if not HOLD_MONITOR_USE_REST_FALLBACK:
        ctx["refresh_meta"] = {
            "market_data_sources": {},
            "data_refresh_attempted": {},
            "retry_failures": ["hold_monitor_rest_disabled"],
        }
        return
    if not await _rest_budget_available(rdb):
        ctx["refresh_meta"] = {
            "market_data_sources": {},
            "data_refresh_attempted": {},
            "retry_failures": ["hold_monitor_rest_budget_exhausted"],
        }
        return

    await qw._refresh_stale_ctx(ctx, stk_cd, rdb, payload, strategy)
    await _record_rest_budget(rdb, _count_rest_attempts(ctx.get("refresh_meta")))


async def _requeue(rdb, payload: dict, reason: str) -> None:
    payload["hold_monitor_last_reason"] = reason
    payload["hold_monitor_attempts"] = int(_fv(payload.get("hold_monitor_attempts"), 0) or 0) + 1
    await requeue_hold_monitor_item(rdb, payload, delay_sec=HOLD_MONITOR_RECHECK_SEC)


async def evaluate_hold_item(rdb, payload: dict) -> dict:
    """Return an ENTER payload when a HOLD item improves, otherwise return {}."""
    normalize_signal_prices(payload)
    stk_cd = normalize_stock_code(payload.get("stk_cd", ""))
    strategy = str(payload.get("strategy") or "")
    if not stk_cd or not strategy:
        return {}
    payload["stk_cd"] = stk_cd

    ctx = await qw._build_market_ctx(rdb, stk_cd, sector=payload.get("sector", "") or "", signal=payload)
    await _refresh_ctx_for_hold_monitor(ctx, stk_cd, rdb, payload, strategy)

    current_price = _current_price_from_ctx(ctx, payload.get("cur_prc") or payload.get("entry_price"))
    if current_price:
        payload["cur_prc"] = current_price
        payload["entry_price"] = current_price
    exact_strength = qw._resolve_execution_strength(payload, ctx)
    ctx["strength"] = exact_strength
    if exact_strength > 0:
        payload["cntr_strength"] = round(exact_strength, 2)
    bid_ratio = qw._resolve_bid_ratio(payload, ctx)
    if bid_ratio is not None:
        payload["bid_ratio"] = round(bid_ratio, 3)
    _refresh_rr(payload)
    normalize_signal_prices(payload)

    r_score, _components = qw._coerce_rule_score_result(rule_score(payload, ctx))
    payload["rule_score"] = r_score
    quality = qw._compute_signal_quality(payload, ctx, r_score)
    payload.update(quality)

    threshold = get_claude_threshold(strategy)
    skip_ai = should_skip_ai(r_score, strategy)
    rescue_reason = (
        qw._rule_threshold_rescue_reason(
            payload,
            ctx,
            rule_score_value=r_score,
            threshold=threshold,
            quality=quality,
        )
        if skip_ai
        else None
    )
    if skip_ai and not rescue_reason:
        payload["threshold_used"] = threshold
        return {}

    rr_reason = qw._rr_prefilter_reason(payload, ctx)
    s8_zone_reason = qw._s8_buy_zone_gate_failure(payload)
    s1_reason = qw._s1_fallback_quality_failure(payload, ctx)
    hard_reason = qw._hard_gate_failure(payload, ctx)
    stale_reason = qw._freshness_cancel_reason(ctx, strategy)
    if rr_reason or s8_zone_reason or s1_reason or hard_reason or stale_reason:
        payload["hold_monitor_last_gate"] = rr_reason or s8_zone_reason or s1_reason or hard_reason or stale_reason
        return {}

    if _recent_ai_call(payload):
        return {}

    if not await check_daily_limit(rdb):
        payload["hold_monitor_last_gate"] = "AI daily limit reached"
        return {}

    payload["hold_monitor_last_ai_at"] = _now_kst().timestamp()
    ai_result = await analyze_signal(payload, ctx, r_score, rdb=rdb)
    ai_score = normalize_score_0_100(ai_result.get("ai_score", r_score))
    original_action = str(ai_result.get("action", "HOLD") or "HOLD").upper()
    action = original_action
    confidence = ai_result.get("confidence", "LOW")
    reason = ai_result.get("reason", "hold monitor re-evaluation")
    cancel_reason = ai_result.get("cancel_reason")
    action, confidence, reason, cancel_reason = qw._maybe_promote_hold_to_enter(
        strategy=strategy,
        action=action,
        confidence=confidence,
        reason=reason,
        cancel_reason=cancel_reason,
        ai_score=ai_score,
    )
    if action != "ENTER":
        payload["ai_score"] = ai_score
        payload["confidence"] = confidence
        payload["ai_reason"] = qw._resolve_display_reason(action, reason, cancel_reason)
        payload["cancel_reason"] = cancel_reason
        return {}

    enriched = {
        **payload,
        "type": payload.get("type") if payload.get("type") != "HOLD_MONITOR" else None,
        "action": "ENTER",
        "confidence": confidence or "HIGH",
        "rule_score": r_score,
        "ai_score": ai_score,
        "ai_reason": qw._resolve_display_reason("ENTER", reason, None),
        "cancel_reason": None,
        "adjusted_target_pct": ai_result.get("adjusted_target_pct"),
        "adjusted_stop_pct": ai_result.get("adjusted_stop_pct"),
        "claude_tp1": ai_result.get("claude_tp1"),
        "claude_tp2": ai_result.get("claude_tp2"),
        "claude_sl": ai_result.get("claude_sl"),
        "hold_monitor_promoted": True,
        "hold_promoted_to_enter": original_action == "HOLD",
    }
    normalize_signal_prices(enriched)
    enriched = qw._apply_claude_postprocess_hard_rules(enriched)
    enriched = qw._apply_claude_rr_override(enriched, ctx)
    enriched = qw._apply_session_enter_guard(enriched, ctx)
    if enriched.get("action") != "ENTER":
        payload.update(enriched)
        return {}
    return enriched


async def process_due_items(rdb) -> int:
    items = await pop_due_hold_monitor_items(rdb, limit=HOLD_MONITOR_BATCH_LIMIT)
    promoted = 0
    for item in items:
        key = item.get("hold_monitor_key", "")
        try:
            result = await evaluate_hold_item(rdb, item)
            if result:
                await push_score_only_queue(rdb, result)
                promoted += 1
                logger.info(
                    "[HoldMonitor] promoted HOLD to ENTER [%s %s] key=%s",
                    result.get("stk_cd"),
                    result.get("strategy"),
                    key,
                )
            elif not _is_after_close():
                await _requeue(rdb, item, item.get("hold_monitor_last_gate") or item.get("hold_monitor_last_reason") or "still HOLD")
        except Exception as exc:
            logger.warning("[HoldMonitor] evaluation failed key=%s: %s", key, exc)
            if not _is_after_close():
                await _requeue(rdb, item, f"error:{type(exc).__name__}")
    return promoted


async def run_hold_monitor_worker(rdb):
    logger.info("[HoldMonitor] worker started interval=%ss close=%s", HOLD_MONITOR_INTERVAL_SEC, HOLD_MONITOR_CLOSE_HHMM)
    cleared_for_date: str | None = None
    while True:
        now = _now_kst()
        today = now.strftime("%Y-%m-%d")
        if _is_after_close(now):
            if cleared_for_date != today:
                await clear_hold_monitor_queue(rdb)
                cleared_for_date = today
                logger.info("[HoldMonitor] queue cleared for close %s", HOLD_MONITOR_CLOSE_HHMM)
            await asyncio.sleep(max(HOLD_MONITOR_INTERVAL_SEC, 30.0))
            continue
        cleared_for_date = None
        if _is_before_main_monitor_window(now):
            await asyncio.sleep(max(HOLD_MONITOR_INTERVAL_SEC, 10.0))
            continue
        await process_due_items(rdb)
        await asyncio.sleep(HOLD_MONITOR_INTERVAL_SEC)
