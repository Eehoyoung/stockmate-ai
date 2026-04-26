"""
WebSocket data writer for Redis with optional direct PostgreSQL persistence.
"""

from __future__ import annotations

import json
import logging
import re
import time

from db_writer import insert_tick_event, insert_vi_event, mark_event_mode

logger = logging.getLogger(__name__)


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
        mapping = {"updated_at": str(time.time())}
        mapping.update(grp_status)
        await rdb.hmset("ws:py_heartbeat", mapping)
        await rdb.expire("ws:py_heartbeat", 90)
    except Exception as e:
        logger.debug("[Redis] heartbeat update failed: %s", e)


async def write_tick(rdb, values: dict, stk_cd: str, pg_pool=None):
    stk_cd = _normalize_stock_code(stk_cd)
    if not stk_cd:
        return
    key = f"ws:tick:{stk_cd}"
    try:
        now_ms = str(int(time.time() * 1000))
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
        await rdb.hmset(key, mapping)
        await rdb.expire(key, 600)

        cntr_str = str(values.get("228", "")).strip()
        if cntr_str:
            sk = f"ws:strength:{stk_cd}"
            await rdb.lpush(sk, cntr_str)
            await rdb.ltrim(sk, 0, 9)
            await rdb.expire(sk, 900)
            recent = await rdb.lrange(sk, 0, 4)
            nums = []
            for value in recent:
                try:
                    nums.append(float(str(value).replace(",", "").replace("+", "")))
                except (TypeError, ValueError):
                    pass
            meta = {
                "updated_at_ms": now_ms,
                "latest": cntr_str,
                "sample_n": str(len(nums)),
            }
            if nums:
                meta["avg_5"] = str(round(sum(nums) / len(nums), 2))
            await rdb.hmset(f"ws:strength_meta:{stk_cd}", meta)
            await rdb.expire(f"ws:strength_meta:{stk_cd}", 900)

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
        now_ms = str(int(time.time() * 1000))
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

        await rdb.hmset(key, mapping)
        await rdb.expire(key, 1800)
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
        now_ms = str(int(time.time() * 1000))
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
        await rdb.hmset(key, mapping)
        await rdb.expire(key, 120)
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
        now_ms = str(int(time.time() * 1000))
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
        await rdb.hmset(key, mapping)
        await rdb.expire(key, 3600)

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
            await rdb.lpush("vi_watch_queue", watch_item)
            await rdb.expire("vi_watch_queue", 7200)
            logger.info("[VI] queued release watch [%s] price=%s dynamic=%s", real_stk_cd, vi_price_f, is_dynamic)
    except Exception as e:
        logger.warning("[Redis] VI write failed [%s]: %s", real_stk_cd, e)
