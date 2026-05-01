from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def flag_enabled(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def cache_get_json(rdb, key: str, default: Any = None) -> Any:
    if not rdb:
        return default
    try:
        raw = await rdb.get(key)
        if raw is None:
            return default
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception as exc:
        logger.debug("[strategy_cache] get failed key=%s: %s", key, exc)
        return default


async def cache_set_json(rdb, key: str, value: Any, ttl: int) -> None:
    if not rdb or ttl <= 0:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False)
        setex = getattr(rdb, "setex", None)
        if setex:
            await setex(key, ttl, payload)
            return
        await rdb.set(key, payload)
        expire = getattr(rdb, "expire", None)
        if expire:
            await expire(key, ttl)
    except Exception as exc:
        logger.debug("[strategy_cache] set failed key=%s: %s", key, exc)
