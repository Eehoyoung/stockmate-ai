from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

_KST = timezone(timedelta(hours=9))


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
