from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any


def build_failure_payload(
    item: dict,
    *,
    strategy: str,
    stk_cd: str,
    error: Exception,
    failure_type: str = "PROCESSING_ERROR",
    failure_action: str = "FAILED",
    now_fn: Callable[[], float] | None = None,
) -> dict:
    return {
        **item,
        "type": failure_type,
        "action": failure_action,
        "confidence": "LOW",
        "rule_score": None,
        "ai_score": 0.0,
        "ai_reason": f"queue_worker processing failed: {type(error).__name__}",
        "error": str(error),
        "error_type": type(error).__name__,
        "failed_stage": "queue_worker",
        "execution_decision": "BLOCK",
        "stk_cd": stk_cd,
        "strategy": strategy,
        "skip_entry": True,
        "error_ts": (now_fn or time.time)(),
    }


async def publish_failure_payload(
    *,
    rdb: Any,
    payload: dict,
    push_score_only_queue_fn: Callable[[Any, dict], Awaitable[Any]],
    logger: Any | None = None,
    error_queue: str = "error_queue",
    error_queue_ttl_sec: int = 86400,
) -> None:
    try:
        dead_payload = json.dumps(payload, ensure_ascii=False, default=str)
        await rdb.lpush(error_queue, dead_payload)
        await rdb.expire(error_queue, error_queue_ttl_sec)
    except Exception as dlq_err:
        if logger:
            logger.error("[Worker] error_queue publish failed: %s", dlq_err)

    try:
        await push_score_only_queue_fn(rdb, payload)
    except Exception as push_err:
        if logger:
            logger.error(
                "[Worker] failure payload publish failed [%s %s]: %s",
                payload.get("stk_cd"),
                payload.get("strategy"),
                push_err,
            )


async def handle_processing_failure(
    *,
    rdb: Any,
    item: dict,
    strategy: str,
    stk_cd: str,
    error: Exception,
    normalize_signal_prices_fn: Callable[[dict], Any],
    push_score_only_queue_fn: Callable[[Any, dict], Awaitable[Any]],
    logger: Any | None = None,
    now_fn: Callable[[], float] | None = None,
) -> dict:
    payload = build_failure_payload(
        item,
        strategy=strategy,
        stk_cd=stk_cd,
        error=error,
        now_fn=now_fn,
    )
    normalize_signal_prices_fn(payload)
    await publish_failure_payload(
        rdb=rdb,
        payload=payload,
        push_score_only_queue_fn=push_score_only_queue_fn,
        logger=logger,
    )
    return payload
