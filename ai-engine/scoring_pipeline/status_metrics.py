from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Callable

_KST = timezone(timedelta(hours=9))
_MARKET_DATA_FIELDS = ("tick", "hoga", "strength", "vi")


def _nonnegative_number(value: Any) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if number.is_integer() else number


def _failure_class(value: Any) -> str:
    text = str(value or "").lower()
    for known in (
        "budget_exhausted",
        "rest_disabled",
        "rest_no_data",
        "no_token",
        "signal_stale_or_undated",
        "current_bar_open",
        "empty",
    ):
        if known in text:
            return known
    return "error"


def build_market_data_observability(ctx: dict) -> dict:
    """Build a stable, low-cardinality freshness/fallback snapshot for signals and metrics."""
    freshness = ctx.get("freshness") or {}
    refresh_meta = ctx.get("refresh_meta") or {}
    sources = refresh_meta.get("market_data_sources") or {}
    attempted = refresh_meta.get("data_refresh_attempted") or {}
    failures = [str(value) for value in (refresh_meta.get("retry_failures") or [])]

    fields = {}
    cache_fields = []
    for kind in _MARKET_DATA_FIELDS:
        status = freshness.get(kind) or {}
        state = str(status.get("state") or "missing").lower()
        source = str(sources.get(kind) or status.get("source") or (
            "missing" if state == "missing" else "redis"
        )).lower()
        fields[kind] = {
            "state": state,
            "source": source,
            "age_ms": _nonnegative_number(status.get("age_ms")),
        }
        if source in {"redis", "cache", "redis_cache", "ws"}:
            cache_fields.append(kind)

    budget = refresh_meta.get("rest_budget") or {}
    budget_state = str(budget.get("state") or "").lower()
    if not budget_state:
        budget_state = "exhausted" if any("budget_exhausted" in value.lower() for value in failures) else "not_reported"

    rest_fields = sorted(kind for kind in _MARKET_DATA_FIELDS if sources.get(kind) == "rest")
    attempted_fields = sorted(str(kind) for kind in attempted)
    return {
        "schema_version": 1,
        "fields": fields,
        "cache_fields": cache_fields,
        "rest": {
            "fallback_used": bool(rest_fields),
            "fallback_fields": rest_fields,
            "attempted_fields": attempted_fields,
            "failures": failures,
            "failure_classes": sorted({_failure_class(value) for value in failures}),
            "budget_state": budget_state,
            "budget_used": _nonnegative_number(budget.get("used")),
            "budget_limit": _nonnegative_number(budget.get("limit")),
            "budget_remaining": _nonnegative_number(budget.get("remaining")),
        },
    }


async def record_market_data_observability_metric(
    rdb: Any,
    *,
    strategy: str,
    snapshot: dict,
    ttl_sec: int,
    now_fn: Callable[[], datetime] | None = None,
    logger: Any | None = None,
) -> str | None:
    """Best-effort daily source, freshness, REST, cache, and budget counters."""
    if not strategy:
        return None
    try:
        now = now_fn() if now_fn else datetime.now(_KST)
        key = f"status:market_data_observability:{now.strftime('%Y-%m-%d')}:{strategy}"
        for kind, status in (snapshot.get("fields") or {}).items():
            await rdb.hincrby(key, f"{kind}.state.{status.get('state', 'missing')}", 1)
            await rdb.hincrby(key, f"{kind}.source.{status.get('source', 'missing')}", 1)
        rest = snapshot.get("rest") or {}
        await rdb.hincrby(key, f"rest.fallback_used.{str(bool(rest.get('fallback_used'))).lower()}", 1)
        await rdb.hincrby(key, f"rest.budget.{rest.get('budget_state') or 'not_reported'}", 1)
        await rdb.hincrby(key, f"cache.used.{str(bool(snapshot.get('cache_fields'))).lower()}", 1)
        for failure in rest.get("failure_classes") or []:
            await rdb.hincrby(key, f"rest.failure.{failure}", 1)
        await rdb.expire(key, ttl_sec)
        return key
    except Exception as err:
        if logger:
            logger.debug("[Worker] market-data observability metric failed [%s]: %s", strategy, err)
        return None


async def record_freshness_decision_metric(
    rdb: Any,
    *,
    strategy: str,
    decision: str,
    ttl_sec: int,
    now_fn: Callable[[], datetime] | None = None,
    logger: Any | None = None,
) -> str | None:
    """Best-effort daily freshness decision metric."""
    if not strategy:
        return None
    try:
        now = now_fn() if now_fn else datetime.now(_KST)
        key = f"status:freshness_decision:{now.strftime('%Y-%m-%d')}:{strategy}"
        await rdb.hincrby(key, decision, 1)
        await rdb.expire(key, ttl_sec)
        return key
    except Exception as err:
        if logger:
            logger.debug("[Worker] freshness decision metric failed [%s %s]: %s", strategy, decision, err)
        return None


async def record_execution_decision_metric(
    rdb: Any,
    *,
    strategy: str,
    decision: str,
    ttl_sec: int,
    logger: Any | None = None,
) -> str | None:
    """Best-effort short-window execution decision metric."""
    try:
        key = f"status:decisions_10m:{strategy}:{decision}"
        await rdb.incr(key)
        await rdb.expire(key, ttl_sec)
        return key
    except Exception as err:
        if logger:
            logger.debug("[Worker] status decision metric failed [%s %s]: %s", strategy, decision, err)
        return None
