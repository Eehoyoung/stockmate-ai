"""
WebSocket data writer for Redis with optional direct PostgreSQL persistence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from inspect import isawaitable

from db_writer import insert_tick_event, insert_vi_event, mark_event_mode

logger = logging.getLogger(__name__)

_NO_SUPPRESSION_MARKERS = ("queue", "control", "token", "heartbeat")
_NO_SUPPRESSION_EXACT = {"vi_watch_queue", "ws:heartbeat", "ws:py_heartbeat"}

_last_expire_ms: dict[str, int] = {}
_last_ltrim_ms: dict[str, int] = {}
_last_write_sig: dict[str, tuple[int, str]] = {}
_strength_samples: dict[str, deque[float]] = {}
_strength_sample_counts: dict[str, int] = {}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _redis_pipeline_enabled() -> bool:
    return _env_bool("WS_REDIS_PIPELINE_ENABLED", False)


def _expire_throttle_ms() -> int:
    return max(0, _env_int("WS_REDIS_EXPIRE_THROTTLE_MS", 0))


def _ltrim_throttle_ms() -> int:
    return max(0, _env_int("WS_REDIS_LTRIM_THROTTLE_MS", 0))


def _dedupe_enabled() -> bool:
    return _env_bool("WS_REDIS_DEDUPE_ENABLED", False)


def _dedupe_ttl_ms() -> int:
    return max(1, _env_int("WS_REDIS_DEDUPE_TTL_MS", 500))


def _strength_avg_sample_every() -> int:
    return max(1, _env_int("WS_REDIS_STRENGTH_AVG_SAMPLE_EVERY", 1))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _allows_suppression(key: str) -> bool:
    if key in _NO_SUPPRESSION_EXACT:
        return False
    lowered = key.lower()
    return not any(marker in lowered for marker in _NO_SUPPRESSION_MARKERS)


def _dedupe_signature(mapping: dict) -> str:
    stable = {k: v for k, v in mapping.items() if k not in {"updated_at_ms", "updated_at"}}
    return json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _should_skip_write(key: str, mapping: dict, now_ms: int) -> bool:
    if not _dedupe_enabled() or not _allows_suppression(key):
        return False
    signature = _dedupe_signature(mapping)
    previous = _last_write_sig.get(key)
    if not previous:
        _last_write_sig[key] = (now_ms, signature)
        return False
    previous_ms, previous_signature = previous
    if previous_signature == signature and now_ms - previous_ms <= _dedupe_ttl_ms():
        return True
    _last_write_sig[key] = (now_ms, signature)
    return False


def _should_expire(key: str, now_ms: int) -> bool:
    throttle_ms = _expire_throttle_ms()
    if throttle_ms <= 0 or not _allows_suppression(key):
        return True
    previous_ms = _last_expire_ms.get(key)
    if previous_ms is not None and now_ms - previous_ms < throttle_ms:
        return False
    _last_expire_ms[key] = now_ms
    return True


def _should_ltrim(key: str, now_ms: int) -> bool:
    throttle_ms = _ltrim_throttle_ms()
    if throttle_ms <= 0:
        return True
    previous_ms = _last_ltrim_ms.get(key)
    if previous_ms is not None and now_ms - previous_ms < throttle_ms:
        return False
    _last_ltrim_ms[key] = now_ms
    return True


async def _execute_redis_commands(rdb, commands: list[tuple[str, tuple]]):
    if not commands:
        return []
    if _redis_pipeline_enabled() and len(commands) > 1 and hasattr(rdb, "pipeline"):
        try:
            pipe = rdb.pipeline(transaction=False)
        except TypeError:
            pipe = rdb.pipeline()
        for name, args in commands:
            result = getattr(pipe, name)(*args)
            if isawaitable(result):
                await result
        result = pipe.execute()
        if isawaitable(result):
            return await result
        return result

    results = []
    for name, args in commands:
        result = getattr(rdb, name)(*args)
        if isawaitable(result):
            result = await result
        results.append(result)
    return results


async def _write_hash(rdb, key: str, mapping: dict, ttl_sec: int, now_ms: int) -> bool:
    if _should_skip_write(key, mapping, now_ms):
        return False
    commands = [("hmset", (key, mapping))]
    if _should_expire(key, now_ms):
        commands.append(("expire", (key, ttl_sec)))
    await _execute_redis_commands(rdb, commands)
    return True


def _parse_float(value) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


async def _update_strength(rdb, stk_cd: str, cntr_str: str, now_ms: str):
    sk = f"ws:strength:{stk_cd}"
    now_ms_int = int(now_ms)
    commands = [("lpush", (sk, cntr_str))]
    if _should_ltrim(sk, now_ms_int):
        commands.append(("ltrim", (sk, 0, 9)))
    if _should_expire(sk, now_ms_int):
        commands.append(("expire", (sk, 900)))
    await _execute_redis_commands(rdb, commands)

    parsed = _parse_float(cntr_str)
    samples = _strength_samples.setdefault(stk_cd, deque(maxlen=5))
    if parsed is not None:
        samples.appendleft(parsed)
    _strength_sample_counts[stk_cd] = _strength_sample_counts.get(stk_cd, 0) + 1

    sample_every = _strength_avg_sample_every()
    use_local_samples = (
        sample_every > 1
        and len(samples) > 0
        and _strength_sample_counts[stk_cd] % sample_every != 0
    )
    if use_local_samples:
        nums = list(samples)
    else:
        recent = await rdb.lrange(sk, 0, 4)
        nums = []
        for value in recent:
            parsed_value = _parse_float(value)
            if parsed_value is not None:
                nums.append(parsed_value)
        if nums:
            samples.clear()
            samples.extend(nums[:5])

    meta = {
        "updated_at_ms": now_ms,
        "latest": cntr_str,
        "sample_n": str(len(nums)),
    }
    if nums:
        meta["avg_5"] = str(round(sum(nums) / len(nums), 2))
    await _write_hash(rdb, f"ws:strength_meta:{stk_cd}", meta, 900, now_ms_int)


def _normalize_stock_code(stk_cd: str | None) -> str:
    if stk_cd is None:
        return ""
    text = str(stk_cd).strip()
    if not text:
        return ""
    base = text.split("_", 1)[0].strip()
    digits = "".join(re.findall(r"\d", base))
    if len(digits) >= 6:
        return digits[:6]
    return base


async def write_heartbeat(rdb, grp_status: dict):
    try:
        now_ts = str(time.time())
        mapping = {"updated_at": now_ts}
        mapping.update(grp_status)
        await _execute_redis_commands(rdb, [
            ("hmset", ("ws:py_heartbeat", mapping)),
            ("expire", ("ws:py_heartbeat", 90)),
        ])
        # ws:heartbeat: 모니터링 시스템이 참조하는 표준 키 (단순 타임스탬프 문자열)
        await rdb.set("ws:heartbeat", now_ts, ex=90)
    except Exception as e:
        logger.debug("[Redis] heartbeat update failed: %s", e)


async def write_tick(rdb, values: dict, stk_cd: str, pg_pool=None):
    stk_cd = _normalize_stock_code(stk_cd)
    if not stk_cd:
        return
    key = f"ws:tick:{stk_cd}"
    try:
        now_ms_int = _now_ms()
        now_ms = str(now_ms_int)
        mapping = {
            "cur_prc": values.get("10", ""),
            "pred_pre": values.get("11", ""),
            "flu_rt": values.get("12", ""),
            "acc_trde_qty": values.get("13", ""),
            "acc_trde_prica": values.get("14", ""),
            "cntr_tm": values.get("20", ""),
            "cntr_str": values.get("228", ""),
            "updated_at_ms": now_ms,
        }
        await _write_hash(rdb, key, mapping, 600, now_ms_int)

        cntr_str = str(values.get("228", "")).strip()
        if cntr_str:
            await _update_strength(rdb, stk_cd, cntr_str, now_ms)

        if pg_pool:
            await insert_tick_event(pg_pool, "0B", stk_cd, values)
            await mark_event_mode(rdb)
    except Exception as e:
        logger.warning("[Redis] tick write failed [%s]: %s", stk_cd, e)


async def write_expected(rdb, values: dict, stk_cd: str, pg_pool=None):
    stk_cd = _normalize_stock_code(stk_cd)
    if not stk_cd:
        return
    key = f"ws:expected:{stk_cd}"
    try:
        now_ms_int = _now_ms()
        now_ms = str(now_ms_int)
        exp_cntr_pric = values.get("10", "")
        exp_pred_pre = values.get("11", "")
        exp_flu_rt = values.get("12", "")
        exp_cntr_qty = values.get("15", "")
        exp_cntr_tm = values.get("20", "")

        mapping = {
            "exp_cntr_pric": exp_cntr_pric,
            "exp_pred_pre": exp_pred_pre,
            "exp_flu_rt": exp_flu_rt,
            "exp_cntr_qty": exp_cntr_qty,
            "exp_cntr_tm": exp_cntr_tm,
            "updated_at_ms": now_ms,
        }

        if exp_cntr_pric and exp_flu_rt:
            try:
                pric = float(str(exp_cntr_pric).replace(",", "").replace("+", "").replace("-", ""))
                flu = float(str(exp_flu_rt).replace(",", "").replace("+", ""))
                if pric > 0 and flu != -100:
                    mapping["pred_pre_pric"] = str(round(pric / (1 + flu / 100)))
            except Exception:
                pass

        await _write_hash(rdb, key, mapping, 1800, now_ms_int)
        if pg_pool:
            await insert_tick_event(pg_pool, "0H", stk_cd, values)
            await mark_event_mode(rdb)
    except Exception as e:
        logger.warning("[Redis] expected write failed [%s]: %s", stk_cd, e)


async def write_hoga(rdb, values: dict, stk_cd: str, pg_pool=None):
    stk_cd = _normalize_stock_code(stk_cd)
    if not stk_cd:
        return
    key = f"ws:hoga:{stk_cd}"
    try:
        now_ms_int = _now_ms()
        now_ms = str(now_ms_int)
        mapping = {
            "total_buy_bid_req": values.get("125", ""),
            "total_sel_bid_req": values.get("121", ""),
            "buy_bid_pric_1": values.get("51", ""),
            "sel_bid_pric_1": values.get("41", ""),
            "buy_bid_req_1": values.get("71", ""),
            "sel_bid_req_1": values.get("61", ""),
            "bid_req_base_tm": values.get("21", ""),
            "updated_at_ms": now_ms,
        }
        await _write_hash(rdb, key, mapping, 120, now_ms_int)
        if pg_pool:
            await insert_tick_event(pg_pool, "0D", stk_cd, values)
            await mark_event_mode(rdb)
    except Exception as e:
        logger.warning("[Redis] hoga write failed [%s]: %s", stk_cd, e)


async def write_vi(rdb, values: dict, stk_cd: str, pg_pool=None):
    real_stk_cd = _normalize_stock_code(values.get("9001", stk_cd))
    if not real_stk_cd:
        return

    vi_stat = values.get("9068", "")
    vi_price = values.get("1221", "0")
    vi_type = values.get("1225", "")

    key = f"vi:{real_stk_cd}"
    try:
        now_ms_int = _now_ms()
        now_ms = str(now_ms_int)
        mapping = {
            "vi_price": vi_price,
            "vi_type": vi_type,
            "status": "active" if vi_stat == "1" else "released",
            "mrkt_cls": values.get("9008", ""),
            "vi_volume": values.get("15", values.get("13", "")),
            "ref_price": values.get("11", ""),
            "upper_limit": values.get("305", ""),
            "lower_limit": values.get("306", ""),
            "updated_at_ms": now_ms,
        }
        if vi_stat == "2":
            mapping["released_at_ms"] = now_ms
        await _write_hash(rdb, key, mapping, 3600, now_ms_int)

        if pg_pool:
            await insert_vi_event(pg_pool, real_stk_cd, values)
            await mark_event_mode(rdb)

        if vi_stat == "2":
            try:
                vi_price_f = float(str(vi_price).replace(",", "").replace("+", "").replace("-", "") or "0")
            except ValueError:
                vi_price_f = 0.0
            is_dynamic = "동적" in str(vi_type)
            watch_item = json.dumps({
                "stk_cd": real_stk_cd,
                "stk_nm": values.get("302", ""),
                "vi_price": vi_price_f,
                "watch_until": int(time.time() * 1000) + 600_000,
                "is_dynamic": is_dynamic,
            }, ensure_ascii=False)
            await _execute_redis_commands(rdb, [
                ("lpush", ("vi_watch_queue", watch_item)),
                ("expire", ("vi_watch_queue", 7200)),
            ])
            logger.info("[VI] queued release watch [%s] price=%s dynamic=%s", real_stk_cd, vi_price_f, is_dynamic)
    except Exception as e:
        logger.warning("[Redis] VI write failed [%s]: %s", real_stk_cd, e)
