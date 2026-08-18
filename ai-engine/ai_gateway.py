"""Single audited entry point for Claude API calls."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)
_pool = None


def configure(pool) -> None:
    global _pool
    _pool = pool


def _usage(response) -> tuple[int, int, int, int]:
    usage = getattr(response, "usage", None)
    return tuple(int(getattr(usage, name, 0) or 0) for name in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"
    ))


def _cost_usd(model: str, tokens: tuple[int, int, int, int]) -> Decimal:
    # Anthropic global standard pricing per million tokens, 2026-05-27.
    if "haiku" in model:
        rates = (1, 5, Decimal("1.25"), Decimal("0.10"))
    elif "opus-4-6" in model or "opus-4-5" in model:
        rates = (5, 25, Decimal("6.25"), Decimal("0.50"))
    elif "opus" in model:
        rates = (15, 75, Decimal("18.75"), Decimal("1.50"))
    else:
        rates = (3, 15, Decimal("3.75"), Decimal("0.30"))
    return sum(Decimal(count) * Decimal(rate) for count, rate in zip(tokens, rates)) / Decimal(1_000_000)


async def _record(**row: Any) -> None:
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO ai_api_usage
                   (provider, purpose, model, request_id, status, input_tokens, output_tokens,
                    cache_write_tokens, cache_read_tokens, cost_usd, duration_ms, metadata,
                    error_type, error_message)
                   VALUES ('anthropic',$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13)""",
                row["purpose"], row["model"], row.get("request_id"), row["status"],
                *row["tokens"], row["cost"], row["duration_ms"],
                json.dumps(row.get("metadata") or {}, ensure_ascii=False),
                row.get("error_type"), row.get("error_message"),
            )
    except Exception as exc:
        logger.warning("[AIGateway] usage audit write failed: %s", exc)


async def create_message(client, *, purpose: str, metadata: dict | None = None, **request):
    """Call Claude and persist success/failure usage without breaking the caller on audit failure."""
    started = time.perf_counter()
    model = str(request.get("model", "unknown"))
    try:
        response = await client.messages.create(**request)
        tokens = _usage(response)
        await _record(
            purpose=purpose, model=model, request_id=getattr(response, "id", None), status="SUCCESS",
            tokens=tokens, cost=_cost_usd(model, tokens), duration_ms=int((time.perf_counter() - started) * 1000),
            metadata=metadata,
        )
        return response
    except asyncio.CancelledError:
        await asyncio.shield(_record(
            purpose=purpose, model=model, status="ERROR", tokens=(0, 0, 0, 0), cost=Decimal(0),
            duration_ms=int((time.perf_counter() - started) * 1000), metadata=metadata,
            error_type="CancelledError", error_message="request cancelled or timed out",
        ))
        raise
    except Exception as exc:
        await _record(
            purpose=purpose, model=model, status="ERROR", tokens=(0, 0, 0, 0), cost=Decimal(0),
            duration_ms=int((time.perf_counter() - started) * 1000), metadata=metadata,
            error_type=type(exc).__name__, error_message=str(exc)[:1000],
        )
        raise


async def purge_old_usage() -> None:
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM ai_api_usage WHERE created_at < now() - interval '90 days'")
    except Exception as exc:
        logger.warning("[AIGateway] retention cleanup skipped: %s", exc)
