"""
PostgreSQL direct writer for websocket events.

When enabled, websocket-listener persists every 0B/0D/0H/1h event directly so
ws_tick_data and vi_events become event-complete instead of minute snapshots.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_TICK_TABLE = "ws_tick_data_partitioned"

_TICK_MIN_INTERVAL_MS = {
    "0B": int(os.getenv("WS_DB_0B_MIN_INTERVAL_MS", "0")),
    "0D": int(os.getenv("WS_DB_0D_MIN_INTERVAL_MS", "0")),
    "0H": int(os.getenv("WS_DB_0H_MIN_INTERVAL_MS", "0")),
}
_last_tick_insert_ms: dict[tuple[str, str], int] = {}


def _safe_relation_name(raw: str | None) -> str:
    name = (raw or _DEFAULT_TICK_TABLE).strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", name):
        return name
    logger.warning("[DB] invalid WS_TICK_DATA_TABLE=%r; using %s", raw, _DEFAULT_TICK_TABLE)
    return _DEFAULT_TICK_TABLE


_WS_TICK_DATA_TABLE = _safe_relation_name(os.getenv("WS_TICK_DATA_TABLE"))


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


def _f(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        text = str(raw).replace(",", "").replace("+", "").strip()
        if not text:
            return None
        return abs(float(text))
    except Exception:
        return None


def _i(raw) -> Optional[int]:
    if raw is None:
        return None
    try:
        text = str(raw).replace(",", "").replace("+", "").strip()
        if not text:
            return None
        return abs(int(float(text)))
    except Exception:
        return None


def _should_persist_tick(tick_type: str, stk_cd: str) -> bool:
    min_interval = _TICK_MIN_INTERVAL_MS.get(tick_type, 0)
    if min_interval <= 0:
        return True
    now_ms = int(time.monotonic() * 1000)
    key = (tick_type, stk_cd)
    last_ms = _last_tick_insert_ms.get(key)
    if last_ms is not None and now_ms - last_ms < min_interval:
        return False
    _last_tick_insert_ms[key] = now_ms
    return True


def _must_persist_trade(values: dict) -> bool:
    return _f(values.get("10")) is not None or _i(values.get("13")) is not None or _f(values.get("228")) is not None


def _must_persist_expected(values: dict) -> bool:
    return _f(values.get("10")) is not None or _i(values.get("15")) is not None


async def mark_event_mode(rdb) -> None:
    try:
        await rdb.set("ws:db_writer:event_mode", "1", ex=120)
    except Exception:
        logger.debug("[DB] event mode marker update failed")


async def insert_tick_event(pg_pool, tick_type: str, stk_cd: str, values: dict) -> None:
    stk_cd = _normalize_stock_code(stk_cd)
    if not pg_pool or not stk_cd:
        return
    if not _should_persist_tick(tick_type, stk_cd):
        return
    try:
        if tick_type == "0B":
            await pg_pool.execute(
                f"""
                INSERT INTO {_WS_TICK_DATA_TABLE} (
                    stk_cd, cur_prc, pred_pre, flu_rt, acc_trde_qty,
                    acc_trde_prica, cntr_str, tick_type, must_persist, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
                """,
                stk_cd,
                _f(values.get("10")),
                _f(values.get("11")),
                _f(values.get("12")),
                _i(values.get("13")),
                _i(values.get("14")),
                _f(values.get("228")),
                "0B",
                _must_persist_trade(values),
            )
            return

        if tick_type == "0D":
            total_bid = _i(values.get("125"))
            total_ask = _i(values.get("121"))
            ratio = (float(total_bid) / float(total_ask)) if total_bid is not None and total_ask not in (None, 0) else None
            await pg_pool.execute(
                f"""
                INSERT INTO {_WS_TICK_DATA_TABLE} (
                    stk_cd, total_bid_qty, total_ask_qty, bid_ask_ratio, tick_type, created_at
                ) VALUES ($1,$2,$3,$4,$5,NOW())
                """,
                stk_cd,
                total_bid,
                total_ask,
                ratio,
                "0D",
            )
            return

        if tick_type == "0H":
            await pg_pool.execute(
                f"""
                INSERT INTO {_WS_TICK_DATA_TABLE} (
                    stk_cd, cur_prc, pred_pre, flu_rt, acc_trde_qty, tick_type, must_persist, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
                """,
                stk_cd,
                _f(values.get("10")),
                _f(values.get("11")),
                _f(values.get("12")),
                _i(values.get("15")),
                "0H",
                _must_persist_expected(values),
            )
    except Exception as e:
        logger.warning(
            "[DB] %s insert failed [%s %s] %s: %r",
            _WS_TICK_DATA_TABLE,
            tick_type,
            stk_cd,
            type(e).__name__,
            e,
        )


async def insert_vi_event(pg_pool, stk_cd: str, values: dict) -> None:
    stk_cd = _normalize_stock_code(stk_cd)
    if not pg_pool or not stk_cd:
        return
    try:
        vi_status = str(values.get("9068", "")).strip()
        vi_type = _normalize_vi_type(values.get("1225", ""))
        released_at = "NOW()" if vi_status == "2" else None
        if released_at:
            await pg_pool.execute(
                """
                INSERT INTO vi_events (
                    stk_cd, stk_nm, vi_type, vi_status, vi_price, acc_volume,
                    ref_price, upper_limit, lower_limit, market_type, created_at, released_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),NOW())
                """,
                stk_cd,
                (values.get("302") or "")[:40] or None,
                vi_type,
                vi_status[:2] or None,
                _f(values.get("1221")),
                _i(values.get("15") or values.get("13")),
                _f(values.get("11")),
                _f(values.get("305")),
                _f(values.get("306")),
                str(values.get("9008", "")).strip()[:10] or None,
            )
        else:
            await pg_pool.execute(
                """
                INSERT INTO vi_events (
                    stk_cd, stk_nm, vi_type, vi_status, vi_price, acc_volume,
                    ref_price, upper_limit, lower_limit, market_type, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
                """,
                stk_cd,
                (values.get("302") or "")[:40] or None,
                vi_type,
                vi_status[:2] or None,
                _f(values.get("1221")),
                _i(values.get("15") or values.get("13")),
                _f(values.get("11")),
                _f(values.get("305")),
                _f(values.get("306")),
                str(values.get("9008", "")).strip()[:10] or None,
            )
    except Exception as e:
        logger.warning("[DB] vi_event insert failed [%s]: %s", stk_cd, e)


def _normalize_vi_type(raw) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value in {"1", "2", "3"}:
        return value
    dynamic = "동적" in value
    static = "정적" in value
    if dynamic and static:
        return "3"
    if dynamic:
        return "2"
    if static:
        return "1"
    return value[:2] or None
