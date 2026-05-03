from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from http_utils import (
    fetch_hoga,
    fetch_cntr_strength,
    fetch_stk_nm,
    kiwoom_client,
    validate_kiwoom_response,
)
from indicator_atr import get_atr_minute
from ma_utils import _safe_price, fetch_daily_candles
from redis_reader import get_avg_cntr_strength
from tp_sl_engine import calc_tp_sl

_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


from utils import safe_float as clean_num


async def get_expected_execution(rdb, stk_cd: str) -> dict:
    """Read pre-open expected execution data written from WS 0H."""
    try:
        return await rdb.hgetall(f"ws:expected:{stk_cd}")
    except Exception:
        return {}


def _snapshot_to_candidate_info(snapshot: dict, rank: int | None = None) -> dict:
    buy_req = clean_num(snapshot.get("buy_req", 0))
    sel_req = clean_num(snapshot.get("sel_req", 0))
    pre_bid_ratio = buy_req / sel_req if sel_req > 0 else (999.0 if buy_req > 0 else 0.0)
    return {
        "rank": rank if rank is not None else int(clean_num(snapshot.get("ka10029_rank", 999)) or 999),
        "gap_rt": clean_num(snapshot.get("exp_flu_rt", snapshot.get("flu_rt", 0))),
        "exp_prc": clean_num(snapshot.get("exp_cntr_pric", 0)),
        "exp_qty": clean_num(snapshot.get("exp_cntr_qty", 0)),
        "buy_req": buy_req,
        "sel_req": sel_req,
        "pre_bid_ratio": pre_bid_ratio,
    }


async def fetch_gap_candidates(token: str) -> list[str]:
    """Fetch S1 fallback candidates from ka10029 when Redis candidate pools are empty."""
    return list((await fetch_gap_snapshots(token)).keys())


async def fetch_gap_snapshots(token: str) -> dict[str, dict]:
    """Fetch ka10029 snapshots keyed by stock code for S1 REST fallback."""
    result: list[str] = []
    snapshots: dict[str, dict] = {}
    next_key = ""

    try:
        async with kiwoom_client() as client:
            while True:
                headers = {
                    "api-id": "ka10029",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                }
                if next_key:
                    headers["cont-yn"] = "Y"
                    headers["next-key"] = next_key

                resp = await client.post(
                    f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                    headers=headers,
                    json={
                        "mrkt_tp": "000",
                        "sort_tp": "1",
                        "trde_qty_cnd": "10",
                        "stk_cnd": "1",
                        "crd_cnd": "0",
                        "pric_cnd": "8",
                        "stex_tp": "3",
                    },
                )
                data = resp.json()
                if not validate_kiwoom_response(data, "ka10029", logger):
                    break

                for item in data.get("exp_cntr_flu_rt_upper", []):
                    try:
                        flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
                    except ValueError:
                        continue
                    if 3.0 <= flu_rt <= 15.0:
                        stk_cd = item.get("stk_cd")
                        if stk_cd:
                            result.append(stk_cd)
                            snapshot = {
                                "exp_cntr_pric": str(item.get("exp_cntr_pric", "")).strip(),
                                "exp_flu_rt": str(item.get("flu_rt", "")).strip(),
                                "exp_cntr_qty": str(item.get("exp_cntr_qty", "")).strip(),
                                "base_pric": str(item.get("base_pric", "")).strip(),
                                "pred_pre": str(item.get("pred_pre", "")).strip(),
                                "pred_pre_sig": str(item.get("pred_pre_sig", "")).strip(),
                                "sel_req": str(item.get("sel_req", "")).strip(),
                                "sel_bid": str(item.get("sel_bid", "")).strip(),
                                "buy_bid": str(item.get("buy_bid", "")).strip(),
                                "buy_req": str(item.get("buy_req", "")).strip(),
                                "ka10029_rank": str(len(result)),
                            }
                            try:
                                exp_price = float(snapshot["exp_cntr_pric"].replace(",", "").replace("+", "").replace("-", ""))
                                if exp_price > 0 and flu_rt != -100:
                                    snapshot["pred_pre_pric"] = str(round(exp_price / (1 + flu_rt / 100)))
                            except Exception:
                                pass
                            snapshots[stk_cd] = snapshot

                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "").strip()
                if cont_yn != "Y" or not next_key:
                    break
    except Exception as exc:
        logger.warning("[S1] ka10029 fallback failed: %s", exc)
        return {}

    if not snapshots:
        return {}
    return {stk_cd: snapshots[stk_cd] for stk_cd in dict.fromkeys(result) if stk_cd in snapshots}


async def _get_strength_value(token: str, stk_cd: str, rdb=None) -> tuple[float, str]:
    """Prefer WS strength cache; use REST ka10046 only when the cache is empty."""
    if rdb:
        try:
            strength = await get_avg_cntr_strength(rdb, stk_cd, count=5)
            if strength > 100.0:
                return strength, "redis"
        except Exception as exc:
            logger.debug("[S1] ws:strength read failed [%s]: %s", stk_cd, exc)

    await asyncio.sleep(_API_INTERVAL)
    return await fetch_cntr_strength(token, stk_cd), "rest"


async def fetch_gap_rank(token: str, market: str) -> dict:
    """Fetch ka10029 gap-ranked candidates for the S7 fallback path."""
    result = {}
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka10029",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "sort_tp": "1",
                    "trde_qty_cnd": "0",
                    "stk_cnd": "1",
                    "crd_cnd": "0",
                    "pric_cnd": "0",
                    "stex_tp": "3",
                },
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10029", logger):
                break

            items = data.get("exp_cntr_flu_rt_upper", [])
            for item in items:
                stk_cd = item.get("stk_cd")
                flu_rt = clean_num(item.get("flu_rt"))
                if stk_cd and 2.0 <= flu_rt <= 10.0:
                    result[stk_cd] = {
                        "rank": len(result) + 1,
                        "gap_rt": flu_rt,
                        "exp_prc": clean_num(item.get("exp_cntr_pric")),
                        "exp_qty": clean_num(item.get("exp_cntr_qty")),
                        "buy_req": clean_num(item.get("buy_req")),
                        "sel_req": clean_num(item.get("sel_req")),
                    }

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()
            if cont_yn != "Y" or not next_key or len(result) >= 150:
                break

    return result


async def fetch_credit_filter(token: str, market: str = "000", rdb=None) -> set:
    """Fetch/cache high-credit stocks from ka10033 for S7 filtering."""
    cache_key = f"cache:high_credit:{market}"
    cache_ttl = 1800

    if rdb:
        try:
            cached = await rdb.smembers(cache_key)
            if cached:
                logger.debug("[S7] using cached high-credit set (%d, market=%s)", len(cached), market)
                return set(cached)
        except Exception as exc:
            logger.debug("[S7] cache read failed; fallback to ka10033: %s", exc)

    high_credit_set = set()
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka10033",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "trde_qty_tp": "0",
                    "stk_cnd": "1",
                    "updown_incls": "1",
                    "crd_cnd": "0",
                    "stex_tp": "3",
                },
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10033", logger):
                break

            for item in data.get("crd_rt_upper", []):
                if clean_num(item.get("crd_rt")) >= 8.0:
                    stk_cd = item.get("stk_cd")
                    if stk_cd:
                        high_credit_set.add(stk_cd)

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()
            if cont_yn != "Y" or not next_key:
                break

    if rdb and high_credit_set:
        try:
            pipe = rdb.pipeline()
            pipe.delete(cache_key)
            pipe.sadd(cache_key, *high_credit_set)
            pipe.expire(cache_key, cache_ttl)
            await pipe.execute()
        except Exception as exc:
            logger.debug("[S7] cache write failed: %s", exc)

    return high_credit_set


async def scan_gap_opening(token: str, candidates: list, rdb=None) -> list[dict]:
    """Build S1 gap-open signals from expected execution and strength data."""
    effective = list(dict.fromkeys(candidates))
    fallback_used = False
    rest_snapshots: dict[str, dict] | None = None
    stats = {
        "candidate_count": len(effective),
        "no_expected": 0,
        "bad_expected_parse": 0,
        "gap_below_threshold": 0,
        "strength_below_threshold": 0,
        "strength_from_redis": 0,
        "strength_from_rest": 0,
    }

    if not effective:
        rest_snapshots = await fetch_gap_snapshots(token)
        effective = list(rest_snapshots.keys())
        fallback_used = bool(effective)
        stats["candidate_count"] = len(effective)
        if fallback_used:
            logger.warning("[S1] candidate pool empty; using ka10029 fallback (%d)", len(effective))
        else:
            logger.warning("[S1] candidate pool empty and ka10029 fallback returned nothing")

    results: list[dict] = []

    for stk_cd in effective:
        exp = await get_expected_execution(rdb, stk_cd) if rdb else {}
        if not exp:
            if rest_snapshots is None:
                rest_snapshots = await fetch_gap_snapshots(token)
            exp = rest_snapshots.get(stk_cd, {})
        if not exp:
            stats["no_expected"] += 1
            continue

        try:
            raw_exp_price = exp.get("exp_cntr_pric") or exp.get("10", "0")
            exp_price = abs(int(str(raw_exp_price).replace("+", "").replace("-", "").replace(",", "")))

            raw_gap_pct = exp.get("exp_flu_rt") or exp.get("12", "0")
            gap_pct = float(str(raw_gap_pct).replace("+", "").replace(",", ""))
        except ValueError:
            stats["bad_expected_parse"] += 1
            continue

        if exp_price <= 0 or gap_pct < 2.5:
            stats["gap_below_threshold"] += 1
            continue

        strength, strength_source = await _get_strength_value(token, stk_cd, rdb=rdb)
        stats[f"strength_from_{strength_source}"] += 1
        if strength < 120.0:
            stats["strength_below_threshold"] += 1
            continue

        bid_ratio = await fetch_hoga(token, stk_cd, rdb=rdb)

        # ── 갭 구간 분류 ──
        # 8~12%: 강한 갭, 실행 비용 증가로 감점
        # 12~15%: 과열 갭, shadow 추적 전용 (자동 진입 금지)
        gap_overheat = gap_pct >= 12.0
        gap_strong   = 8.0 <= gap_pct < 12.0

        # ── 장초반 time gate ──
        # 09:00~09:03: 스프레드/호가 불안정 구간 — AUTO_SMALL만 허용
        now_kst = datetime.now(_KST)
        early_open = (now_kst.hour == 9 and now_kst.minute < 3)

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        score = (gap_pct * 0.5) + ((strength - 100) * 0.5)
        score -= (15 if gap_overheat else 0)  # 과열 갭 큰 감점
        score -= (8  if gap_strong   else 0)  # 강한 갭 감점
        score -= (10 if early_open   else 0)  # 장초반 호가 불안정 감점

        atr_val = None
        prev_close = None
        try:
            await asyncio.sleep(_API_INTERVAL)
            atr_result = await get_atr_minute(token, stk_cd, tic_scope="5", period=7)
            atr_val = atr_result.atr
        except Exception:
            pass
        try:
            daily = await fetch_daily_candles(token, stk_cd, target_count=2)
            if len(daily) >= 2:
                prev_close = _safe_price(daily[1].get("cur_prc"))
        except Exception:
            pass

        tp_sl = calc_tp_sl(
            "S1_GAP_OPEN",
            exp_price,
            [],
            [],
            [],
            stk_cd=stk_cd,
            atr=atr_val,
            prev_close=prev_close,
        )

        # signal_mode: 과열 갭 → shadow, 장초반 → auto_small, 정상 → normal
        if gap_overheat:
            signal_mode = "SHADOW"
        elif early_open:
            signal_mode = "AUTO_SMALL"
        else:
            signal_mode = "NORMAL"

        results.append(
            {
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "cur_prc": exp_price,
                "strategy": "S1_GAP_OPEN",
                "gap_pct": round(gap_pct, 2),
                "gap_zone": ("overheat" if gap_overheat else "strong" if gap_strong else "normal"),
                "signal_mode": signal_mode,
                "early_open": early_open,
                "cntr_strength": round(strength, 1),
                "bid_ratio": round(bid_ratio, 2) if bid_ratio is not None else None,
                "score": round(score, 2),
                "entry_type": "시초가_시장가",
                **tp_sl.to_signal_fields(),
            }
        )

    final_results = sorted(results, key=lambda x: x["score"], reverse=True)[:5]
    logger.info(
        "[S1] scan complete candidates=%d fallback=%s selected=%d no_expected=%d parse_fail=%d gap_below=%d strength_below=%d strength(redis/rest)=%d/%d",
        stats["candidate_count"],
        fallback_used,
        len(final_results),
        stats["no_expected"],
        stats["bad_expected_parse"],
        stats["gap_below_threshold"],
        stats["strength_below_threshold"],
        stats["strength_from_redis"],
        stats["strength_from_rest"],
    )
    return final_results


