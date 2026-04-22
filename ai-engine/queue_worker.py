from __future__ import annotations

"""
queue_worker.py

Consumes `telegram_queue`, enriches candidate signals with rule-based scoring and
optional AI analysis, then publishes results to `ai_scored_queue`.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from analyzer import analyze_signal
from db_writer import (
    cancel_open_position_by_signal,
    confirm_open_position,
    insert_ai_cancel_signal,
    insert_python_signal,
    insert_rule_cancel_signal,
    insert_score_components,
    update_signal_score,
)
from http_utils import fetch_stk_nm
from price_utils import normalize_signal_prices
from redis_reader import (
    get_avg_cntr_strength,
    get_hoga_data,
    get_tick_data,
    get_vi_status,
    pop_telegram_queue,
    push_score_only_queue,
)
from scorer import check_daily_limit, get_claude_threshold, rule_score, should_skip_ai
from utils import normalize_stock_code, safe_float as _fv

logger = logging.getLogger(__name__)

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SEC", "2.0"))
STATUS_DECISION_TTL_SEC = int(os.getenv("STATUS_DECISION_TTL_SEC", "600"))
REDIS_TOKEN_KEY = "kiwoom:token"
FAILURE_ACTION = "FAILED"
FAILURE_TYPE = "PROCESSING_ERROR"

_KST = timezone(timedelta(hours=9))
_PIPELINE_TTL_SEC = 172800


async def _incr_pipeline(rdb, strategy: str, field: str) -> None:
    """Best-effort per-strategy daily pipeline counters."""
    try:
        today = datetime.now(_KST).strftime("%Y-%m-%d")
        key = f"pipeline_daily:{today}:{strategy}"
        await rdb.hincrby(key, field, 1)
        await rdb.expire(key, _PIPELINE_TTL_SEC)
    except Exception:
        pass


def _resolve_display_reason(action: str, reason: str, cancel_reason: str | None) -> str:
    if action == "CANCEL" and cancel_reason:
        return cancel_reason
    return reason


def _coerce_rule_score_result(result) -> tuple[float, dict]:
    """Accept the canonical `(score, components)` return and tolerate legacy floats."""
    if isinstance(result, tuple) and len(result) == 2:
        score, components = result
    else:
        score, components = result, {}

    try:
        score_val = float(score)
    except (TypeError, ValueError):
        score_val = 0.0

    if not isinstance(components, dict):
        components = {}

    return score_val, components


def _build_failure_payload(item: dict, strategy: str, stk_cd: str, error: Exception) -> dict:
    return {
        **item,
        "type": FAILURE_TYPE,
        "action": FAILURE_ACTION,
        "confidence": "LOW",
        "rule_score": None,
        "ai_score": 0.0,
        "ai_reason": f"queue_worker processing failed: {type(error).__name__}",
        "error": str(error),
        "error_type": type(error).__name__,
        "failed_stage": "queue_worker",
        "stk_cd": stk_cd,
        "strategy": strategy,
        "skip_entry": True,
        "error_ts": time.time(),
    }


def _resolve_execution_strength(signal: dict, ctx: dict) -> float:
    signal_strength = signal.get("cntr_strength")
    if signal_strength is None:
        signal_strength = signal.get("cntr_str")
    try:
        if signal_strength is not None and float(signal_strength) > 0:
            return float(signal_strength)
    except (TypeError, ValueError):
        pass

    tick = ctx.get("tick", {}) or {}
    tick_strength = tick.get("cntr_str")
    try:
        if tick_strength is not None and float(str(tick_strength).replace(",", "").replace("+", "")) > 0:
            return float(str(tick_strength).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        pass

    try:
        return float(ctx.get("strength", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


async def _build_market_ctx(rdb, stk_cd: str) -> dict:
    tick, hoga, strength, vi = await asyncio.gather(
        get_tick_data(rdb, stk_cd),
        get_hoga_data(rdb, stk_cd),
        get_avg_cntr_strength(rdb, stk_cd, 5),
        get_vi_status(rdb, stk_cd),
    )
    return {"tick": tick, "hoga": hoga, "strength": strength, "vi": vi}


async def process_one(rdb, pg_pool=None) -> bool:
    """
    Process one queue item.

    Returns `True` when an item was consumed, otherwise `False`.
    """
    item = await pop_telegram_queue(rdb)
    if not item:
        return False

    normalize_signal_prices(item)

    stk_cd = normalize_stock_code(item.get("stk_cd", ""))
    strategy = item.get("strategy", "")
    item["stk_cd"] = stk_cd

    await _incr_pipeline(rdb, strategy, "candidate")

    if stk_cd and not item.get("stk_nm"):
        try:
            token = await rdb.get(REDIS_TOKEN_KEY)
            if token:
                item["stk_nm"] = await fetch_stk_nm(rdb, token, stk_cd)
        except Exception as nm_err:
            logger.debug("[Worker] stk_nm lookup failed [%s %s]: %s", stk_cd, strategy, nm_err)

    item_type = item.get("type", "")
    if item_type in ("FORCE_CLOSE", "DAILY_REPORT"):
        await push_score_only_queue(rdb, item)
        logger.debug("[Worker] bypass item forwarded [%s]", item_type)
        return True

    signal_id = item.get("id")
    signal = item

    try:
        try:
            hb = await rdb.hgetall("ws:py_heartbeat")
            ws_online = bool(hb and hb.get("updated_at"))
        except Exception:
            ws_online = False

        if not ws_online:
            logger.warning("[Worker] websocket heartbeat unavailable [%s %s]", stk_cd, strategy)

        ctx = await _build_market_ctx(rdb, stk_cd)
        exact_strength = _resolve_execution_strength(signal, ctx)
        ctx["strength"] = exact_strength
        signal["cntr_strength"] = round(exact_strength, 2) if exact_strength > 0 else signal.get("cntr_strength")
        ctx["ws_online"] = ws_online

        r_score, components = _coerce_rule_score_result(rule_score(signal, ctx))
        logger.info("[Worker] rule score [%s %s]: %.1f", stk_cd, strategy, r_score)

        threshold = get_claude_threshold(strategy)
        ai_score_val = r_score
        ai_result = {}
        cancel_type = None
        cancel_reason = None

        if should_skip_ai(r_score, strategy):
            action = "CANCEL"
            confidence = "LOW"
            reason = f"Rule score {r_score:.1f} below threshold"
            cancel_reason = "Rule threshold not met"
            cancel_type = "RULE_THRESHOLD"
            await _incr_pipeline(rdb, strategy, "cancel_score")
        else:
            await _incr_pipeline(rdb, strategy, "rule_pass")
            can_call = await check_daily_limit(rdb)
            if can_call:
                try:
                    ai_result = await analyze_signal(signal, ctx, r_score, rdb=rdb)
                    ai_score_val = ai_result.get("ai_score", r_score)
                    action = ai_result.get("action", "ENTER")
                    confidence = ai_result.get("confidence", "HIGH")
                    reason = ai_result.get("reason", f"Rule score {r_score:.1f} passed")
                    cancel_reason = ai_result.get("cancel_reason")
                    if action == "ENTER":
                        await _incr_pipeline(rdb, strategy, "ai_pass")
                    else:
                        await _incr_pipeline(rdb, strategy, "cancel_ai")
                except Exception as claude_err:
                    logger.warning(
                        "[Worker] Claude failed [%s %s]: %s, falling back to rules",
                        stk_cd,
                        strategy,
                        claude_err,
                    )
                    action = "ENTER"
                    confidence = "HIGH"
                    reason = f"Rule score {r_score:.1f} passed; Claude unavailable"
            else:
                action = "ENTER"
                confidence = "HIGH"
                reason = f"Rule score {r_score:.1f} passed; Claude daily limit reached"

        display_reason = _resolve_display_reason(action, reason, cancel_reason)

        enriched = {
            **item,
            "rule_score": r_score,
            "ai_score": ai_score_val,
            "action": action,
            "confidence": confidence,
            "ai_reason": display_reason,
            "cancel_reason": cancel_reason,
            "adjusted_target_pct": ai_result.get("adjusted_target_pct"),
            "adjusted_stop_pct": ai_result.get("adjusted_stop_pct"),
            "claude_tp1": ai_result.get("claude_tp1"),
            "claude_tp2": ai_result.get("claude_tp2"),
            "claude_sl": ai_result.get("claude_sl"),
        }
        normalize_signal_prices(enriched)
        await push_score_only_queue(rdb, enriched)

        if action == "ENTER":
            await _incr_pipeline(rdb, strategy, "publish")

        try:
            decision_key = f"status:decisions_10m:{strategy}:{action}"
            await rdb.incr(decision_key)
            await rdb.expire(decision_key, STATUS_DECISION_TTL_SEC)
        except Exception as status_err:
            logger.debug(
                "[Worker] status decision metric failed [%s %s]: %s",
                strategy,
                action,
                status_err,
            )

        if pg_pool:
            db_id = signal_id
            if not db_id:
                db_id = await insert_python_signal(
                    pg_pool,
                    signal,
                    action=action,
                    confidence=confidence,
                    rule_score=r_score,
                    ai_score=ai_score_val,
                    ai_reason=display_reason,
                    skip_entry=(action == "CANCEL"),
                )

            if db_id:
                await update_signal_score(
                    pg_pool,
                    db_id,
                    rule_score=r_score,
                    ai_score=ai_score_val,
                    rr_ratio=None,
                    action=action,
                    confidence=confidence,
                    ai_reason=display_reason,
                    tp_method=signal.get("tp_method"),
                    sl_method=signal.get("sl_method"),
                    skip_entry=(action == "CANCEL"),
                    ma5=signal.get("ma5"),
                    ma20=signal.get("ma20"),
                    ma60=signal.get("ma60"),
                    rsi14=signal.get("rsi"),
                    bb_upper=signal.get("bb_upper"),
                    bb_lower=signal.get("bb_lower"),
                    atr=signal.get("atr"),
                    market_flu_rt=None,
                    news_sentiment=None,
                    news_ctrl=None,
                )
                await insert_score_components(
                    pg_pool,
                    db_id,
                    strategy,
                    components,
                    total_score=r_score,
                    threshold=threshold,
                )

                if action == "ENTER":
                    await confirm_open_position(
                        pg_pool,
                        db_id,
                        ai_score=ai_score_val,
                        tp1_price=_fv(enriched.get("claude_tp1") or enriched.get("tp1_price")),
                        tp2_price=_fv(enriched.get("claude_tp2") or enriched.get("tp2_price")),
                        sl_price=_fv(enriched.get("claude_sl") or enriched.get("sl_price")),
                    )
                else:
                    if cancel_type:
                        await insert_rule_cancel_signal(
                            pg_pool,
                            signal_id=db_id,
                            stk_cd=stk_cd,
                            strategy=strategy,
                            rule_score=r_score,
                            cancel_type=cancel_type,
                            reason=display_reason,
                            raw_payload={**item, "action": action, "confidence": confidence},
                        )
                    elif action == "CANCEL":
                        await insert_ai_cancel_signal(
                            pg_pool,
                            signal_id=db_id,
                            stk_cd=stk_cd,
                            strategy=strategy,
                            ai_score=ai_score_val,
                            confidence=confidence,
                            reason=reason,
                            cancel_reason=cancel_reason,
                            raw_payload={**item, **ai_result},
                        )

                    await cancel_open_position_by_signal(pg_pool, db_id)

    except Exception as err:
        logger.error("[Worker] processing failed [%s %s]: %s", stk_cd, strategy, err)
        failure_payload = _build_failure_payload(item, strategy, stk_cd, err)
        normalize_signal_prices(failure_payload)

        try:
            dead_payload = json.dumps(failure_payload, ensure_ascii=False, default=str)
            await rdb.lpush("error_queue", dead_payload)
            await rdb.expire("error_queue", 86400)
        except Exception as dlq_err:
            logger.error("[Worker] error_queue publish failed: %s", dlq_err)

        try:
            await push_score_only_queue(rdb, failure_payload)
        except Exception as push_err:
            logger.error(
                "[Worker] failure payload publish failed [%s %s]: %s",
                stk_cd,
                strategy,
                push_err,
            )

    return True


async def run_worker(rdb, pg_pool=None):
    logger.info("[Worker] queue worker started (poll_interval=%.1fs)", POLL_INTERVAL)
    consecutive_empty = 0

    while True:
        try:
            processed = await process_one(rdb, pg_pool)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                wait = min(POLL_INTERVAL * (1 + consecutive_empty * 0.1), 10.0)
                await asyncio.sleep(wait)
        except Exception as err:
            logger.error("[Worker] loop error: %s", err)
            await asyncio.sleep(5)
