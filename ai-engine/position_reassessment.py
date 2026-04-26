from __future__ import annotations

"""
position_reassessment.py
Open position indicator refresh loop.

After entry, this worker periodically refreshes technical-analysis context
for each active position and stores a compact snapshot in Redis so
position_monitor and notifications can use more realistic, current context.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from db_reader import get_active_positions
from http_utils import fetch_hoga
from indicator_atr import get_atr_minute
from indicator_macd import get_macd_daily, get_macd_minute
from indicator_rsi import get_rsi_daily, get_rsi_minute
from indicator_stochastic import get_stochastic_minute
from indicator_volume import get_vwap_minute
from ma_utils import get_ma_context
from redis_reader import get_avg_cntr_strength, get_tick_data

logger = logging.getLogger("position_reassessment")

REDIS_TOKEN_KEY = "kiwoom:token"
REASSESS_INTERVAL_SEC = int(os.getenv("POSITION_REASSESS_INTERVAL_SEC", "300"))
REASSESS_CACHE_TTL_SEC = int(os.getenv("POSITION_REASSESS_CACHE_TTL_SEC", "900"))
MINUTE_SCOPE = os.getenv("POSITION_REASSESS_MIN_SCOPE", "5")


def classify_trend_state(
    cur_prc: float,
    ma20: float | None,
    ma60: float | None,
    daily_rsi: float | None,
) -> str:
    if cur_prc > 0 and ma20 and ma60 and cur_prc >= ma20 >= ma60:
        return "BULLISH"
    if cur_prc > 0 and ma20 and cur_prc < ma20:
        return "BEARISH"
    if daily_rsi is not None and daily_rsi < 40:
        return "BEARISH"
    return "NEUTRAL"


def classify_momentum_state(
    minute_rsi: float | None,
    macd_hist: float | None,
    macd_hist_prev: float | None,
    stoch_k: float | None,
    cur_prc: float,
    vwap: float | None,
) -> str:
    above_vwap = bool(vwap and cur_prc > 0 and cur_prc >= vwap)
    hist_up = macd_hist is not None and macd_hist_prev is not None and macd_hist > 0 and macd_hist >= macd_hist_prev
    hist_down = macd_hist is not None and macd_hist_prev is not None and macd_hist < macd_hist_prev

    if above_vwap and hist_up and minute_rsi is not None and 50 <= minute_rsi <= 75:
        return "STRONG"
    if (minute_rsi is not None and minute_rsi < 45) or (vwap and cur_prc > 0 and cur_prc < vwap) or hist_down:
        return "WEAK"
    if stoch_k is not None and stoch_k > 80:
        return "OVERHEATED"
    return "NEUTRAL"


def decide_exit_bias(
    trend_state: str,
    momentum_state: str,
    hoga_ratio: float | None,
    cntr_strength: float | None,
) -> str:
    if trend_state == "BEARISH" or momentum_state == "WEAK":
        return "TIGHTEN"
    if momentum_state == "OVERHEATED":
        return "TRIM"
    if trend_state == "BULLISH" and momentum_state == "STRONG" and (cntr_strength or 0) >= 105 and (hoga_ratio or 1.0) <= 1.2:
        return "HOLD"
    return "CAUTIOUS"


def build_reason_summary(trend_state: str, momentum_state: str, exit_bias: str) -> str:
    trend_map = {
        "BULLISH": "일봉 추세 우상향",
        "BEARISH": "일봉 추세 약화",
        "NEUTRAL": "일봉 추세 중립",
    }
    momentum_map = {
        "STRONG": "분봉 모멘텀 강함",
        "WEAK": "분봉 모멘텀 둔화",
        "OVERHEATED": "단기 과열 구간",
        "NEUTRAL": "분봉 모멘텀 중립",
    }
    bias_map = {
        "HOLD": "추세 보유 우선",
        "TIGHTEN": "트레일링 타이트 필요",
        "TRIM": "이익 보호 우선",
        "CAUTIOUS": "보수적 관리 필요",
    }
    return f"{trend_map.get(trend_state, trend_state)} / {momentum_map.get(momentum_state, momentum_state)} / {bias_map.get(exit_bias, exit_bias)}"


async def run_position_reassessment(rdb, pg_pool):
    if pg_pool is None:
        logger.warning("[PosReassess] PostgreSQL pool missing; reassessment disabled")
        return

    logger.info("[PosReassess] started (interval=%ss, ttl=%ss)", REASSESS_INTERVAL_SEC, REASSESS_CACHE_TTL_SEC)
    while True:
        try:
            await asyncio.sleep(REASSESS_INTERVAL_SEC)
            await _refresh_all(rdb, pg_pool)
        except asyncio.CancelledError:
            logger.info("[PosReassess] stopped")
            break
        except Exception as exc:
            logger.error("[PosReassess] loop error: %s", exc, exc_info=True)
            await asyncio.sleep(10)


async def _refresh_all(rdb, pg_pool):
    positions = await get_active_positions(pg_pool)
    if not positions:
        return

    token = await rdb.get(REDIS_TOKEN_KEY)
    if not token:
        logger.debug("[PosReassess] no kiwoom token; skip refresh")
        return

    tasks = [_refresh_position(rdb, token, pos) for pos in positions]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _refresh_position(rdb, token: str, pos: dict):
    position_id = pos["id"]
    stk_cd = pos["stk_cd"]
    tick = await get_tick_data(rdb, stk_cd)
    cur_prc = _safe_float(tick.get("cur_prc")) or _safe_float(pos.get("entry_price"))

    (
        ma_ctx,
        rsi_daily,
        rsi_min,
        macd_daily,
        macd_min,
        stoch,
        atr_result,
        vwap_result,
        hoga_ratio,
        cntr_strength,
    ) = await asyncio.gather(
        get_ma_context(token, stk_cd),
        get_rsi_daily(token, stk_cd),
        get_rsi_minute(token, stk_cd, tic_scope=MINUTE_SCOPE),
        get_macd_daily(token, stk_cd),
        get_macd_minute(token, stk_cd, tic_scope=MINUTE_SCOPE),
        get_stochastic_minute(token, stk_cd, tic_scope=MINUTE_SCOPE),
        get_atr_minute(token, stk_cd, tic_scope=MINUTE_SCOPE),
        get_vwap_minute(token, stk_cd, tic_scope=MINUTE_SCOPE),
        fetch_hoga(token, stk_cd, rdb=rdb),
        get_avg_cntr_strength(rdb, stk_cd, count=5),
        return_exceptions=False,
    )

    trend_state = classify_trend_state(cur_prc, ma_ctx.ma20, ma_ctx.ma60, rsi_daily.rsi)
    momentum_state = classify_momentum_state(
        rsi_min.rsi,
        macd_min.histogram,
        macd_min.hist_prev,
        stoch.k,
        cur_prc,
        vwap_result.vwap,
    )
    exit_bias = decide_exit_bias(trend_state, momentum_state, hoga_ratio, cntr_strength)
    dynamic_trailing_pct = _dynamic_trailing(float(pos.get("trailing_pct") or 1.5), exit_bias)
    reason_summary = build_reason_summary(trend_state, momentum_state, exit_bias)

    snapshot = {
        "position_id": position_id,
        "stk_cd": stk_cd,
        "strategy": pos.get("strategy", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cur_prc": round(cur_prc) if cur_prc else None,
        "ma20": _round_opt(ma_ctx.ma20),
        "ma60": _round_opt(ma_ctx.ma60),
        "daily_rsi": _round_opt(rsi_daily.rsi, 2),
        "minute_rsi": _round_opt(rsi_min.rsi, 2),
        "daily_macd_hist": _round_opt(macd_daily.histogram, 4),
        "minute_macd_hist": _round_opt(macd_min.histogram, 4),
        "minute_macd_hist_prev": _round_opt(macd_min.hist_prev, 4),
        "stoch_k": _round_opt(stoch.k, 2),
        "stoch_d": _round_opt(stoch.d, 2),
        "atr_pct": _round_opt(atr_result.atr_pct, 3),
        "vwap": _round_opt(vwap_result.vwap),
        "hoga_ratio": _round_opt(hoga_ratio, 3),
        "cntr_strength": _round_opt(cntr_strength, 2),
        "trend_state": trend_state,
        "momentum_state": momentum_state,
        "exit_bias": exit_bias,
        "dynamic_trailing_pct": round(dynamic_trailing_pct, 2),
        "reason_summary": reason_summary,
    }

    await rdb.set(f"position_ctx:{position_id}", json.dumps(snapshot, ensure_ascii=False), ex=REASSESS_CACHE_TTL_SEC)


def _dynamic_trailing(base_trailing_pct: float, exit_bias: str) -> float:
    if exit_bias == "TIGHTEN":
        return max(0.7, base_trailing_pct - 0.5)
    if exit_bias == "TRIM":
        return max(0.8, base_trailing_pct - 0.3)
    if exit_bias == "HOLD":
        return min(base_trailing_pct + 0.3, 4.0)
    return base_trailing_pct


def _safe_float(raw) -> float:
    try:
        return float(str(raw).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def _round_opt(value, digits: int = 0):
    if value is None:
        return None
    if digits == 0:
        return round(value)
    return round(value, digits)
