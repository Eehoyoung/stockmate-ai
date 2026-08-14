from __future__ import annotations

"""
redis_reader.py
Redis helpers for queue I/O and realtime market cache access.
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

HOLD_MONITOR_QUEUE = "hold_monitor_queue"
HOLD_MONITOR_ITEMS = "hold_monitor:items"
HOLD_MONITOR_WATCHLIST = "hold_monitor:watchlist"
HOLD_MONITOR_TTL_SEC = int(os.getenv("HOLD_MONITOR_TTL_SEC", "43200"))


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


async def push_telegram_queue(rdb, payload: dict, *, ttl: int = 43200) -> None:
    """Push a candidate payload back to telegram_queue for normal queue_worker processing."""
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.error("[Reader] telegram_queue serialization failed: %s", exc)
        return
    await rdb.lpush("telegram_queue", serialized)
    await rdb.expire("telegram_queue", ttl)


async def get_tick_data(rdb, stk_cd: str) -> dict:
    """Return the realtime tick hash for a stock code."""
    data = await rdb.hgetall(f"ws:tick:{stk_cd}")
    return data or {}


async def get_hoga_data(rdb, stk_cd: str) -> dict:
    """Return the realtime orderbook hash for a stock code."""
    data = await rdb.hgetall(f"ws:hoga:{stk_cd}")
    return data or {}


async def get_realtime_hash_with_status(
    rdb,
    stk_cd: str,
    kind: str,
    *,
    now_ms: int | None = None,
) -> dict:
    """Read a realtime hash and suppress values beyond the cancel cutoff.

    Only ``fresh`` and ``caution`` observations are returned as usable data.
    Missing timestamps are treated as missing instead of silently becoming a
    strong market observation.
    """
    if kind not in {"tick", "hoga"}:
        raise ValueError(f"unsupported realtime hash kind: {kind}")
    key = f"ws:{kind}:{stk_cd}"
    raw = await rdb.hgetall(key)
    status = freshness_status(raw or {}, kind, now_ms=now_ms)
    if status["state"] in {"fresh", "caution"}:
        return {"data": raw or {}, "status": status, "source": "redis"}
    source = "stale" if status["state"] == "cancel" else "missing"
    return {"data": {}, "status": status, "source": source}


async def get_tick_with_status(rdb, stk_cd: str, *, now_ms: int | None = None) -> dict:
    """Return freshness-checked ``ws:tick`` data."""
    return await get_realtime_hash_with_status(rdb, stk_cd, "tick", now_ms=now_ms)


async def get_hoga_with_status(rdb, stk_cd: str, *, now_ms: int | None = None) -> dict:
    """Return freshness-checked ``ws:hoga`` data."""
    return await get_realtime_hash_with_status(rdb, stk_cd, "hoga", now_ms=now_ms)


async def get_strength_with_status(
    rdb,
    stk_cd: str,
    count: int = 5,
    now_ms: int | None = None,
) -> dict:
    """
    ws:strength_meta 의 freshness 를 확인한 뒤 리스트 값을 반환한다.
    meta 가 missing/stale 이면 리스트 값이 있어도 stale/missing 으로 반환.
    반환:
    {
        "data": float | None,          # 평균 체결강도
        "status": {"state": "fresh|caution|cancel|missing", "age_ms": int, "kind": "strength"},
        "source": "redis|missing"
    }
    """
    now = _now_ms() if now_ms is None else int(now_ms)
    meta = await rdb.hgetall(f"ws:strength_meta:{stk_cd}")
    status = freshness_status(meta or {}, "strength", now_ms=now)

    _missing = {"data": None, "status": status, "source": "missing"}

    if status["state"] == "missing":
        return _missing

    if status["state"] == "cancel":
        return {"data": None, "status": status, "source": "stale"}

    # fresh or caution — 리스트에서 평균 계산
    values = await rdb.lrange(f"ws:strength:{stk_cd}", 0, count - 1)
    nums: list[float] = []
    for v in (values or []):
        try:
            nums.append(float(str(v).replace(",", "").replace("+", "")))
        except ValueError:
            pass

    if not nums:
        return {"data": None, "status": status, "source": "missing"}

    avg = round(sum(nums) / len(nums), 2)
    return {"data": avg, "status": status, "source": "redis"}


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


def _hold_monitor_key(payload: dict) -> str:
    strategy = str(payload.get("strategy") or "UNKNOWN").strip() or "UNKNOWN"
    stk_cd = str(payload.get("stk_cd") or "").strip()
    signal_id = str(payload.get("id") or "").strip()
    suffix = signal_id or stk_cd or str(int(time.time() * 1000))
    return f"{strategy}:{suffix}"


async def push_hold_monitor_queue(rdb, payload: dict, *, delay_sec: float = 0.0) -> str | None:
    """Store a HOLD payload in the dedicated monitor queue."""
    try:
        item = dict(payload)
        stk_cd = str(item.get("stk_cd") or "").strip()
        key = str(item.get("hold_monitor_key") or _hold_monitor_key(item))
        now = time.time()
        existing_score = await rdb.zscore(HOLD_MONITOR_QUEUE, key)
        existing_item = None
        if existing_score is not None and not item.get("hold_monitor_recheck"):
            raw_existing = await rdb.hget(HOLD_MONITOR_ITEMS, key)
            if raw_existing:
                try:
                    existing_item = json.loads(raw_existing)
                except (TypeError, json.JSONDecodeError):
                    existing_item = None
        item["hold_monitor_key"] = key
        item.setdefault(
            "hold_monitor_enqueued_at",
            (existing_item or {}).get("hold_monitor_enqueued_at", now),
        )
        if existing_score is None:
            # A newly routed WATCH has just completed its initial decision
            # path.  Seed the monitor cooldown so it cannot immediately send
            # the same candidate through a second full AI analysis.
            item.setdefault("hold_monitor_last_ai_at", now)
        if existing_score is not None and not item.get("hold_monitor_recheck"):
            # Repeated scanner output for the same WATCH must refresh its data,
            # but must not postpone the already scheduled evaluation forever.
            item["hold_monitor_next_check_at"] = float(existing_score)
        else:
            item["hold_monitor_next_check_at"] = now + max(0.0, float(delay_sec))
        serialized = json.dumps(item, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.error("[Reader] hold_monitor_queue serialization failed: %s", exc)
        return None

    await rdb.hset(HOLD_MONITOR_ITEMS, key, serialized)
    await rdb.zadd(HOLD_MONITOR_QUEUE, {key: item["hold_monitor_next_check_at"]})
    await rdb.expire(HOLD_MONITOR_ITEMS, HOLD_MONITOR_TTL_SEC)
    await rdb.expire(HOLD_MONITOR_QUEUE, HOLD_MONITOR_TTL_SEC)
    if stk_cd:
        await rdb.sadd(HOLD_MONITOR_WATCHLIST, stk_cd)
        await rdb.expire(HOLD_MONITOR_WATCHLIST, HOLD_MONITOR_TTL_SEC)
    return key


async def pop_due_hold_monitor_items(rdb, *, limit: int = 20, now: float | None = None) -> list[dict]:
    """Pop due HOLD monitor items from the sorted queue."""
    score_now = time.time() if now is None else float(now)
    keys = await rdb.zrangebyscore(HOLD_MONITOR_QUEUE, "-inf", score_now, start=0, num=limit)
    items: list[dict] = []
    for key in keys or []:
        key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        removed = await rdb.zrem(HOLD_MONITOR_QUEUE, key_text)
        if not removed:
            continue
        raw = await rdb.hget(HOLD_MONITOR_ITEMS, key_text)
        if not raw:
            continue
        try:
            item = json.loads(raw)
            item["hold_monitor_key"] = key_text
            items.append(item)
        except json.JSONDecodeError as exc:
            logger.warning("[Reader] hold monitor JSON parse failed: %s / key=%s", exc, key_text)
            await rdb.hdel(HOLD_MONITOR_ITEMS, key_text)
    return items


async def requeue_hold_monitor_item(rdb, payload: dict, *, delay_sec: float) -> str | None:
    return await push_hold_monitor_queue(rdb, payload, delay_sec=delay_sec)


async def remove_hold_monitor_item(rdb, key: str) -> None:
    if not key:
        return
    await rdb.zrem(HOLD_MONITOR_QUEUE, key)
    await rdb.hdel(HOLD_MONITOR_ITEMS, key)


async def clear_hold_monitor_queue(rdb) -> None:
    await rdb.delete(HOLD_MONITOR_QUEUE)
    await rdb.delete(HOLD_MONITOR_ITEMS)
    await rdb.delete(HOLD_MONITOR_WATCHLIST)


async def get_all_hold_monitor_items(rdb) -> list[dict]:
    """Return all currently tracked HOLD monitor items (read before a bulk clear)."""
    raw_items = await rdb.hgetall(HOLD_MONITOR_ITEMS)
    items: list[dict] = []
    for raw in (raw_items or {}).values():
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            items.append(json.loads(text))
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning("[Reader] hold monitor item JSON parse failed during bulk read: %s", exc)
    return items


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


async def get_market_index_exp_flu_rt(rdb) -> dict:
    """동시호가(08:30~09:00) 구간 예상 등락률. TTL 5분이므로 09:05 이후 자동 소멸."""
    try:
        kospi = await rdb.get("market:kospi_exp_flu_rt")
        kosdaq = await rdb.get("market:kosdaq_exp_flu_rt")
        return {
            "kospi_exp_flu_rt": float(kospi) if kospi else None,
            "kosdaq_exp_flu_rt": float(kosdaq) if kosdaq else None,
        }
    except Exception:
        return {"kospi_exp_flu_rt": None, "kosdaq_exp_flu_rt": None}


async def get_market_investor_flow(rdb) -> dict:
    """TossMarketScheduler(Java)가 캐시한 시장 전체(코스피/코스닥) 투자자별 순매수
    금액(원)을 읽는다. Kiwoom에는 없던 데이터 — analyzer.py 프롬프트 참고정보와
    strategy_meta.detect_market_regime()의 sideways 보정에 사용한다.
    값이 없으면(토스 비활성/폴링 실패) 빈 dict를 반환한다."""
    result: dict = {}
    try:
        raw_kospi = await rdb.get("market:kospi_investor_flow")
        raw_kosdaq = await rdb.get("market:kosdaq_investor_flow")
    except Exception:
        return result
    for market, raw in (("kospi", raw_kospi), ("kosdaq", raw_kosdaq)):
        if not raw:
            continue
        try:
            result[market] = json.loads(raw)
        except Exception:
            continue
    return result


async def get_market_index_series(rdb, market: str, *, minutes: int = 60) -> list[dict]:
    """market:{market}_index_ts ZSET에서 최근 N분간의 분단위 지수값/등락률 시계열을
    시간 오름차순으로 반환한다. TossMarketScheduler(Java)가 1분마다 기록한다.
    항목: {"ts": ISO8601, "value": float, "fluRt": float}. 실패/미설정 시 빈 리스트."""
    if not rdb or market not in ("kospi", "kosdaq"):
        return []
    key = f"market:{market}_index_ts"
    min_score = time.time() - minutes * 60
    try:
        raw_items = await rdb.zrangebyscore(key, min_score, "+inf")
    except Exception:
        return []
    result: list[dict] = []
    for raw in raw_items:
        try:
            result.append(json.loads(raw))
        except Exception:
            continue
    return result


async def get_market_investor_flow_series(rdb, market: str, *, minutes: int = 60) -> list[dict]:
    """market:{market}_investor_flow_ts ZSET에서 최근 N분간의 투자자별 순매수 스냅샷
    시계열(시간 오름차순)을 반환한다. investor-trading API는 1d 집계만 제공하므로
    각 항목은 "당일 누적치의 그 시점 스냅샷"이며, 연속 항목의 차이가 곧 그 구간의
    순매수 유입량이다. 실패/미설정 시 빈 리스트."""
    if not rdb or market not in ("kospi", "kosdaq"):
        return []
    key = f"market:{market}_investor_flow_ts"
    min_score = time.time() - minutes * 60
    try:
        raw_items = await rdb.zrangebyscore(key, min_score, "+inf")
    except Exception:
        return []
    result: list[dict] = []
    for raw in raw_items:
        try:
            result.append(json.loads(raw))
        except Exception:
            continue
    return result


def summarize_market_flow_trend(series: list[dict]) -> dict:
    """get_market_investor_flow_series()가 반환한 시간 오름차순 시계열에서 창구간
    추세를 요약한다. 각 스냅샷이 '당일 누적치의 그 시점 값'이므로 최신-최초 델타가
    곧 그 구간에 새로 유입/유출된 순매수 금액이다. 표본이 2개 미만이면 빈 dict —
    참고정보일 뿐 어떤 게이트에도 쓰이지 않는다(순수 함수, I/O 없음)."""
    if len(series) < 2:
        return {}
    first, last = series[0], series[-1]

    def _delta(field: str) -> float | None:
        try:
            return round(float(last.get(field) or 0) - float(first.get(field) or 0), 0)
        except (TypeError, ValueError):
            return None

    return {
        "sample_count": len(series),
        "window_start_ts": first.get("ts"),
        "window_end_ts": last.get("ts"),
        "foreigner_net_delta": _delta("foreigner_net"),
        "institution_net_delta": _delta("institution_net"),
        "latest_foreigner_net": last.get("foreigner_net"),
        "latest_institution_net": last.get("institution_net"),
    }


async def get_runtime_flag(rdb, name: str, default: bool) -> bool:
    """대시보드가 flags:{name} 에 저장한 런타임 오버라이드가 있으면 그 값을, 없으면 env 기본값을 반환."""
    if rdb is None:
        return default
    try:
        raw = await rdb.get(f"flags:{name}")
    except Exception:
        return default
    if raw is None:
        return default
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return text.strip().lower() in {"1", "true", "yes", "on"}


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
