from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from utils import normalize_stock_code


STRATEGY_NAME = "S16_ACCUMULATION_SHADOW"

STATE_DISCOVERED = "DISCOVERED"
STATE_ACCUMULATING = "ACCUMULATING"
STATE_ARMED = "ARMED"
STATE_TRIGGERED = "TRIGGERED"
STATE_REJECTED = "REJECTED"

WATCH_KEY_PREFIX = "s16:watch:"
WATCH_ZSET = "s16:watch_zset"
ARMED_ZSET = "s16:armed_zset"
TRIGGER_QUEUE = "s16:trigger_queue"
EVENTS_KEY = "s16:events"


@dataclass
class S16WatchState:
    stk_cd: str
    state: str
    first_seen_at: int
    last_seen_at: int
    observe_days: int = 0
    market_cap_eok: float = 0.0
    accumulation_score: float = 0.0
    supply_score: float = 0.0
    trigger_score: float = 0.0
    risk_score: float = 0.0
    total_score: float = 0.0
    box_low: float = 0.0
    box_high: float = 0.0
    cur_prc: float = 0.0
    rr_ratio: float = 0.0
    last_reason: str = ""

    def to_redis_mapping(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def watch_key(stk_cd: str) -> str:
    return f"{WATCH_KEY_PREFIX}{normalize_stock_code(stk_cd)}"


def triggered_key(stk_cd: str, ymd: str) -> str:
    return f"s16:triggered:{normalize_stock_code(stk_cd)}:{ymd}"


def _coerce_state(stk_cd: str, data: dict[str, Any]) -> S16WatchState:
    now = int(time.time())
    return S16WatchState(
        stk_cd=normalize_stock_code(stk_cd or data.get("stk_cd", "")),
        state=str(data.get("state") or STATE_DISCOVERED),
        first_seen_at=int(float(data.get("first_seen_at") or now)),
        last_seen_at=int(float(data.get("last_seen_at") or now)),
        observe_days=int(float(data.get("observe_days") or 0)),
        market_cap_eok=float(data.get("market_cap_eok") or 0),
        accumulation_score=float(data.get("accumulation_score") or 0),
        supply_score=float(data.get("supply_score") or 0),
        trigger_score=float(data.get("trigger_score") or 0),
        risk_score=float(data.get("risk_score") or 0),
        total_score=float(data.get("total_score") or 0),
        box_low=float(data.get("box_low") or 0),
        box_high=float(data.get("box_high") or 0),
        cur_prc=float(data.get("cur_prc") or 0),
        rr_ratio=float(data.get("rr_ratio") or 0),
        last_reason=str(data.get("last_reason") or ""),
    )


async def load_watch_state(rdb, stk_cd: str) -> S16WatchState | None:
    code = normalize_stock_code(stk_cd)
    if not code:
        return None
    data = await rdb.hgetall(watch_key(code))
    if not data:
        return None
    return _coerce_state(code, data)


async def save_watch_state(
    rdb,
    state: S16WatchState,
    *,
    next_check_at: int | None = None,
    ttl_sec: int = 604800,
) -> None:
    code = normalize_stock_code(state.stk_cd)
    if not code:
        return
    state.stk_cd = code
    key = watch_key(code)
    await rdb.hset(key, mapping=state.to_redis_mapping())
    await rdb.expire(key, ttl_sec)
    if next_check_at is not None:
        await rdb.zadd(WATCH_ZSET, {code: int(next_check_at)})
    if state.state == STATE_ARMED:
        await rdb.zadd(ARMED_ZSET, {code: float(state.total_score)})


async def enqueue_trigger(rdb, payload: dict, *, ymd: str, ttl_sec: int = 21600) -> bool:
    code = normalize_stock_code(payload.get("stk_cd", ""))
    if not code:
        return False
    dedup_key = triggered_key(code, ymd)
    is_new = await rdb.set(dedup_key, "1", nx=True, ex=ttl_sec)
    if not is_new:
        return False
    item = dict(payload)
    item["stk_cd"] = code
    item["strategy"] = STRATEGY_NAME
    await rdb.lpush(TRIGGER_QUEUE, json.dumps(item, ensure_ascii=False))
    return True


async def pop_trigger(rdb) -> dict | None:
    raw = await rdb.rpop(TRIGGER_QUEUE)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["stk_cd"] = normalize_stock_code(data.get("stk_cd", ""))
    data["strategy"] = STRATEGY_NAME
    return data


async def record_event(rdb, event: dict, *, max_len: int = 500) -> None:
    item = dict(event)
    item.setdefault("ts", int(time.time()))
    await rdb.lpush(EVENTS_KEY, json.dumps(item, ensure_ascii=False))
    await rdb.ltrim(EVENTS_KEY, 0, max_len - 1)
