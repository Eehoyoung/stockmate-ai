from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta, timezone

from price_utils import normalize_signal_prices
from redis_reader import (
    clear_hold_monitor_queue,
    get_all_hold_monitor_items,
    remove_hold_monitor_item,
    pop_due_hold_monitor_items,
    push_score_only_queue,
    push_telegram_queue,
    requeue_hold_monitor_item,
)
from scorer import get_claude_threshold, rule_score, should_skip_ai
from tp_sl_engine import compute_rr
from utils import normalize_stock_code, safe_float as _fv

import queue_worker as qw

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

HOLD_MONITOR_INTERVAL_SEC = float(os.getenv("HOLD_MONITOR_INTERVAL_SEC", "5.0"))
HOLD_MONITOR_RECHECK_SEC = float(os.getenv("HOLD_MONITOR_RECHECK_SEC", "10.0"))
HOLD_MONITOR_AI_COOLDOWN_SEC = float(os.getenv("HOLD_MONITOR_AI_COOLDOWN_SEC", "300.0"))
# 룰 게이트는 통과했지만 직전 Claude 호출 대비 rule_score가 이만큼도 움직이지 않았다면
# 같은 판단을 반복해서 물어보는 셈이므로 Claude 재호출을 건너뛴다. 2026-08-12 관측:
# 종목 278470(S15)이 30분간 rule_score 90~100 유지 상태에서 60초 쿨다운마다 계속
# Claude를 호출했지만 ai_score가 72~76 사이 노이즈만 오갔음(방향성 없음, 30회 이상 낭비 호출).
HOLD_MONITOR_MIN_SCORE_DELTA = float(os.getenv("HOLD_MONITOR_MIN_SCORE_DELTA", "5.0"))
HOLD_MONITOR_MAX_AI_RECHECKS = int(os.getenv("HOLD_MONITOR_MAX_AI_RECHECKS", "2"))
HOLD_MONITOR_BATCH_LIMIT = int(os.getenv("HOLD_MONITOR_BATCH_LIMIT", "20"))
HOLD_MONITOR_CLOSE_HHMM = os.getenv("HOLD_MONITOR_CLOSE_HHMM", "15:30")
HOLD_MONITOR_USE_REST_FALLBACK = os.getenv("HOLD_MONITOR_USE_REST_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}
HOLD_MONITOR_MAX_REST_CALLS_PER_MIN = int(os.getenv("HOLD_MONITOR_MAX_REST_CALLS_PER_MIN", "30"))
HOLD_MONITOR_MAX_AGE_SEC = int(os.getenv("HOLD_MONITOR_MAX_AGE_SEC", "1800"))
# Must stay >= HOLD_MONITOR_MAX_AGE_SEC / HOLD_MONITOR_RECHECK_SEC (currently 1800/10=180),
# otherwise this cuts the observation window short long before the age limit ever applies.
# Found 2026-07-27: default of 6 gave a ~60s window instead of the intended ~30min, causing
# WATCH items to hit HOLD_RELEASED almost immediately after the HOLD_WATCH notice.
HOLD_MONITOR_MAX_ATTEMPTS = int(os.getenv("HOLD_MONITOR_MAX_ATTEMPTS", "180"))
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


def _score_stalled(payload: dict, r_score: float) -> bool:
    """직전 Claude 호출 시점의 rule_score와 비교해 유의미한 변화가 없으면 True.
    첫 호출(비교 대상 없음)은 항상 False — 최초 재평가 기회는 막지 않는다."""
    last = _fv(payload.get("hold_monitor_last_ai_rule_score"), None)
    if last is None:
        return False
    return abs(r_score - last) < HOLD_MONITOR_MIN_SCORE_DELTA


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


def _terminal_reason(payload: dict) -> str | None:
    enqueued_at = _fv(payload.get("hold_monitor_enqueued_at"), None)
    if enqueued_at is not None and (_now_kst().timestamp() - enqueued_at) > HOLD_MONITOR_MAX_AGE_SEC:
        return f"hold monitor max age exceeded {HOLD_MONITOR_MAX_AGE_SEC}s"
    attempts = int(_fv(payload.get("hold_monitor_attempts"), 0) or 0)
    if attempts >= HOLD_MONITOR_MAX_ATTEMPTS:
        return f"hold monitor max attempts exceeded {HOLD_MONITOR_MAX_ATTEMPTS}"
    return None


async def _notify_release(rdb, payload: dict, reason: str) -> None:
    """Notify Telegram that a WATCH item left the hold monitor without being promoted to ENTER."""
    notice = {**payload, "type": "HOLD_RELEASED", "release_reason": reason}
    try:
        await push_score_only_queue(rdb, notice)
        logger.info(
            "[HoldMonitor] released [%s %s] key=%s reason=%s",
            payload.get("stk_cd"), payload.get("strategy"), payload.get("hold_monitor_key"), reason,
        )
    except Exception as exc:
        logger.warning(
            "[HoldMonitor] release notice failed key=%s: %s", payload.get("hold_monitor_key"), exc
        )


async def _requeue(rdb, payload: dict, reason: str) -> bool:
    terminal = _terminal_reason(payload)
    if terminal:
        payload["hold_monitor_last_reason"] = terminal
        return False
    payload["hold_monitor_last_reason"] = reason
    payload["hold_monitor_attempts"] = int(_fv(payload.get("hold_monitor_attempts"), 0) or 0) + 1
    await requeue_hold_monitor_item(rdb, payload, delay_sec=HOLD_MONITOR_RECHECK_SEC)
    return True


async def evaluate_hold_item(rdb, payload: dict) -> dict:
    """Return a recheck candidate when a WATCH item improves, otherwise return {}."""
    normalize_signal_prices(payload)
    stk_cd = normalize_stock_code(payload.get("stk_cd", ""))
    strategy = str(payload.get("strategy") or "")
    if not stk_cd or not strategy:
        payload["hold_monitor_terminal_reason"] = "missing stk_cd or strategy"
        return {}
    terminal = _terminal_reason(payload)
    if terminal:
        payload["hold_monitor_terminal_reason"] = terminal
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
        payload["hold_monitor_last_gate"] = f"rule_score {r_score:.1f} below threshold {threshold:.1f}"
        return {}

    rr_reason = qw._rr_prefilter_reason(payload, ctx)
    s8_zone_reason = qw._s8_buy_zone_gate_failure(payload)
    s1_reason = qw._s1_fallback_quality_failure(payload, ctx)
    hard_reason = qw._hard_gate_failure(payload, ctx)
    stale_reason = qw._freshness_cancel_reason(ctx, strategy)
    if rr_reason or s8_zone_reason or s1_reason or hard_reason or stale_reason:
        payload["hold_monitor_last_gate"] = rr_reason or s8_zone_reason or s1_reason or hard_reason or stale_reason
        return {}

    # Rule-side gates alone can look "improved" every cycle even when Claude keeps
    # returning HOLD on the same fundamentals (observed 2026-07-29: stock 051900 looped
    # through this branch every ~10s for 15 minutes, firing a real Claude call each time).
    # Enforce HOLD_MONITOR_AI_COOLDOWN_SEC so a full re-analysis isn't triggered more often
    # than that, regardless of how often rule gates re-clear.
    if _recent_ai_call(payload):
        payload["hold_monitor_last_gate"] = "ai cooldown active"
        return {}

    # 쿨다운을 넘겨도 rule_score가 직전 Claude 호출 시점과 사실상 그대로라면 같은
    # 질문을 반복하는 것과 다름없다 — Claude 예산만 소모하고 방향성 있는 정보는
    # 얻지 못한다(2026-08-12 관측: 종목 278470이 30분간 90~100점을 유지하며 60초
    # 쿨다운마다 재호출됐지만 ai_score는 72~76 사이 노이즈만 오갔음). 점수가 실제로
    # 움직였을 때만 재호출한다.
    if _score_stalled(payload, r_score):
        payload["hold_monitor_last_gate"] = (
            f"score stalled (Δ<{HOLD_MONITOR_MIN_SCORE_DELTA:.1f} since last AI call)"
        )
        return {}

    ai_rechecks = int(_fv(payload.get("hold_monitor_ai_rechecks"), 0) or 0)
    if ai_rechecks >= HOLD_MONITOR_MAX_AI_RECHECKS:
        payload["hold_monitor_last_gate"] = "AI recheck limit reached"
        return {}

    payload["hold_monitor_last_ai_at"] = _now_kst().timestamp()
    payload["hold_monitor_last_ai_rule_score"] = r_score

    enriched = {
        **payload,
        "type": "HOLD_MONITOR_RECHECK",
        "action": "HOLD",
        "execution_decision": "WATCH",
        "signal_stage": "WATCH",
        "confidence": payload.get("confidence") or "MEDIUM",
        "rule_score": r_score,
        "ai_score": payload.get("ai_score", r_score),
        "ai_reason": "HOLD monitor conditions improved; re-enter queue_worker for full validation",
        "cancel_reason": None,
        "hold_monitor_recheck": True,
        "hold_monitor_ai_rechecks": ai_rechecks + 1,
        "hold_monitor_promoted": False,
        "origin_hold_monitor_key": payload.get("hold_monitor_key"),
        "hold_monitor_last_gate": None,
        "recompute_rule_score": True,
    }
    normalize_signal_prices(enriched)
    return enriched


async def process_due_items(rdb) -> int:
    items = await pop_due_hold_monitor_items(rdb, limit=HOLD_MONITOR_BATCH_LIMIT)
    promoted = 0
    for item in items:
        key = item.get("hold_monitor_key", "")
        try:
            result = await evaluate_hold_item(rdb, item)
            if result:
                await push_telegram_queue(rdb, result)
                if key:
                    await remove_hold_monitor_item(rdb, key)
                promoted += 1
                logger.info(
                    "[HoldMonitor] queued WATCH recheck [%s %s] key=%s",
                    result.get("stk_cd"),
                    result.get("strategy"),
                    key,
                )
            elif not _is_after_close():
                drop_reason = (
                    item.get("hold_monitor_terminal_reason")
                    or item.get("hold_monitor_last_gate")
                    or item.get("hold_monitor_last_reason")
                    or "still WATCH"
                )
                requeued = await _requeue(rdb, item, drop_reason)
                if not requeued and key:
                    await remove_hold_monitor_item(rdb, key)
                    await _notify_release(rdb, item, drop_reason)
        except Exception as exc:
            logger.warning("[HoldMonitor] evaluation failed key=%s: %s", key, exc)
            if not _is_after_close():
                drop_reason = f"error:{type(exc).__name__}"
                requeued = await _requeue(rdb, item, drop_reason)
                if not requeued and key:
                    await remove_hold_monitor_item(rdb, key)
                    await _notify_release(rdb, item, drop_reason)
    return promoted


async def _release_all_for_close(rdb) -> int:
    """Notify Telegram for every still-open WATCH item, then clear the hold monitor queue for the day."""
    stale_items = await get_all_hold_monitor_items(rdb)
    for stale in stale_items:
        await _notify_release(rdb, stale, f"장 마감({HOLD_MONITOR_CLOSE_HHMM}) — 관심종목 관찰 종료")
    await clear_hold_monitor_queue(rdb)
    return len(stale_items)


async def run_hold_monitor_worker(rdb):
    logger.info("[HoldMonitor] worker started interval=%ss close=%s", HOLD_MONITOR_INTERVAL_SEC, HOLD_MONITOR_CLOSE_HHMM)
    cleared_for_date: str | None = None
    while True:
        now = _now_kst()
        today = now.strftime("%Y-%m-%d")
        if _is_after_close(now):
            if cleared_for_date != today:
                released_count = await _release_all_for_close(rdb)
                cleared_for_date = today
                logger.info(
                    "[HoldMonitor] queue cleared for close %s (%d items released)",
                    HOLD_MONITOR_CLOSE_HHMM, released_count,
                )
            await asyncio.sleep(max(HOLD_MONITOR_INTERVAL_SEC, 30.0))
            continue
        cleared_for_date = None
        if _is_before_main_monitor_window(now):
            await asyncio.sleep(max(HOLD_MONITOR_INTERVAL_SEC, 10.0))
            continue
        await process_due_items(rdb)
        await asyncio.sleep(HOLD_MONITOR_INTERVAL_SEC)
