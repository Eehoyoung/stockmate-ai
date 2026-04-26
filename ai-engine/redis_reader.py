from __future__ import annotations

"""
redis_reader.py
Redis helpers for queue I/O and realtime market cache access.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


FRESHNESS_CUTOFFS_MS = {
    "hoga": {"caution": 1_000, "cancel": 2_000},
    "tick": {"caution": 3_000, "cancel": 5_000},
    "strength": {"caution": 5_000, "cancel": 10_000},
    "vi_active": {"caution": 3_000, "cancel": 5_000},
    "vi_released": {"caution": 10_000, "cancel": 20_000},
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return default


def _age_ms(data: dict, now_ms: int) -> tuple[int | None, int | None]:
    updated_at = _to_float(data.get("updated_at_ms"))
    if updated_at is None:
        return None, None
    return max(0, now_ms - int(updated_at)), int(updated_at)


def freshness_status(data: dict, kind: str, *, now_ms: int | None = None) -> dict:
    """
    Classify realtime Redis hash age.

    Missing timestamps are reported as missing for deploy compatibility and do not
    imply cancellation by themselves.
    """
    now = _now_ms() if now_ms is None else int(now_ms)
    cutoffs = FRESHNESS_CUTOFFS_MS[kind]
    if not data:
        return {"state": "missing", "kind": kind, "age_ms": None, "updated_at_ms": None}
    age, updated_at = _age_ms(data, now)
    if age is None:
        return {"state": "missing", "kind": kind, "age_ms": None, "updated_at_ms": None}
    if age > cutoffs["cancel"]:
        state = "cancel"
    elif age > cutoffs["caution"]:
        state = "caution"
    else:
        state = "fresh"
    return {"state": state, "kind": kind, "age_ms": age, "updated_at_ms": updated_at}


class RedisConnectionManager:
    """Manage a reusable Redis client with ping checks and reconnect backoff."""

    _BACKOFF_BASE = 1
    _BACKOFF_MAX = 60

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: Optional[str] = None,
        *,
        decode_responses: bool = True,
        socket_connect_timeout: int = 5,
        socket_timeout: int = 5,
        retry_on_timeout: bool = True,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.decode_responses = decode_responses
        self.socket_connect_timeout = socket_connect_timeout
        self.socket_timeout = socket_timeout
        self.retry_on_timeout = retry_on_timeout
        self._client = None
        self._lock = asyncio.Lock()

    def _make_client(self):
        return aioredis.Redis(
            host=self.host,
            port=self.port,
            password=self.password,
            decode_responses=self.decode_responses,
            socket_connect_timeout=self.socket_connect_timeout,
            socket_timeout=self.socket_timeout,
            retry_on_timeout=self.retry_on_timeout,
        )

    async def connect(self):
        client = self._make_client()
        try:
            await client.ping()
        except Exception:
            try:
                await client.aclose()
            except Exception:
                logger.debug("[RedisManager] close after failed connect also failed", exc_info=True)
            raise
        self._client = client
        return client

    async def reconnect(self):
        async with self._lock:
            await self.close()
            wait_time = self._BACKOFF_BASE
            while True:
                try:
                    return await self.connect()
                except Exception as exc:
                    logger.warning(
                        "[RedisManager] reconnect failed host=%s port=%s wait=%ss err=%s",
                        self.host,
                        self.port,
                        wait_time,
                        exc,
                    )
                    await asyncio.sleep(wait_time)
                    wait_time = min(wait_time * 2, self._BACKOFF_MAX)

    async def get_or_reconnect(self):
        client = self._client
        if client is None:
            return await self.connect()
        try:
            await client.ping()
            return client
        except Exception:
            logger.warning("[RedisManager] ping failed, reconnecting", exc_info=True)
            return await self.reconnect()

    async def close(self):
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            await client.aclose()
        except Exception:
            logger.warning("[RedisManager] close failed", exc_info=True)


async def pop_telegram_queue(rdb) -> Optional[dict]:
    """
    Pop one payload from telegram_queue with RPOP.
    Java SignalService pushes into the same list with LPUSH.
    """
    raw = await rdb.rpop("telegram_queue")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("[Reader] telegram_queue JSON parse failed: %s / raw=%.80s", exc, raw)
        return None


async def get_tick_data(rdb, stk_cd: str) -> dict:
    """Return the realtime tick hash for a stock code."""
    data = await rdb.hgetall(f"ws:tick:{stk_cd}")
    return data or {}


async def get_hoga_data(rdb, stk_cd: str) -> dict:
    """Return the realtime orderbook hash for a stock code."""
    data = await rdb.hgetall(f"ws:hoga:{stk_cd}")
    return data or {}


async def get_avg_cntr_strength(rdb, stk_cd: str, count: int = 5) -> float:
    """Return the average execution strength over the most recent N samples."""
    values = await rdb.lrange(f"ws:strength:{stk_cd}", 0, count - 1)
    if not values:
        return 100.0
    nums = []
    for value in values:
        try:
            nums.append(float(str(value).replace(",", "").replace("+", "")))
        except ValueError:
            pass
    return round(sum(nums) / len(nums), 2) if nums else 100.0


async def get_strength_meta(rdb, stk_cd: str) -> dict:
    """Return metadata for realtime execution strength samples."""
    data = await rdb.hgetall(f"ws:strength_meta:{stk_cd}")
    return data or {}


async def get_market_freshness(rdb, stk_cd: str, *, now_ms: int | None = None) -> dict:
    """Return freshness states for realtime market-data hashes."""
    tick, hoga, strength_meta, vi = await asyncio.gather(
        get_tick_data(rdb, stk_cd),
        get_hoga_data(rdb, stk_cd),
        get_strength_meta(rdb, stk_cd),
        get_vi_status(rdb, stk_cd),
    )
    vi_status = str((vi or {}).get("status", "")).lower()
    vi_kind = "vi_active" if vi_status == "active" else "vi_released"
    return {
        "tick": freshness_status(tick, "tick", now_ms=now_ms),
        "hoga": freshness_status(hoga, "hoga", now_ms=now_ms),
        "strength": freshness_status(strength_meta, "strength", now_ms=now_ms),
        "vi": freshness_status(vi, vi_kind, now_ms=now_ms),
    }


async def get_strength_trend(rdb, stk_cd: str, count: int = 10) -> dict:
    """Return simple trend stats from recent execution strength samples."""
    values = await rdb.lrange(f"ws:strength:{stk_cd}", 0, count - 1)
    nums: list[float] = []
    for value in values:
        try:
            nums.append(float(str(value).replace(",", "").replace("+", "")))
        except ValueError:
            pass
    if not nums:
        return {
            "avg_all": 100.0,
            "avg_recent": 100.0,
            "avg_older": 100.0,
            "declining": False,
            "count": 0,
        }
    recent = nums[:3]
    older = nums[3:] if len(nums) > 3 else nums
    avg_all = round(sum(nums) / len(nums), 2)
    avg_recent = round(sum(recent) / len(recent), 2)
    avg_older = round(sum(older) / len(older), 2)
    declining = avg_recent < avg_older - 5.0
    return {
        "avg_all": avg_all,
        "avg_recent": avg_recent,
        "avg_older": avg_older,
        "declining": declining,
        "count": len(nums),
    }


async def get_hoga_ratio(rdb, stk_cd: str) -> float:
    """
    Return sell/buy orderbook pressure ratio.
    >1.0 means sell-side pressure.
    """
    data = await rdb.hgetall(f"ws:hoga:{stk_cd}")
    if not data:
        return 1.0
    try:
        sell = float(str(data.get("total_sel_bid_req", 0)).replace(",", "") or 0)
        buy = float(str(data.get("total_buy_bid_req", 1)).replace(",", "") or 1)
        if buy <= 0:
            return 2.0
        return round(sell / buy, 3)
    except (TypeError, ValueError):
        return 1.0


async def get_vi_status(rdb, stk_cd: str) -> dict:
    """Return the VI status hash for a stock code."""
    data = await rdb.hgetall(f"vi:{stk_cd}")
    return data or {}


async def push_score_only_queue(rdb, payload: dict):
    """Push a scored payload to ai_scored_queue without Telegram-specific wrapping."""
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.error("[Reader] ai_scored_queue serialization failed: %s", exc)
        return
    await rdb.lpush("ai_scored_queue", serialized)
    await rdb.expire("ai_scored_queue", 43200)


async def get_sector_overheat_count(rdb, sector: str) -> int:
    """Java SignalService 가 signal:sector:{sector} 에 기록하는 1시간 카운터를 읽는다."""
    if not sector:
        return 0
    try:
        val = await rdb.get(f"signal:sector:{sector}")
        return int(val) if val else 0
    except Exception:
        return 0


async def get_market_index_flu_rt(rdb) -> dict:
    """TradingScheduler 가 캐시한 KOSPI/KOSDAQ 등락률을 읽는다."""
    try:
        kospi = await rdb.get("market:kospi_flu_rt")
        kosdaq = await rdb.get("market:kosdaq_flu_rt")
        return {
            "kospi_flu_rt": float(kospi) if kospi else None,
            "kosdaq_flu_rt": float(kosdaq) if kosdaq else None,
        }
    except Exception:
        return {"kospi_flu_rt": None, "kosdaq_flu_rt": None}


async def get_stock_market_cap(rdb, stk_cd: str) -> int | None:
    """StockMasterScheduler 가 캐시한 시가총액(억 원)을 읽는다."""
    try:
        val = await rdb.get(f"stock:mktcap:{stk_cd}")
        return int(val) if val else None
    except Exception:
        return None


from confirm_gate_redis import (  # noqa: E402, F401
    CONFIRM_PENDING_PFX,
    CONFIRM_TIMEOUT_SEC,
    CONFIRMED_QUEUE,
    HUMAN_CONFIRM_QUEUE,
    pop_confirmed_queue,
    push_confirmed_queue,
    push_human_confirm_queue,
)
