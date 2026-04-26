from __future__ import annotations
"""
confirm_worker.py
인간 컨펌 완료 신호를 confirmed_queue 에서 꺼내 Claude API 분석 후
ai_scored_queue 에 발행하는 워커.
"""

import asyncio
import logging
import os

from analyzer import analyze_signal
from confirm_gate_redis import pop_confirmed_queue
from db_writer import (
    update_human_confirm_request_status,
    confirm_open_position,
    cancel_open_position_by_signal,
    insert_ai_cancel_signal,
    insert_rule_cancel_signal,
)
from price_utils import normalize_signal_prices
from redis_reader import push_score_only_queue
from scorer import check_daily_limit, rule_score
from tp_sl_engine import compute_rr
from utils import safe_float as _fv

logger = logging.getLogger(__name__)
RR_HARD_CANCEL_THRESHOLD = float(os.getenv("RR_HARD_CANCEL_THRESHOLD", "0.8"))
HOLD_TO_ENTER_MIN_AI_SCORE = float(os.getenv("HOLD_TO_ENTER_MIN_AI_SCORE", "80.0"))


def _resolve_display_reason(action: str, reason: str, cancel_reason: str | None) -> str:
    if action == "CANCEL" and cancel_reason:
        return cancel_reason
    return reason


def _maybe_promote_hold_to_enter(result: dict) -> dict:
    """Promote high-score Claude HOLD decisions into actionable ENTER signals."""
    if str(result.get("action", "")).upper() != "HOLD":
        return result
    try:
        score = float(result.get("ai_score"))
    except (TypeError, ValueError):
        return result
    if score < HOLD_TO_ENTER_MIN_AI_SCORE:
        return result

    promoted = dict(result)
    reason = str(promoted.get("reason") or "").strip() or "Claude HOLD"
    promoted["action"] = "ENTER"
    promoted["cancel_reason"] = None
    promoted["confidence"] = promoted.get("confidence") or "HIGH"
    promoted["reason"] = (
        f"{reason} | HOLD promoted to ENTER because ai_score "
        f"{score:.1f} >= {HOLD_TO_ENTER_MIN_AI_SCORE:.1f}"
    )
    return promoted


def _raw_rr(entry, tp, sl) -> float | None:
    entry_f = _fv(entry, None)
    tp_f = _fv(tp, None)
    sl_f = _fv(sl, None)
    if entry_f is None or tp_f is None or sl_f is None:
        return None
    if entry_f <= 0 or tp_f <= entry_f or sl_f >= entry_f:
        return None
    risk = entry_f - sl_f
    if risk <= 0:
        return None
    return round((tp_f - entry_f) / risk, 3)


def _apply_claude_rr_override(payload: dict) -> dict:
    if payload.get("action") != "ENTER":
        return payload
    entry = _fv(payload.get("cur_prc") or payload.get("entry_price"), None)
    claude_tp = _fv(payload.get("claude_tp1"), None)
    claude_sl = _fv(payload.get("claude_sl"), None)
    if entry is None or claude_tp is None or claude_sl is None:
        return payload
    min_rr = _fv(payload.get("min_rr_ratio"), None)
    rr, skip = compute_rr(
        str(payload.get("stk_cd", "")),
        entry,
        claude_tp,
        claude_sl,
        min_rr=min_rr if min_rr is not None else None,
    )
    payload["rr_ratio"] = rr
    payload["effective_rr"] = rr
    payload["single_tp_rr"] = _raw_rr(entry, claude_tp, claude_sl)
    payload["raw_rr"] = payload["single_tp_rr"]
    payload["rr_basis"] = "claude_tp_sl"
    if rr < RR_HARD_CANCEL_THRESHOLD:
        reason = f"Claude TP/SL R:R {rr:.2f} below {RR_HARD_CANCEL_THRESHOLD:.2f}"
        payload["action"] = "CANCEL"
        payload["confidence"] = "LOW"
        payload["cancel_reason"] = reason
        payload["ai_reason"] = reason
        payload["rr_skip_reason"] = reason
    elif skip and not payload.get("rr_skip_reason") and min_rr is not None:
        payload["rr_skip_reason"] = f"Claude TP/SL effective_rr {rr:.2f} < min_rr {min_rr:.2f}"
    return payload


def _resolve_execution_strength(item: dict, ctx: dict) -> float:
    signal_strength = item.get("cntr_strength")
    if signal_strength is None:
        signal_strength = item.get("cntr_str")
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


async def process_confirmed(rdb, pg_pool=None) -> bool:
    """
    confirmed_queue 에서 항목 1개 처리.
    처리 항목이 있으면 True, 없으면 False 반환.
    """
    item = await pop_confirmed_queue(rdb)
    if not item:
        return False
    normalize_signal_prices(item)

    stk_cd   = item.get("stk_cd", "")
    strategy = item.get("strategy", "")
    ctx      = item.get("market_ctx", {})
    exact_strength = _resolve_execution_strength(item, ctx)
    ctx["strength"] = exact_strength
    if exact_strength > 0:
        item["cntr_strength"] = round(exact_strength, 2)
    request_key = item.get("confirm_request_key")
    recompute_rule = bool(item.get("recompute_rule_score"))

    if recompute_rule:
        r_score, _ = rule_score(item, ctx)
        item["rule_score"] = r_score
    else:
        r_score  = float(item.get("rule_score", 0))

    logger.info("[ConfirmWorker] Claude 분석 시작 [%s %s] rule_score=%.1f", stk_cd, strategy, r_score)

    try:
        cancel_type = None
        within_limit = await check_daily_limit(rdb)
        if not within_limit:
            result = {
                "action": "CANCEL",
                "ai_score": r_score,
                "confidence": "LOW",
                "reason": "Claude daily limit reached",
                "cancel_reason": "AI daily limit reached",
            }
            cancel_type = "AI_DAILY_LIMIT"
        else:
            try:
                result = await analyze_signal(item, ctx, r_score, rdb=rdb)
            except Exception as claude_err:
                logger.warning(
                    "[ConfirmWorker] Claude 오류 [%s %s]: %s – CANCEL",
                    stk_cd, strategy, claude_err
                )
                result = {
                    "action": "CANCEL",
                    "ai_score": r_score,
                    "confidence": "LOW",
                    "reason": f"Claude unavailable: {type(claude_err).__name__}",
                    "cancel_reason": "AI analysis unavailable",
                }
                cancel_type = "AI_UNAVAILABLE"

        result = _maybe_promote_hold_to_enter(result)
        display_reason = _resolve_display_reason(
            result.get("action", "HOLD"),
            result.get("reason", ""),
            result.get("cancel_reason"),
        )

        enriched = {
            **item,
            "ai_score":            result.get("ai_score", r_score),
            "action":              result.get("action", "HOLD"),
            "confidence":          result.get("confidence", "LOW"),
            "ai_reason":           display_reason,
            "cancel_reason":       result.get("cancel_reason"),
            "adjusted_target_pct": result.get("adjusted_target_pct"),
            "adjusted_stop_pct":   result.get("adjusted_stop_pct"),
            "claude_tp1":          result.get("claude_tp1"),
            "claude_tp2":          None,
            "claude_sl":           result.get("claude_sl"),
            "tp2_price":           None,
            "human_confirmed":     True,
        }
        # market_ctx 는 큰 데이터이므로 발행 전 제거
        normalize_signal_prices(enriched)
        enriched = _apply_claude_rr_override(enriched)
        enriched.pop("market_ctx", None)
        await push_score_only_queue(rdb, enriched)
        if pg_pool:
            signal_id = enriched.get("id")
            action    = enriched.get("action", "")
            if signal_id and action == "ENTER":
                await confirm_open_position(
                    pg_pool, signal_id,
                    ai_score=enriched.get("ai_score"),
                    tp1_price=enriched.get("claude_tp1") or enriched.get("tp1_price"),
                    tp2_price=None,
                    sl_price=enriched.get("claude_sl")  or enriched.get("sl_price"),
                    rr_ratio=enriched.get("rr_ratio"),
                    trailing_pct=enriched.get("trailing_pct"),
                    trailing_activation=enriched.get("trailing_activation"),
                    trailing_basis=enriched.get("trailing_basis"),
                    strategy_version=enriched.get("strategy_version"),
                    time_stop_type=enriched.get("time_stop_type"),
                    time_stop_minutes=enriched.get("time_stop_minutes"),
                    time_stop_session=enriched.get("time_stop_session"),
                    raw_rr=enriched.get("raw_rr"),
                    single_tp_rr=enriched.get("single_tp_rr"),
                    effective_rr=enriched.get("effective_rr"),
                    min_rr_ratio=enriched.get("min_rr_ratio"),
                    rr_skip_reason=enriched.get("rr_skip_reason"),
                    stop_max_pct=enriched.get("stop_max_pct"),
                    tp_policy_version=enriched.get("tp_policy_version"),
                    sl_policy_version=enriched.get("sl_policy_version"),
                    exit_policy_version=enriched.get("exit_policy_version"),
                    allow_overnight=enriched.get("allow_overnight"),
                    allow_reentry=enriched.get("allow_reentry"),
                )
            elif signal_id and action == "CANCEL":
                if cancel_type:
                    await insert_rule_cancel_signal(
                        pg_pool,
                        signal_id=signal_id,
                        stk_cd=stk_cd,
                        strategy=strategy,
                        rule_score=r_score,
                        cancel_type=cancel_type,
                        reason=display_reason,
                        raw_payload={**item, "result": result},
                    )
                else:
                    await insert_ai_cancel_signal(
                        pg_pool,
                        signal_id=signal_id,
                        stk_cd=stk_cd,
                        strategy=strategy,
                        ai_score=enriched.get("ai_score"),
                        confidence=enriched.get("confidence"),
                        reason=result.get("reason"),
                        cancel_reason=result.get("cancel_reason"),
                        raw_payload={**item, "result": result},
                    )
                await cancel_open_position_by_signal(pg_pool, signal_id)
            if request_key:
                await update_human_confirm_request_status(
                    pg_pool,
                    request_key,
                    status="COMPLETED",
                    ai_score=enriched["ai_score"],
                    ai_action=enriched["action"],
                    ai_confidence=enriched["confidence"],
                    ai_reason=enriched.get("ai_reason"),
                )
        logger.info(
            "[ConfirmWorker] 발행 완료 [%s %s] action=%s ai_score=%.1f",
            stk_cd, strategy, enriched["action"], enriched["ai_score"]
        )

    except Exception as e:
        logger.error("[ConfirmWorker] 처리 오류 [%s %s]: %s", stk_cd, strategy, e)

        if pg_pool and request_key:
            await update_human_confirm_request_status(
                pg_pool,
                request_key,
                status="FAILED",
                ai_reason=str(e),
            )

    return True


async def run_confirm_worker(rdb, pg_pool=None):
    """confirmed_queue 폴링 루프"""
    logger.info("[ConfirmWorker] 시작")
    consecutive_empty = 0

    while True:
        try:
            processed = await process_confirmed(rdb, pg_pool)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                wait = min(1.0 * (1 + consecutive_empty * 0.1), 5.0)
                await asyncio.sleep(wait)
        except Exception as e:
            logger.error("[ConfirmWorker] 루프 오류: %s", e)
            await asyncio.sleep(5)
