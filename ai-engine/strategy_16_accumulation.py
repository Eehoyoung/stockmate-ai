from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from http_utils import (
    apply_volume_profile_rr,
    fetch_cntr_strength_cached,
    fetch_daily_cntr_strength,
    fetch_hoga,
    fetch_investor_flow_summary_cached,
    fetch_program_snapshot,
    fetch_stk_nm,
    fetch_volume_profile,
    program_drop_reason,
)
from ma_utils import _safe_price, _safe_vol, fetch_daily_candles
from s16_accumulation_state import (
    STATE_ACCUMULATING,
    STATE_ARMED,
    STATE_REJECTED,
    STATE_TRIGGERED,
    STRATEGY_NAME,
    S16WatchState,
    enqueue_trigger,
    load_watch_state,
    pop_trigger,
    record_event,
    save_watch_state,
)
from utils import normalize_stock_code


logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

S16_ENABLED = os.getenv("S16_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
S16_MIN_MARKET_CAP_EOK = float(os.getenv("S16_MIN_MARKET_CAP_EOK", "1500"))
S16_MAX_MARKET_CAP_EOK = float(os.getenv("S16_MAX_MARKET_CAP_EOK", "10000"))
S16_LOOKBACK_DAYS = int(os.getenv("S16_LOOKBACK_DAYS", "60"))
S16_BOX_DAYS = int(os.getenv("S16_BOX_DAYS", "40"))
S16_ARMED_SCORE = float(os.getenv("S16_ARMED_SCORE", "75"))
S16_TRIGGER_SCORE = float(os.getenv("S16_TRIGGER_SCORE", "80"))
S16_MIN_RR = float(os.getenv("S16_MIN_RR", "1.6"))
S16_CONFIRM_BUY_MIN_RR = float(os.getenv("S16_CONFIRM_BUY_MIN_RR", "1.8"))
S16_MIN_CNTR_STRENGTH = float(os.getenv("S16_MIN_CNTR_STRENGTH", "120"))
S16_MIN_BID_RATIO = float(os.getenv("S16_MIN_BID_RATIO", "1.3"))
S16_MAX_5D_RISE_PCT = float(os.getenv("S16_MAX_5D_RISE_PCT", "25"))
S16_MAX_20D_RISE_PCT = float(os.getenv("S16_MAX_20D_RISE_PCT", "35"))
S16_MIN_AVG_TRADING_VALUE_EOK = float(os.getenv("S16_MIN_AVG_TRADING_VALUE_EOK", "20"))
S16_CANDIDATE_LIMIT = int(os.getenv("S16_CANDIDATE_LIMIT", "40"))
S16_SIGNAL_LIMIT = int(os.getenv("S16_SIGNAL_LIMIT", "5"))
S16_RECHECK_SEC = int(os.getenv("S16_RECHECK_SEC", "1800"))
S16_TRIGGER_DEDUP_TTL_SEC = int(os.getenv("S16_TRIGGER_DEDUP_TTL_SEC", "21600"))
S16_MIN_OBSERVE_DAYS = int(os.getenv("S16_MIN_OBSERVE_DAYS", "2"))


@dataclass
class S16Metrics:
    state: str
    accumulation_score: float
    supply_score: float
    trigger_score: float
    risk_score: float
    total_score: float
    box_low: float
    box_high: float
    cur_prc: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    rr_ratio: float
    vol_ratio: float
    twenty_day_rise_pct: float
    five_day_rise_pct: float
    avg_trading_value_eok: float
    reason: str


def _sf(value, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").replace("+", "") or default)
    except (TypeError, ValueError):
        return default


def _pct(new: float, old: float) -> float:
    if old <= 0:
        return 0.0
    return (new - old) / old * 100.0


def _avg(values: Iterable[float]) -> float:
    vals = [v for v in values if v > 0]
    return sum(vals) / len(vals) if vals else 0.0


def _normalize_market_cap_eok(value) -> float:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    market_cap = _sf(value, 0.0)
    return market_cap / 100_000_000 if market_cap > 10_000_000 else market_cap


def _observed_calendar_days(first_seen_at: int, now: int) -> int:
    try:
        first = datetime.fromtimestamp(max(1, int(first_seen_at)), KST).date()
        current = datetime.fromtimestamp(max(1, int(now)), KST).date()
        return max(1, (current - first).days + 1)
    except Exception:
        return 1


def _recent_high(candles: list[dict], days: int) -> float:
    return max((_safe_price(c.get("high_pric") or c.get("cur_prc")) for c in candles[:days]), default=0.0)


def _recent_low(candles: list[dict], days: int) -> float:
    lows = [_safe_price(c.get("low_pric") or c.get("cur_prc")) for c in candles[:days]]
    lows = [v for v in lows if v > 0]
    return min(lows) if lows else 0.0


def _trading_value_eok(candle: dict) -> float:
    amount = _sf(candle.get("trde_prica"), 0.0)
    if amount > 0:
        return amount / 100_000_000
    close = _safe_price(candle.get("cur_prc"))
    vol = _safe_vol(candle.get("trde_qty"))
    return close * vol / 100_000_000


def _volume_structure_score(candles: list[dict]) -> tuple[float, float]:
    latest_vol = _safe_vol(candles[0].get("trde_qty")) if candles else 0.0
    prev_avg = _avg(_safe_vol(c.get("trde_qty")) for c in candles[1:21])
    vol_ratio = latest_vol / prev_avg if prev_avg > 0 else 0.0

    up_vol = 0.0
    down_vol = 0.0
    for c in candles[:20]:
        close = _safe_price(c.get("cur_prc"))
        open_price = _safe_price(c.get("open_pric"))
        vol = _safe_vol(c.get("trde_qty"))
        if close >= open_price:
            up_vol += vol
        else:
            down_vol += vol
    up_down_ratio = up_vol / down_vol if down_vol > 0 else (2.0 if up_vol > 0 else 0.0)

    score = 0.0
    if up_down_ratio >= 1.4:
        score += 12.0
    elif up_down_ratio >= 1.15:
        score += 8.0
    if 0.8 <= vol_ratio <= 3.0:
        score += 8.0
    elif vol_ratio > 3.0:
        score += 5.0
    return min(20.0, score), vol_ratio


def calculate_s16_metrics(
    candles: list[dict],
    *,
    market_cap_eok: float = 0.0,
    cntr_strength: float = 100.0,
    bid_ratio: float | None = None,
    supply_score_hint: float = 0.0,
) -> S16Metrics:
    market_cap_eok = _normalize_market_cap_eok(market_cap_eok)
    if len(candles) < max(25, min(S16_LOOKBACK_DAYS, 60)):
        return S16Metrics(STATE_REJECTED, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "not enough daily candles")

    lookback = candles[:S16_LOOKBACK_DAYS]
    box_days = min(S16_BOX_DAYS, len(lookback))
    cur_prc = _safe_price(lookback[0].get("cur_prc"))
    box_high = _recent_high(lookback, box_days)
    box_low = _recent_low(lookback, box_days)
    box_width_pct = (box_high - box_low) / cur_prc * 100.0 if cur_prc > 0 else 999.0

    close_5 = _safe_price(lookback[5].get("cur_prc")) if len(lookback) > 5 else 0.0
    close_20 = _safe_price(lookback[20].get("cur_prc")) if len(lookback) > 20 else 0.0
    five_day_rise = _pct(cur_prc, close_5)
    twenty_day_rise = _pct(cur_prc, close_20)
    recent_low_20 = _recent_low(lookback, 20)
    prev_low_20 = _recent_low(lookback[20:40], 20) if len(lookback) >= 40 else 0.0
    low_rising = recent_low_20 > prev_low_20 * 0.98 if prev_low_20 > 0 else False

    avg_value_eok = _avg(_trading_value_eok(c) for c in lookback[:20])
    vol_structure, vol_ratio = _volume_structure_score(lookback)

    accumulation = 0.0
    if 8.0 <= box_width_pct <= 35.0:
        accumulation += 18.0
    elif 35.0 < box_width_pct <= 50.0:
        accumulation += 10.0
    if low_rising:
        accumulation += 12.0
    accumulation += vol_structure
    accumulation = min(50.0, accumulation) / 50.0 * 30.0

    supply_score = max(0.0, min(25.0, supply_score_hint))

    box_proximity_pct = (cur_prc - box_high) / box_high * 100.0 if box_high > 0 else -999.0
    trigger = 0.0
    if cntr_strength >= S16_MIN_CNTR_STRENGTH:
        trigger += 8.0
    elif cntr_strength >= 110:
        trigger += 4.0
    if bid_ratio is not None and bid_ratio >= S16_MIN_BID_RATIO:
        trigger += 5.0
    if vol_ratio >= 1.5:
        trigger += 4.0
    if -4.0 <= box_proximity_pct <= 3.0:
        trigger += 3.0

    risk = 10.0
    risk_reasons = []
    if market_cap_eok and not (S16_MIN_MARKET_CAP_EOK <= market_cap_eok <= S16_MAX_MARKET_CAP_EOK):
        risk -= 7.0
        risk_reasons.append("market_cap_out_of_range")
    if avg_value_eok and avg_value_eok < S16_MIN_AVG_TRADING_VALUE_EOK:
        risk -= 4.0
        risk_reasons.append("low_trading_value")
    if five_day_rise > S16_MAX_5D_RISE_PCT or twenty_day_rise > S16_MAX_20D_RISE_PCT:
        risk -= 6.0
        risk_reasons.append("overheated")
    risk = max(0.0, min(10.0, risk))

    sl_price = max(box_low, cur_prc * 0.94) if cur_prc > 0 else 0.0
    box_range = max(0.0, box_high - box_low)
    tp1_price = max(box_high + box_range * 0.5, cur_prc * 1.05) if cur_prc > 0 else 0.0
    tp2_price = max(box_high + box_range, cur_prc * 1.10) if cur_prc > 0 else 0.0
    risk_per_share = cur_prc - sl_price
    rr = (tp1_price - cur_prc) / risk_per_share if risk_per_share > 0 else 0.0

    total = round(accumulation + supply_score + trigger + risk, 1)
    if total >= S16_TRIGGER_SCORE and trigger >= 14.0 and rr >= S16_MIN_RR and risk >= 5.0:
        state = STATE_TRIGGERED
    elif total >= S16_ARMED_SCORE and risk >= 5.0:
        state = STATE_ARMED
    elif total >= 60.0 and risk >= 4.0:
        state = STATE_ACCUMULATING
    else:
        state = STATE_REJECTED

    reason_parts = [
        f"box_width={box_width_pct:.1f}%",
        f"vol_ratio={vol_ratio:.2f}",
        f"strength={cntr_strength:.1f}",
        f"rr={rr:.2f}",
    ]
    reason_parts.extend(risk_reasons)
    return S16Metrics(
        state=state,
        accumulation_score=round(accumulation, 1),
        supply_score=round(supply_score, 1),
        trigger_score=round(trigger, 1),
        risk_score=round(risk, 1),
        total_score=total,
        box_low=round(box_low, 2),
        box_high=round(box_high, 2),
        cur_prc=round(cur_prc, 2),
        sl_price=round(sl_price),
        tp1_price=round(tp1_price),
        tp2_price=round(tp2_price),
        rr_ratio=round(rr, 3),
        vol_ratio=round(vol_ratio, 3),
        twenty_day_rise_pct=round(twenty_day_rise, 2),
        five_day_rise_pct=round(five_day_rise, 2),
        avg_trading_value_eok=round(avg_value_eok, 2),
        reason=", ".join(reason_parts),
    )


def build_s16_signal(stk_cd: str, stk_nm: str, metrics: S16Metrics, *, market_cap_eok: float = 0.0) -> dict:
    market_cap_eok = _normalize_market_cap_eok(market_cap_eok)
    return {
        "stk_cd": normalize_stock_code(stk_cd),
        "stk_nm": stk_nm,
        "strategy": STRATEGY_NAME,
        "score": metrics.total_score,
        "cur_prc": round(metrics.cur_prc),
        "entry_price": round(metrics.cur_prc),
        "entry_type": "box_breakout_or_first_pullback",
        "accumulation_score": metrics.accumulation_score,
        "supply_score": metrics.supply_score,
        "trigger_score": metrics.trigger_score,
        "risk_score": metrics.risk_score,
        "box_low": metrics.box_low,
        "box_high": metrics.box_high,
        "sl_price": metrics.sl_price,
        "tp1_price": metrics.tp1_price,
        "tp2_price": metrics.tp2_price,
        "rr_ratio": metrics.rr_ratio,
        "effective_rr": metrics.rr_ratio,
        "vol_ratio": metrics.vol_ratio,
        "market_cap_eok": market_cap_eok,
        "s16_state": metrics.state,
        "s16_reason": metrics.reason,
        "signal_mode": "LIVE",
    }


async def _fetch_supply_context(token: str, rdb, stk_cd: str) -> tuple[float, dict]:
    daily_strength, strength_meta = await fetch_daily_cntr_strength(token, stk_cd, days=20)
    investor_flow, investor_meta = await fetch_investor_flow_summary_cached(token, stk_cd, rdb=rdb, days=10)
    program_snapshot = await fetch_program_snapshot(rdb, stk_cd)

    score = 0.0
    latest = _sf(daily_strength.get("latest"), 0.0)
    avg_5 = _sf(daily_strength.get("avg_5"), 0.0)
    avg_20 = _sf(daily_strength.get("avg_20"), 0.0)
    strong_days = _sf(daily_strength.get("strong_days"), 0.0)
    if latest >= 130:
        score += 5.0
    elif latest >= 115:
        score += 3.0
    if avg_5 >= 125:
        score += 5.0
    elif avg_5 >= 112:
        score += 3.0
    if avg_20 >= 110:
        score += 4.0
    if strong_days >= 4:
        score += 3.0

    smart_money = _sf(investor_flow.get("smart_money"), 0.0)
    foreign = _sf(investor_flow.get("foreign"), 0.0)
    institution = _sf(investor_flow.get("institution"), 0.0)
    if smart_money > 0:
        score += 5.0
    if foreign > 0 and institution > 0:
        score += 3.0

    net_amt = _sf(program_snapshot.get("program_net_buy_amt"), 0.0)
    net_chg = _sf(program_snapshot.get("program_net_buy_amt_chg"), 0.0)
    if net_amt > 0:
        score += 2.0
    if net_chg > 0:
        score += 1.0

    detail = {
        "daily_strength": daily_strength,
        "daily_strength_meta": strength_meta,
        "investor_flow": investor_flow,
        "investor_flow_meta": investor_meta,
        "program_snapshot": program_snapshot,
        "program_drop_reason": program_drop_reason(program_snapshot),
    }
    return min(25.0, score), detail


async def _read_candidate_codes(rdb, market: str) -> list[str]:
    keys = [
        "s16:universe",
        "candidates:watchlist",
        f"candidates:s15:{market}",
        f"candidates:s13:{market}",
        f"candidates:s11:{market}",
    ]
    seen = set()
    codes: list[str] = []
    for key in keys:
        try:
            if key.endswith(":watchlist") or key == "s16:universe":
                raw_values = await rdb.smembers(key)
            else:
                raw_values = await rdb.lrange(key, 0, S16_CANDIDATE_LIMIT - 1)
        except Exception:
            raw_values = []
        for raw in raw_values or []:
            code = normalize_stock_code(raw)
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
            if len(codes) >= S16_CANDIDATE_LIMIT:
                return codes
    return codes


async def _market_cap_eok(rdb, stk_cd: str) -> float:
    try:
        raw = await rdb.get(f"stock:mktcap:{stk_cd}")
        return _normalize_market_cap_eok(raw)
    except Exception:
        return 0.0


async def _evaluate_code(token: str, rdb, stk_cd: str) -> dict | None:
    code = normalize_stock_code(stk_cd)
    if not code:
        return None
    candles = await fetch_daily_candles(token, code, target_count=S16_LOOKBACK_DAYS)
    market_cap = await _market_cap_eok(rdb, code)
    strength, _ = await fetch_cntr_strength_cached(token, code, rdb=rdb)
    bid_ratio = await fetch_hoga(token, code, rdb=rdb)
    supply_score, supply_detail = await _fetch_supply_context(token, rdb, code)
    metrics = calculate_s16_metrics(
        candles,
        market_cap_eok=market_cap,
        cntr_strength=strength,
        bid_ratio=bid_ratio,
        supply_score_hint=supply_score,
    )

    now = int(time.time())
    previous = await load_watch_state(rdb, code)
    first_seen_at = previous.first_seen_at if previous else now
    observe_days = _observed_calendar_days(first_seen_at, now)
    state = S16WatchState(
        stk_cd=code,
        state=metrics.state,
        first_seen_at=first_seen_at,
        last_seen_at=now,
        observe_days=observe_days,
        market_cap_eok=market_cap,
        accumulation_score=metrics.accumulation_score,
        supply_score=metrics.supply_score,
        trigger_score=metrics.trigger_score,
        risk_score=metrics.risk_score,
        total_score=metrics.total_score,
        box_low=metrics.box_low,
        box_high=metrics.box_high,
        cur_prc=metrics.cur_prc,
        rr_ratio=metrics.rr_ratio,
        last_reason=metrics.reason,
    )
    await save_watch_state(rdb, state, next_check_at=now + S16_RECHECK_SEC)
    if metrics.state != STATE_TRIGGERED:
        return None
    if observe_days < S16_MIN_OBSERVE_DAYS:
        await record_event(
            rdb,
            {
                "stk_cd": code,
                "state": metrics.state,
                "enqueued": False,
                "score": metrics.total_score,
                "blocked_reason": "observe_days",
                "observe_days": observe_days,
                "min_observe_days": S16_MIN_OBSERVE_DAYS,
            },
        )
        return None

    stk_nm = await fetch_stk_nm(rdb, token, code)
    signal = build_s16_signal(code, stk_nm, metrics, market_cap_eok=market_cap)
    program_snapshot = supply_detail.get("program_snapshot") or {}
    signal.update(program_snapshot)
    if supply_detail.get("program_drop_reason"):
        signal["program_drop_reason"] = supply_detail["program_drop_reason"]
    signal["s16_supply_detail"] = supply_detail
    profile, profile_meta = await fetch_volume_profile(token, code)
    signal["volume_profile_meta"] = profile_meta
    signal = apply_volume_profile_rr(signal, profile)
    signal["effective_rr"] = signal.get("rr_ratio", metrics.rr_ratio)
    ymd = datetime.now(KST).strftime("%Y%m%d")
    enqueued = await enqueue_trigger(rdb, signal, ymd=ymd, ttl_sec=S16_TRIGGER_DEDUP_TTL_SEC)
    await record_event(rdb, {"stk_cd": code, "state": metrics.state, "enqueued": bool(enqueued), "score": metrics.total_score})
    return signal if enqueued else None


async def scan_accumulation_shadow(token: str, market: str = "000", rdb=None) -> list[dict]:
    if not S16_ENABLED or rdb is None:
        return []

    codes = await _read_candidate_codes(rdb, market)
    for code in codes:
        try:
            await _evaluate_code(token, rdb, code)
        except Exception as exc:
            logger.debug("[S16] evaluation failed %s: %s", code, exc)

    signals: list[dict] = []
    for _ in range(S16_SIGNAL_LIMIT):
        item = await pop_trigger(rdb)
        if not item:
            break
        if _sf(item.get("rr_ratio"), 0.0) < S16_MIN_RR:
            continue
        signals.append(item)
    return signals
