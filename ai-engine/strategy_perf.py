from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def perf_timer(name: str, rdb=None, fields: dict | None = None):
    enabled = str(os.getenv("STRATEGY_PERF_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        labels = fields or {}
        logger.debug("[strategy_perf] %s elapsed_ms=%d fields=%s", name, elapsed_ms, labels)
        if rdb:
            try:
                key = f"status:strategy_perf:{name}"
                await rdb.hincrby(key, "count", 1)
                await rdb.hincrby(key, "elapsed_ms_total", elapsed_ms)
                expire = getattr(rdb, "expire", None)
                if expire:
                    await expire(key, 3600)
            except Exception as exc:
                logger.debug("[strategy_perf] metric write failed %s: %s", name, exc)
