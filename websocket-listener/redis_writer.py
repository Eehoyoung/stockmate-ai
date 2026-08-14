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
from datetime import time as dtime
from inspect import isawaitable

from db_writer import insert_tick_event, insert_vi_event, mark_event_mode
from market_session import is_market_open_day, now_kst

logger = logging.getLogger(__name__)

_NO_SUPPRESSION_MARKERS = ("queue", "control", "token", "heartbeat")
_NO_SUPPRESSION_EXACT = {"vi_watch_queue", "ws:heartbeat", "ws:py_heartbeat"}
_FUND_PRODUCT_NAME_MARKERS = (
    "ETF", "ETN", "레버리지", "인버스", "2X", "곱버스", "선물", "합성", "액티브",
)


def _is_etf_or_etn_name(value) -> bool:
    normalized = str(value or "").upper()
    return any(marker in normalized for marker in _FUND_PRODUCT_NAME_MARKERS)

_last_expire_ms: dict[str, int] = {}
_last_ltrim_ms: dict[str, int] = {}
_last_write_sig: dict[str, tuple[int, str]] = {}
_strength_samples: dict[str, deque[float]] = {}
_strength_sample_counts: dict[str, int] = {}
_VI_RELEASE_QUEUE_DEDUP_SEC = 660  # release watch window (10m) plus buffer
_S2_WINDOW_START = dtime(9, 0)
_S2_WINDOW_END = dtime(14, 50)


def _is_s2_window_open(date_time=None) -> bool:
    target = date_time or now_kst()
    return (
        is_market_open_day(target)
        and _S2_WINDOW_START <= target.time() < _S2_WINDOW_END
    )

# 5분 평균 거래량 산출용 누적 스냅샷 (S2 VI 거래량 배수 계산에 사용)
_5MIN_MS = 5 * 60 * 1000
_acc_qty_snapshots: dict[str, deque] = {}


def _update_prev_5m_avg_qty(stk_cd: str, acc_qty: float, now_ms: int) -> int | None:
    """acc_trde_qty 누적값으로 직전 5분 평균 거래량을 추정한다.

    최근 5분 이상 된 스냅샷과의 누적 차분을 5분 단위로 정규화.
    데이터 부족(5분 이상 스냅샷 없음) 시 None 반환.
    """
    if stk_cd not in _acc_qty_snapshots:
        _acc_qty_snapshots[stk_cd] = deque(maxlen=120)
    history = _acc_qty_snapshots[stk_cd]
    history.append((now_ms, acc_qty))

    cutoff = now_ms - _5MIN_MS
    oldest = None
    for ts, qty in history:
        if ts <= cutoff:
            oldest = (ts, qty)
        else:
            break

    if oldest is None:
        return None
    elapsed = now_ms - oldest[0]
    if elapsed <= 0:
        return None
    vol_diff = max(0.0, acc_qty - oldest[1])
    avg_5m = vol_diff * (_5MIN_MS / elapsed)
    return max(1, int(avg_5m))


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
        # Event-mode is a producer capability, not evidence that a trade happened
        # recently. Keep the marker alive with the producer heartbeat so quiet
        # after-market periods are not reported as an unknown DB writer mode.
        await mark_event_mode(rdb)
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
        # S2 VI 거래량 배수 산출을 위한 5분 평균 거래량 추적
        try:
            acc_qty_raw = values.get("13", "")
            if acc_qty_raw:
                acc_qty = float(str(acc_qty_raw).replace(",", "").replace("+", ""))
                if acc_qty > 0:
                    avg5 = _update_prev_5m_avg_qty(stk_cd, acc_qty, now_ms_int)
                    if avg5 is not None:
                        mapping["prev_5m_avg_qty"] = str(avg5)
        except (TypeError, ValueError):
            pass
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
            "source": "ws_0h",
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


async def write_program(rdb, values: dict, stk_cd: str, pg_pool=None):
    stk_cd = _normalize_stock_code(stk_cd)
    if not stk_cd:
        return
    key = f"ws:program:{stk_cd}"
    history_key = f"ws:program_history:{stk_cd}"
    try:
        now_ms_int = _now_ms()
        now_ms = str(now_ms_int)
        mapping = {
            "cur_prc": values.get("10", ""),
            "pred_pre_sig": values.get("25", ""),
            "pred_pre": values.get("11", ""),
            "flu_rt": values.get("12", ""),
            "acc_trde_qty": values.get("13", ""),
            "cntr_tm": values.get("20", ""),
            "program_sell_qty": values.get("202", ""),
            "program_sell_amt": values.get("204", ""),
            "program_buy_qty": values.get("206", ""),
            "program_buy_amt": values.get("208", ""),
            "program_net_buy_qty": values.get("210", ""),
            "program_net_buy_qty_chg": values.get("211", ""),
            "program_net_buy_amt": values.get("212", ""),
            "program_net_buy_amt_chg": values.get("213", ""),
            "source": "ws_0w",
            "updated_at_ms": now_ms,
        }
        await _write_hash(rdb, key, mapping, 600, now_ms_int)

        history_item = json.dumps(mapping, ensure_ascii=False, sort_keys=True)
        commands = [("lpush", (history_key, history_item))]
        if _should_ltrim(history_key, now_ms_int):
            commands.append(("ltrim", (history_key, 0, 19)))
        if _should_expire(history_key, now_ms_int):
            commands.append(("expire", (history_key, 900)))
        await _execute_redis_commands(rdb, commands)
    except Exception as e:
        logger.warning("[Redis] program write failed [%s]: %s", stk_cd, e)


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
            stk_nm = values.get("302", "")
            if _is_etf_or_etn_name(stk_nm):
                logger.info(
                    "[VI] ETF/ETN release watch suppressed [%s] name=%s",
                    real_stk_cd,
                    stk_nm,
                )
                return
            if not _is_s2_window_open():
                logger.info(
                    "[VI] release watch suppressed outside S2 window [%s]",
                    real_stk_cd,
                )
                return
            try:
                vi_price_f = float(str(vi_price).replace(",", "").replace("+", "").replace("-", "") or "0")
            except ValueError:
                vi_price_f = 0.0
            release_dedup_key = f"vi:release:queue_dedup:{real_stk_cd}:{vi_price_f}"
            if not await rdb.set(
                release_dedup_key,
                now_ms,
                nx=True,
                ex=_VI_RELEASE_QUEUE_DEDUP_SEC,
            ):
                logger.debug(
                    "[VI] duplicate release watch suppressed [%s] price=%s",
                    real_stk_cd,
                    vi_price_f,
                )
                return
            is_dynamic = "동적" in str(vi_type)
            watch_item = json.dumps({
                "stk_cd": real_stk_cd,
                "stk_nm": stk_nm,
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
