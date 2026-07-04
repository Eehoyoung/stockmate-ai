from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from http_utils import (
    apply_volume_profile_rr,
    fetch_hoga,
    fetch_cntr_strength,
    fetch_volume_profile,
    fetch_stk_nm,
    kiwoom_client,
    validate_kiwoom_response,
)
from indicator_atr import get_atr_minute
from ma_utils import _safe_price, fetch_daily_candles
from redis_reader import get_avg_cntr_strength
from tp_sl_engine import calc_tp_sl
from execution_quality import assess_execution_quality, should_hard_reject

_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


from utils import safe_float as clean_num


def _expected_age_ms(exp: dict) -> int | None:
    updated_at = clean_num(exp.get("updated_at_ms"), 0)
    if updated_at <= 0:
        return None
    return max(0, int(datetime.now(_KST).timestamp() * 1000) - int(updated_at))


def _expected_bid_decay_pct(exp: dict) -> float | None:
    prev_buy_req = clean_num(exp.get("prev_buy_req"), 0)
    buy_req = clean_num(exp.get("buy_req"), 0)
    if prev_buy_req <= 0 or buy_req < 0:
        return None
    return round((buy_req - prev_buy_req) / prev_buy_req * 100.0, 2)


def _s1_entry_policy(
    *,
    gap_pct: float,
    strength: float,
    bid_ratio: float | None,
    rr_ratio: float | None,
    early_open: bool,
    expected_age_ms: int | None,
    expected_bid_decay_pct: float | None,
    post_open_extension_pct: float | None,
    execution_quality: str,
    first_low_break: bool,
    vwap_position: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    policy = "ENTER_CANDIDATE"
    bid = bid_ratio if bid_ratio is not None else 0.0
    rr = rr_ratio if rr_ratio is not None else 0.0

    def hold(reason: str) -> None:
        nonlocal policy
        if policy != "CANCEL":
            policy = "HOLD_RECHECK"
        reasons.append(reason)

    def cancel(reason: str) -> None:
        nonlocal policy
        policy = "CANCEL"
        reasons.append(reason)

    if expected_age_ms is None:
        hold("expected freshness missing")
    elif expected_age_ms > 15_000:
        hold(f"expected stale {expected_age_ms}ms")

    if expected_bid_decay_pct is not None:
        if expected_bid_decay_pct <= -50.0:
            cancel(f"expected bid decayed {expected_bid_decay_pct:.1f}%")
        elif expected_bid_decay_pct <= -30.0:
            hold(f"expected bid weakened {expected_bid_decay_pct:.1f}%")

    if first_low_break and vwap_position == "BELOW_VWAP":
        cancel("first low break below VWAP")
    elif first_low_break:
        hold("first low break")
    elif vwap_position == "BELOW_VWAP":
        hold("below VWAP")

    if post_open_extension_pct is not None:
        if gap_pct >= 8.0 and post_open_extension_pct > 1.0:
            hold(f"gap>=8 and extension {post_open_extension_pct:.2f}%")
        elif post_open_extension_pct > 1.5:
            hold(f"post-open extension {post_open_extension_pct:.2f}%")

    if rr_ratio is not None:
        if rr < 0.8:
            cancel(f"R:R {rr:.2f} below 0.80")
        elif rr < 1.0:
            hold(f"R:R {rr:.2f} below 1.00")

    if gap_pct < 3.0 and not (strength >= 150.0 and bid >= 1.8 and rr >= 1.2):
        hold("sub-3pct gap needs stronger strength/bid/RR")
    elif 5.0 <= gap_pct < 8.0 and (strength < 130.0 or bid < 1.3 or rr < 1.0):
        hold("5-8pct gap needs strength>=130 bid>=1.3 RR>=1.0")
    elif 8.0 <= gap_pct < 12.0 and (strength < 150.0 or bid < 1.5 or rr < 1.2):
        hold("8-12pct gap needs strength>=150 bid>=1.5 RR>=1.2")
    elif gap_pct >= 12.0:
        hold("gap>=12 overheat")

    if early_open and not (strength >= 160.0 and bid >= 1.5):
        hold("early open requires strength>=160 and bid>=1.5")

    if execution_quality == "REJECT":
        hold("execution quality reject shadow")

    return policy, reasons


async def get_expected_execution(rdb, stk_cd: str) -> dict:
    """Read pre-open expected execution data written from WS 0H."""
    try:
        return await rdb.hgetall(f"ws:expected:{stk_cd}")
    except Exception:
        return {}


async def _redis_expected_snapshots(rdb, limit: int = 100) -> dict[str, dict]:
    """Build S1 fallback snapshots from ws:expected hashes when ka10029 is empty."""
    if not rdb:
        return {}

    snapshots: dict[str, dict] = {}
    try:
        async for raw_key in rdb.scan_iter(match="ws:expected:*", count=200):
            key = raw_key.decode("utf-8", errors="ignore") if isinstance(raw_key, bytes) else str(raw_key)
            stk_cd = key.rsplit(":", 1)[-1].strip()
            if not stk_cd:
                continue

            exp = await rdb.hgetall(key)
            decoded = {}
            for field, value in (exp or {}).items():
                if isinstance(field, bytes):
                    field = field.decode("utf-8", errors="ignore")
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="ignore")
                decoded[str(field)] = str(value)

            exp_price = clean_num(decoded.get("exp_cntr_pric", 0))
            gap_pct = clean_num(decoded.get("exp_flu_rt", decoded.get("flu_rt", 0)))
            if exp_price <= 0 or not (2.5 <= gap_pct <= 15.0):
                continue

            decoded["exp_cntr_pric"] = decoded.get("exp_cntr_pric", "")
            decoded["exp_flu_rt"] = decoded.get("exp_flu_rt", decoded.get("flu_rt", ""))
            snapshots[stk_cd] = decoded
            if len(snapshots) >= limit:
                break
    except Exception as exc:
        logger.debug("[S1] ws:expected fallback scan failed: %s", exc)
        return {}

    return snapshots


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
                        "stk_cnd": "16",
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
                    "stk_cnd": "16",
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


async def _fetch_minute_chart_s1(token: str, stk_cd: str, scope: int = 1) -> dict:
    """ka10080 분봉차트 조회 (S1 execution_quality 용). 분봉 응답 전체 dict 반환."""
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/chart",
                headers={
                    "api-id": "ka10080",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "stk_cd": stk_cd.strip(),
                    "tic_scope": str(scope),
                    "upd_stkpc_tp": "1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10080", logger):
                return {}
            return data
    except Exception as exc:
        logger.debug("[S1] ka10080 분봉 조회 실패 [%s]: %s", stk_cd, exc)
        return {}


async def _fetch_hoga_raw_s1(token: str, stk_cd: str) -> dict:
    """ka10004 호가 raw dict 반환 (S1 execution_quality 용)."""
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10004",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd.strip()},
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10004", logger):
                return {}
            return data
    except Exception as exc:
        logger.debug("[S1] ka10004 호가 조회 실패 [%s]: %s", stk_cd, exc)
        return {}


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
            rest_snapshots = await _redis_expected_snapshots(rdb)
            effective = list(rest_snapshots.keys())
            fallback_used = bool(effective)
            stats["candidate_count"] = len(effective)
            if fallback_used:
                logger.warning("[S1] candidate pool empty; using ws:expected fallback (%d)", len(effective))
            else:
                logger.warning("[S1] candidate pool empty and fallbacks returned nothing")

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
        expected_age = _expected_age_ms(exp)
        expected_bid_decay_pct = _expected_bid_decay_pct(exp)

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
        min_strength = 115.0 if 3.0 <= gap_pct < 5.0 else 120.0
        if strength < min_strength:
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

        # ── execution_quality 통합 (shadow 모드) ──────────────────────────
        await asyncio.sleep(_API_INTERVAL)
        hoga_raw = await _fetch_hoga_raw_s1(token, stk_cd)
        await asyncio.sleep(_API_INTERVAL)
        candle_raw = await _fetch_minute_chart_s1(token, stk_cd, scope=1)

        # 첫 3분봉 저가 추출 (분봉 데이터에서)
        candle_list = candle_raw.get("stk_min_pole_chart_qry", [])
        first_3m_low: float | None = None
        if candle_list:
            try:
                recent_lows = [
                    abs(float(str(c.get("low_pric", 0)).replace("+", "").replace(",", "")))
                    for c in candle_list[:3]
                    if c.get("low_pric")
                ]
                if recent_lows:
                    first_3m_low = min(v for v in recent_lows if v > 0)
            except Exception:
                pass

        # 예상체결 매수잔량 감소율 (장전 buy_req 스냅샷 차분 — 현재는 None)
        # 장시작 후 예상가 대비 추가 상승폭 (현재가 vs 예상가)
        post_open_extension_pct: float | None = None
        cur_price = float(exp_price)
        if candle_list:
            try:
                parsed_cur_price = abs(float(str(candle_list[0].get("cur_prc", 0)).replace("+", "").replace(",", "")))
                if parsed_cur_price > 0:
                    cur_price = parsed_cur_price
            except Exception:
                pass
        if exp_price > 0 and cur_price > 0:
            try:
                post_open_extension_pct = round((cur_price - exp_price) / exp_price * 100, 2)
            except Exception:
                pass

        eq_result = assess_execution_quality(
            stk_cd,
            cur_price,
            hoga_raw,
            candle_raw,
            "S1",
            extra={"gap_pct": gap_pct},
        )

        # HARD_GATE 모드: REJECT이면 탈락
        if should_hard_reject(eq_result):
            logger.debug("[S1] execution_quality REJECT skip [%s]", stk_cd)
            continue

        # execution_quality가 REJECT이면 signal_mode를 SHADOW로 격하
        if eq_result["execution_quality"] == "REJECT" and signal_mode == "NORMAL":
            signal_mode = "SHADOW"

        entry_policy, entry_policy_reasons = _s1_entry_policy(
            gap_pct=gap_pct,
            strength=strength,
            bid_ratio=bid_ratio,
            rr_ratio=tp_sl.rr_ratio,
            early_open=early_open,
            expected_age_ms=expected_age,
            expected_bid_decay_pct=expected_bid_decay_pct,
            post_open_extension_pct=post_open_extension_pct,
            execution_quality=eq_result["execution_quality"],
            first_low_break=bool(eq_result["first_low_break"]),
            vwap_position=str(eq_result["vwap_position"]),
        )
        if entry_policy == "HOLD_RECHECK" and signal_mode == "NORMAL":
            signal_mode = "HOLD_RECHECK"
        elif entry_policy == "CANCEL":
            signal_mode = "SHADOW"

        signal = {
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "cur_prc": exp_price,
                "entry_price": exp_price,
                "strategy": "S1_GAP_OPEN",
                "gap_pct": round(gap_pct, 2),
                "gap_zone": ("overheat" if gap_overheat else "strong" if gap_strong else "normal"),
                "signal_mode": signal_mode,
                "s1_entry_policy": entry_policy,
                "s1_entry_policy_reasons": entry_policy_reasons,
                "early_open": early_open,
                "cntr_strength": round(strength, 1),
                "bid_ratio": round(bid_ratio, 2) if bid_ratio is not None else None,
                "score": round(score, 2),
                "entry_type": "시초가_시장가",
                # S1 추격 품질 필드
                "expected_age_ms": expected_age,
                "expected_bid_decay_pct": expected_bid_decay_pct,
                "post_open_extension_pct": post_open_extension_pct,
                "first_3m_low": first_3m_low,
                "first_low_break": eq_result["first_low_break"],
                "vwap_position": eq_result["vwap_position"],
                "chase_risk_score": eq_result["chase_risk_score"],
                "execution_quality": eq_result["execution_quality"],
                **tp_sl.to_signal_fields(),
            }
        try:
            await asyncio.sleep(_API_INTERVAL)
            profile, profile_meta = await fetch_volume_profile(token, stk_cd)
            signal["volume_profile_meta"] = profile_meta
            if profile.get("target_verified"):
                signal = apply_volume_profile_rr(signal, profile)
        except Exception as exc:
            logger.debug("[S1] ka10025 volume profile failed [%s]: %s", stk_cd, exc)

        results.append(signal)

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


