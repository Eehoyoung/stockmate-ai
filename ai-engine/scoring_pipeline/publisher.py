from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def route_execution_payload(
    *,
    rdb: Any,
    payload: dict,
    strategy: str,
    stk_cd: str,
    execution_decision: str,
    display_reason: str,
    push_hold_monitor_queue_fn: Callable[[Any, dict], Awaitable[Any]],
    push_score_only_queue_fn: Callable[[Any, dict], Awaitable[Any]],
    incr_pipeline_fn: Callable[[Any, str, str], Awaitable[Any]],
    logger: Any | None = None,
) -> str:
    """Route a canonical execution payload to the appropriate queue."""
    decision = str(execution_decision or "").upper()
    if decision == "WATCH":
        await push_hold_monitor_queue_fn(rdb, payload)
        await incr_pipeline_fn(rdb, strategy, "hold_monitor")
        if logger:
            logger.info("[Worker] WATCH routed to monitor queue [%s %s]", stk_cd, strategy)
        return "WATCH"

    if decision == "ENTER":
        await push_score_only_queue_fn(rdb, payload)
        return "ENTER"

    if logger:
        logger.info("[Worker] BLOCK kept internal [%s %s] reason=%s", stk_cd, strategy, display_reason)
    return "BLOCK"
