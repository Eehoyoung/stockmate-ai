"""
db_writer.py
Python ai-engine PostgreSQL write helpers (asyncpg based).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import asyncpg

from position_lifecycle import ACTIVE_POSITION_STATES, ACTIVE_SIGNAL_STATUSES, TERMINAL_SIGNAL_STATUSES
from utils import normalize_stock_code, safe_float_opt as _sf

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _opt_num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _opt_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _zone_insert_params(signal: dict) -> tuple:
    """
    buy_zone / sell_zone1 dict에서 DB INSERT용 파라미터 7개 추출.
    순서: buy_zone_low, buy_zone_high, buy_zone_anchors, buy_zone_strength,
          sell_zone1_low, sell_zone1_high, zone_rr
    """
    import json as _json
    bz = signal.get("buy_zone")
    sz = signal.get("sell_zone1")
    if not isinstance(bz, dict):
        bz = None
    if not isinstance(sz, dict):
        sz = None
    return (
        _opt_num(bz.get("low"))      if bz else None,
        _opt_num(bz.get("high"))     if bz else None,
        _json.dumps(bz.get("anchors", []), ensure_ascii=False) if bz else None,
        int(bz["strength"])          if bz and bz.get("strength") is not None else None,
        _opt_num(sz.get("low"))      if sz else None,
        _opt_num(sz.get("high"))     if sz else None,
        _opt_num(signal.get("zone_rr")),
    )


def _opt_bool(v) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"true", "1", "y", "yes"}:
        return True
    if s in {"false", "0", "n", "no"}:
        return False
    return None


def _clip_str(v, limit: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:limit]


def _add_business_days(start_dt: datetime, days: int) -> datetime:
    cur = start_dt
    remaining = max(days, 0)
    while remaining > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            remaining -= 1
    return cur


def _resolve_time_stop_deadline_utc(
    *,
    created_at_utc: datetime,
    time_stop_type: Optional[str],
    time_stop_minutes: Optional[int],
    time_stop_session: Optional[str],
) -> Optional[datetime]:
    if not time_stop_type and not time_stop_session:
        return None
    base_kst = created_at_utc.astimezone(KST)
    stop_type = str(time_stop_type or "").strip()
    stop_session = str(time_stop_session or "").strip()
    minutes = _opt_int(time_stop_minutes)

    if stop_type == "intraday_minutes" and minutes is not None:
        return (created_at_utc + timedelta(minutes=minutes)).astimezone(timezone.utc)
    if stop_type == "trading_days" and minutes is not None:
        deadline_kst = _add_business_days(base_kst, minutes).replace(hour=15, minute=18, second=0, microsecond=0)
        return deadline_kst.astimezone(timezone.utc)
    if stop_type == "session_close" and stop_session == "same_day_close":
        return base_kst.replace(hour=15, minute=18, second=0, microsecond=0).astimezone(timezone.utc)
    if stop_type == "session_close" and stop_session == "next_day_morning":
        next_kst = _add_business_days(base_kst, 1).replace(hour=10, minute=30, second=0, microsecond=0)
        return next_kst.astimezone(timezone.utc)
    if stop_session == "same_day_close":
        return base_kst.replace(hour=15, minute=18, second=0, microsecond=0).astimezone(timezone.utc)
    return None


def _next_trading_day_preopen_utc(base_dt: Optional[datetime] = None) -> datetime:
    base = base_dt.astimezone(KST) if base_dt else datetime.now(KST)
    candidate = base.date() + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    next_run_kst = datetime.combine(candidate, datetime.min.time(), tzinfo=KST).replace(hour=7)
    return next_run_kst.astimezone(timezone.utc)


def _is_active_signal(signal_status: Optional[str], exit_type: Optional[str]) -> bool:
    return (signal_status or "PENDING") in ACTIVE_SIGNAL_STATUSES and not exit_type


def _parse_utc_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _shadow_result(realized_pnl_pct: Optional[float], exit_reason: Optional[str]) -> str:
    reason = str(exit_reason or "").upper()
    pnl = _opt_num(realized_pnl_pct)
    if reason in {"TP1_HIT", "TP2_HIT"}:
        return "WIN"
    if reason == "SL_HIT":
        return "LOSS"
    if pnl is None:
        return "EXIT"
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "FLAT"


async def _load_signal_for_update(conn, signal_id: int):
    return await conn.fetchrow(
        """
        SELECT id, stk_cd, stk_nm, strategy, market_type, entry_price, tp1_price, tp2_price, sl_price,
               tp_method, sl_method, rr_ratio, signal_status, exit_type, created_at, executed_at,
               position_status, entry_at, tp1_hit_at, peak_price, trailing_pct, trailing_activation,
               trailing_basis, strategy_version, time_stop_type, time_stop_minutes, time_stop_session,
               monitor_enabled, is_overnight, overnight_verdict, overnight_score
        FROM trading_signals
        WHERE id = $1
        FOR UPDATE
        """,
        signal_id,
    )


def _build_position_row(row) -> dict:
    data = dict(row)
    status = str(data.get("position_status") or "ACTIVE")
    if status not in ACTIVE_POSITION_STATES:
        status = "ACTIVE"
    return {
        "id": data["id"],
        "signal_id": data["id"],
        "stk_cd": data.get("stk_cd"),
        "stk_nm": data.get("stk_nm"),
        "strategy": data.get("strategy"),
        "market": data.get("market_type"),
        "entry_price": data.get("entry_price"),
        "tp1_price": data.get("tp1_price"),
        "tp2_price": data.get("tp2_price"),
        "sl_price": data.get("sl_price"),
        "tp_method": data.get("tp_method"),
        "sl_method": data.get("sl_method"),
        "rr_ratio": data.get("rr_ratio"),
        "status": status,
        "tp1_hit_at": data.get("tp1_hit_at"),
        "peak_price": data.get("peak_price"),
        "trailing_pct": data.get("trailing_pct"),
        "trailing_activation": data.get("trailing_activation"),
        "trailing_basis": data.get("trailing_basis"),
        "strategy_version": data.get("strategy_version"),
        "time_stop_type": data.get("time_stop_type"),
        "time_stop_minutes": data.get("time_stop_minutes"),
        "time_stop_session": data.get("time_stop_session"),
        "entry_at": data.get("entry_at") or data.get("executed_at") or data.get("created_at"),
        "monitor_enabled": True if data.get("monitor_enabled") is None else bool(data.get("monitor_enabled")),
        "is_overnight": bool(data.get("is_overnight", False)),
        "overnight_verdict": data.get("overnight_verdict"),
        "overnight_score": data.get("overnight_score"),
    }


def _calc_realized_rr(entry_price: Optional[float], sl_price: Optional[float], exit_price: Optional[float]) -> Optional[float]:
    entry = _opt_num(entry_price)
    sl = _opt_num(sl_price)
    exit_p = _opt_num(exit_price)
    if entry is None or sl is None or exit_p is None:
        return None
    risk = entry - sl
    if risk <= 0:
        return None
    return round((exit_p - entry) / risk, 3)


async def _insert_position_state_event(
    conn,
    *,
    signal_id: int,
    event_type: str,
    position_status: Optional[str] = None,
    peak_price: Optional[float] = None,
    trailing_stop_price: Optional[float] = None,
    payload: Optional[dict] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO position_state_events (
            signal_id, event_type, position_status, peak_price, trailing_stop_price, payload
        ) VALUES (
            $1, $2, $3, $4, $5, $6::jsonb
        )
        """,
        signal_id,
        event_type,
        position_status,
        _opt_int(peak_price),
        _opt_int(trailing_stop_price),
        json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
    )


async def _upsert_primary_trade_plan(
    conn,
    *,
    signal_id: int,
    strategy_code: Optional[str],
    strategy_version: Optional[str],
    entry_price: Optional[float],
    tp_price: Optional[float],
    sl_price: Optional[float],
    planned_rr: Optional[float],
    effective_rr: Optional[float],
    tp_model: Optional[str],
    sl_model: Optional[str],
    time_stop_type: Optional[str],
    time_stop_minutes: Optional[int],
    time_stop_session: Optional[str],
    trailing_basis: Optional[str],
    trailing_pct: Optional[float],
) -> None:
    strategy_code = (strategy_code or "").strip() or "UNKNOWN"
    strategy_version = _clip_str(strategy_version, 40)
    tp_model = _clip_str(tp_model, 200)
    sl_model = _clip_str(sl_model, 200)
    time_stop_type = _clip_str(time_stop_type, 30)
    time_stop_session = _clip_str(time_stop_session, 30)
    entry = _opt_num(entry_price)
    tp = _opt_num(tp_price)
    sl = _opt_num(sl_price)
    tp_pct = round((tp - entry) / entry * 100, 3) if entry and tp and tp > 0 else None
    sl_pct = round((entry - sl) / entry * 100, 3) if entry and sl and sl > 0 else None
    trailing_rule = None
    if trailing_pct is not None:
        basis = str(trailing_basis or "single_tp")
        trailing_rule = _clip_str(f"{basis}:{round(float(trailing_pct), 2)}%", 200)

    updated = await conn.execute(
        """
        UPDATE trade_plans
        SET strategy_code = $2,
            strategy_version = $3,
            tp_model = $4,
            sl_model = $5,
            tp_price = $6,
            sl_price = $7,
            tp_pct = $8,
            sl_pct = $9,
            planned_rr = $10,
            effective_rr = $11,
            time_stop_type = $12,
            time_stop_minutes = $13,
            time_stop_session = $14,
            trailing_rule = $15,
            partial_tp_rule = 'single_tp',
            planned_exit_priority = 'tp_then_trailing_then_sl_then_time'
        WHERE signal_id = $1
          AND variant_rank = 1
        """,
        signal_id,
        strategy_code,
        strategy_version,
        tp_model,
        sl_model,
        _opt_int(tp),
        _opt_int(sl),
        _opt_num(tp_pct),
        _opt_num(sl_pct),
        _opt_num(planned_rr),
        _opt_num(effective_rr),
        time_stop_type,
        _opt_int(time_stop_minutes),
        time_stop_session,
        trailing_rule,
    )
    if updated != "UPDATE 1":
        await conn.execute(
            """
            INSERT INTO trade_plans (
                signal_id, strategy_code, strategy_version, plan_name,
                tp_model, sl_model, tp_price, sl_price, tp_pct, sl_pct,
                planned_rr, effective_rr, time_stop_type, time_stop_minutes, time_stop_session,
                trailing_rule, partial_tp_rule, planned_exit_priority, variant_rank
            ) VALUES (
                $1, $2, $3, 'primary',
                $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14,
                $15, 'single_tp', 'tp_then_trailing_then_sl_then_time', 1
            )
            """,
            signal_id,
            strategy_code,
            strategy_version,
            tp_model,
            sl_model,
            _opt_int(tp),
            _opt_int(sl),
            _opt_num(tp_pct),
            _opt_num(sl_pct),
            _opt_num(planned_rr),
            _opt_num(effective_rr),
            time_stop_type,
            _opt_int(time_stop_minutes),
            time_stop_session,
            trailing_rule,
        )


async def _insert_trade_outcome(
    conn,
    *,
    signal_id: int,
    row,
    exit_reason: str,
    exit_price: float,
    realized_pnl_pct: float,
) -> None:
    row_data = dict(row)
    realized_rr = _calc_realized_rr(row_data.get("entry_price"), row_data.get("sl_price"), exit_price)
    tp_hit = bool(row_data.get("tp1_hit_at")) or exit_reason == "TP1_HIT"
    timeout = exit_reason == "TIME_STOP"
    await conn.execute(
        """
        INSERT INTO trade_outcomes (
            signal_id, plan_id, exit_reason, exit_price,
            realized_rr_gross, realized_rr_net, realized_pnl,
            tp_hit_before_sl_flag, tp_reached_within_horizon_flag,
            timeout_flag, touch_mode, execution_quality_flag
        ) VALUES (
            $1,
            (SELECT id FROM trade_plans WHERE signal_id = $1 ORDER BY variant_rank ASC, id ASC LIMIT 1),
            $2, $3, $4, $5, NULL, $6, $7, $8, 'close_signal', NULL
        )
        """,
        signal_id,
        exit_reason,
        _opt_int(exit_price),
        _opt_num(realized_rr),
        _opt_num(realized_rr),
        tp_hit,
        tp_hit,
        timeout,
    )


async def create_shadow_trade(
    pool,
    *,
    signal_id: int,
    payload: dict,
    entry_price: float,
    tp1_price: Optional[float],
    sl_price: Optional[float],
    tp2_price: Optional[float] = None,
    data_quality: Optional[str] = "OK",
    data_quality_detail: Optional[dict] = None,
) -> bool:
    if not signal_id:
        return False
    entry = _opt_int(entry_price)
    if not entry or entry <= 0:
        logger.warning("[DBWriter] create_shadow_trade skipped: invalid entry signal_id=%s entry=%s", signal_id, entry_price)
        return False

    payload = dict(payload or {})
    now_utc = datetime.now(timezone.utc)
    signal_time = (
        _parse_utc_dt(payload.get("signal_time"))
        or _parse_utc_dt(payload.get("created_at"))
        or _parse_utc_dt(payload.get("timestamp"))
        or now_utc
    )
    latency_ms = max(0, int((now_utc - signal_time).total_seconds() * 1000))
    detail = data_quality_detail or {
        "rr_ratio": _opt_num(payload.get("rr_ratio")),
        "raw_rr": _opt_num(payload.get("raw_rr")),
        "effective_rr": _opt_num(payload.get("effective_rr")),
        "signal_quality_bucket": payload.get("signal_quality_bucket"),
        "tp_policy_version": payload.get("tp_policy_version"),
        "sl_policy_version": payload.get("sl_policy_version"),
        "exit_policy_version": payload.get("exit_policy_version"),
    }
    try:
        await pool.execute(
            """
            INSERT INTO shadow_trades (
                signal_id, strategy, stk_cd, stk_nm,
                entry_price, tp1_price, tp2_price, sl_price,
                signal_time, opened_at, status,
                max_favorable_price, max_adverse_price, last_price,
                latency_ms, data_quality, data_quality_detail
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, NOW(), 'OPEN',
                $5, $5, $5,
                $10, $11, $12::jsonb
            )
            ON CONFLICT (signal_id) DO UPDATE SET
                strategy = EXCLUDED.strategy,
                stk_cd = COALESCE(EXCLUDED.stk_cd, shadow_trades.stk_cd),
                stk_nm = COALESCE(EXCLUDED.stk_nm, shadow_trades.stk_nm),
                entry_price = EXCLUDED.entry_price,
                tp1_price = EXCLUDED.tp1_price,
                tp2_price = EXCLUDED.tp2_price,
                sl_price = EXCLUDED.sl_price,
                signal_time = EXCLUDED.signal_time,
                status = CASE WHEN shadow_trades.status = 'CLOSED' THEN shadow_trades.status ELSE 'OPEN' END,
                last_price = EXCLUDED.last_price,
                latency_ms = COALESCE(shadow_trades.latency_ms, EXCLUDED.latency_ms),
                data_quality = COALESCE(EXCLUDED.data_quality, shadow_trades.data_quality),
                data_quality_detail = shadow_trades.data_quality_detail || EXCLUDED.data_quality_detail,
                updated_at = NOW()
            """,
            signal_id,
            _clip_str(payload.get("strategy") or "", 30) or "UNKNOWN",
            normalize_stock_code(payload.get("stk_cd", "")),
            _clip_str(payload.get("stk_nm"), 100),
            entry,
            _opt_int(tp1_price),
            _opt_int(tp2_price),
            _opt_int(sl_price),
            signal_time,
            latency_ms,
            _clip_str(data_quality, 20),
            json.dumps(detail, ensure_ascii=False, default=str),
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] create_shadow_trade error signal_id=%s: %s", signal_id, e)
        return False


async def update_shadow_trade_mark(
    pool,
    *,
    signal_id: int,
    cur_prc: float,
    data_quality: Optional[str] = "OK",
    data_quality_detail: Optional[dict] = None,
) -> bool:
    price = _opt_int(cur_prc)
    if not signal_id or not price or price <= 0:
        return False
    try:
        await pool.execute(
            """
            UPDATE shadow_trades
            SET last_price = $2,
                max_favorable_price = CASE
                    WHEN max_favorable_price IS NULL OR $2 > max_favorable_price THEN $2
                    ELSE max_favorable_price
                END,
                max_adverse_price = CASE
                    WHEN max_adverse_price IS NULL OR $2 < max_adverse_price THEN $2
                    ELSE max_adverse_price
                END,
                max_favorable_excursion = GREATEST(
                    COALESCE(max_favorable_excursion, 0),
                    ROUND((($2 - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 4)
                ),
                max_adverse_excursion = LEAST(
                    COALESCE(max_adverse_excursion, 0),
                    ROUND((($2 - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 4)
                ),
                data_quality = COALESCE($3, data_quality),
                data_quality_detail = CASE
                    WHEN $4::jsonb IS NULL THEN data_quality_detail
                    ELSE data_quality_detail || $4::jsonb
                END,
                updated_at = NOW()
            WHERE signal_id = $1
              AND status = 'OPEN'
              AND entry_price > 0
            """,
            signal_id,
            price,
            _clip_str(data_quality, 20),
            json.dumps(data_quality_detail, ensure_ascii=False, default=str) if data_quality_detail else None,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] update_shadow_trade_mark error signal_id=%s: %s", signal_id, e)
        return False


async def close_shadow_trade(
    conn_or_pool,
    *,
    signal_id: int,
    exit_reason: str,
    exit_price: float,
    realized_pnl_pct: float,
    data_quality: Optional[str] = None,
    data_quality_detail: Optional[dict] = None,
) -> bool:
    price = _opt_int(exit_price)
    if not signal_id or not price:
        return False
    result = _shadow_result(realized_pnl_pct, exit_reason)
    detail = json.dumps(data_quality_detail, ensure_ascii=False, default=str) if data_quality_detail else None
    try:
        await conn_or_pool.execute(
            """
            UPDATE shadow_trades
            SET status = 'CLOSED',
                closed_at = COALESCE(closed_at, NOW()),
                last_price = $2,
                result = $3,
                realized_pnl_simulated = $4,
                exit_reason = $5,
                data_quality = COALESCE($6, data_quality),
                data_quality_detail = CASE
                    WHEN $7::jsonb IS NULL THEN data_quality_detail
                    ELSE data_quality_detail || $7::jsonb
                END,
                updated_at = NOW()
            WHERE signal_id = $1
              AND status = 'OPEN'
            """,
            signal_id,
            price,
            result,
            _opt_num(realized_pnl_pct),
            _clip_str(exit_reason, 40),
            _clip_str(data_quality, 20),
            detail,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] close_shadow_trade error signal_id=%s: %s", signal_id, e)
        return False


async def update_signal_score(
    pool,
    signal_id: int,
    *,
    rule_score: float,
    ai_score: float,
    rr_ratio: Optional[float],
    action: str,
    confidence: str,
    ai_reason: str,
    tp_method: Optional[str],
    sl_method: Optional[str],
    skip_entry: bool,
    ma5: Optional[float] = None,
    ma20: Optional[float] = None,
    ma60: Optional[float] = None,
    rsi14: Optional[float] = None,
    bb_upper: Optional[float] = None,
    bb_lower: Optional[float] = None,
    atr: Optional[float] = None,
    market_flu_rt: Optional[float] = None,
    news_sentiment: Optional[str] = None,
    news_ctrl: Optional[str] = None,
    raw_rr: Optional[float] = None,
    single_tp_rr: Optional[float] = None,
    effective_rr: Optional[float] = None,
    min_rr_ratio: Optional[float] = None,
    rr_skip_reason: Optional[str] = None,
    stop_max_pct: Optional[float] = None,
    tp_policy_version: Optional[str] = None,
    sl_policy_version: Optional[str] = None,
    exit_policy_version: Optional[str] = None,
    allow_overnight: Optional[bool] = None,
    allow_reentry: Optional[bool] = None,
    time_stop_deadline_at: Optional[datetime] = None,
) -> bool:
    if not signal_id:
        return False
    try:
        now = datetime.now(timezone.utc)
        await pool.execute(
            """
            UPDATE trading_signals SET
                rule_score       = $2,
                ai_score         = $3,
                rr_ratio         = $4,
                action           = $5,
                confidence       = $6,
                ai_reason        = $7,
                tp_method        = $8,
                sl_method        = $9,
                skip_entry       = $10,
                scored_at        = $11,
                ma5_at_signal    = $12,
                ma20_at_signal   = $13,
                ma60_at_signal   = $14,
                rsi14_at_signal  = $15,
                bb_upper_at_sig  = $16,
                bb_lower_at_sig  = $17,
                atr_at_signal    = $18,
                market_flu_rt    = $19,
                news_sentiment   = $20,
                news_ctrl        = $21,
                raw_rr           = COALESCE($22, raw_rr),
                single_tp_rr     = COALESCE($23, single_tp_rr),
                effective_rr     = COALESCE($24, effective_rr),
                min_rr_ratio     = COALESCE($25, min_rr_ratio),
                rr_skip_reason   = COALESCE($26, rr_skip_reason),
                stop_max_pct     = COALESCE($27, stop_max_pct),
                tp_policy_version = COALESCE($28, tp_policy_version),
                sl_policy_version = COALESCE($29, sl_policy_version),
                exit_policy_version = COALESCE($30, exit_policy_version),
                allow_overnight  = COALESCE($31, allow_overnight),
                allow_reentry    = COALESCE($32, allow_reentry),
                time_stop_deadline_at = COALESCE($33, time_stop_deadline_at)
            WHERE id = $1
            """,
            signal_id,
            round(rule_score, 2),
            round(ai_score, 2),
            round(rr_ratio, 2) if rr_ratio is not None else None,
            action,
            confidence,
            ai_reason,
            tp_method,
            sl_method,
            skip_entry,
            now,
            int(ma5) if ma5 is not None else None,
            int(ma20) if ma20 is not None else None,
            int(ma60) if ma60 is not None else None,
            round(rsi14, 2) if rsi14 is not None else None,
            int(bb_upper) if bb_upper is not None else None,
            int(bb_lower) if bb_lower is not None else None,
            round(atr, 2) if atr is not None else None,
            round(market_flu_rt, 3) if market_flu_rt is not None else None,
            news_sentiment,
            news_ctrl,
            _opt_num(raw_rr),
            _opt_num(single_tp_rr),
            _opt_num(effective_rr),
            _opt_num(min_rr_ratio),
            rr_skip_reason,
            _opt_num(stop_max_pct),
            tp_policy_version,
            sl_policy_version,
            exit_policy_version,
            _opt_bool(allow_overnight),
            _opt_bool(allow_reentry),
            time_stop_deadline_at,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] update_signal_score error signal_id=%s: %s", signal_id, e)
        return False


async def insert_python_signal(
    pool,
    signal: dict,
    *,
    action: str,
    confidence: str,
    rule_score: float,
    ai_score: float,
    ai_reason: str,
    skip_entry: bool,
) -> Optional[int]:
    signal = dict(signal)
    signal["stk_cd"] = normalize_stock_code(signal.get("stk_cd", ""))
    if not signal["stk_cd"]:
        logger.error("[DBWriter] insert_python_signal aborted: stk_cd is empty (strategy=%s)", signal.get("strategy"))
        return None
    if not signal.get("strategy"):
        logger.error("[DBWriter] insert_python_signal aborted: strategy is empty (stk_cd=%s)", signal["stk_cd"])
        return None
    now = datetime.now(timezone.utc)
    status = "SENT" if action == "ENTER" else "CANCELLED"
    time_stop_deadline_at = _resolve_time_stop_deadline_utc(
        created_at_utc=now.replace(tzinfo=timezone.utc),
        time_stop_type=signal.get("time_stop_type"),
        time_stop_minutes=signal.get("time_stop_minutes"),
        time_stop_session=signal.get("time_stop_session"),
    )
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO trading_signals (
                        stk_cd, strategy, signal_status, action, confidence,
                        rule_score, ai_score, signal_score, ai_reason, skip_entry,
                        entry_price, target_price, stop_price,
                        tp1_price, tp2_price, sl_price,
                        tp_method, sl_method, rr_ratio,
                        raw_rr, single_tp_rr, effective_rr, min_rr_ratio, rr_skip_reason, stop_max_pct,
                        gap_pct, vol_ratio, cntr_strength, bid_ratio, pullback_pct,
                        entry_type, theme_name, market_type,
                        trailing_pct, trailing_activation, trailing_basis,
                        strategy_version, time_stop_type, time_stop_minutes, time_stop_session,
                        tp_policy_version, sl_policy_version, exit_policy_version,
                        allow_overnight, allow_reentry, time_stop_deadline_at,
                        created_at, scored_at,
                        buy_zone_low, buy_zone_high, buy_zone_anchors, buy_zone_strength,
                        sell_zone1_low, sell_zone1_high, zone_rr
                    ) VALUES (
                        $1,$2,$3,$4,$5,
                        $6,$7,$8,$9,$10,
                        $11,$12,$13,
                        $14,$15,$16,
                        $17,$18,$19,
                        $20,$21,$22,$23,$24,$25,
                        $26,$27,$28,$29,$30,
                        $31,$32,$33,
                        $34,$35,$36,
                        $37,$38,$39,$40,
                        $41,$42,$43,
                        $44,$45,$46,$47,$48,
                        $49,$50,$51,$52,
                        $53,$54,$55
                    ) RETURNING id
                    """,
                    signal.get("stk_cd", ""),
                    signal.get("strategy", ""),
                    status,
                    action,
                    confidence,
                    round(rule_score, 2),
                    round(ai_score, 2),
                    round(ai_score, 2),
                    ai_reason,
                    skip_entry,
                    _sf(signal.get("entry_price") or signal.get("cur_prc")),
                    _sf(signal.get("target_price") or signal.get("tp1_price")),
                    _sf(signal.get("stop_price") or signal.get("sl_price")),
                    _sf(signal.get("tp1_price")),
                    _sf(signal.get("tp2_price")),
                    _sf(signal.get("sl_price")),
                    _clip_str(signal.get("tp_method"), 200),
                    _clip_str(signal.get("sl_method"), 200),
                    _sf(signal.get("rr_ratio")),
                    _sf(signal.get("raw_rr")),
                    _sf(signal.get("single_tp_rr")),
                    _sf(signal.get("effective_rr")),
                    _sf(signal.get("min_rr_ratio")),
                    signal.get("rr_skip_reason"),
                    _sf(signal.get("stop_max_pct")),
                    _sf(signal.get("gap_pct")),
                    _sf(signal.get("vol_ratio")),
                    _sf(signal.get("cntr_strength") or signal.get("cntr_str")),
                    _sf(signal.get("bid_ratio")),
                    _sf(signal.get("pullback_pct")),
                    signal.get("entry_type"),
                    signal.get("theme_name"),
                    signal.get("market_type"),
                    _sf(signal.get("trailing_pct")),
                    _sf(signal.get("trailing_activation")),
                    signal.get("trailing_basis"),
                    signal.get("strategy_version"),
                    signal.get("time_stop_type"),
                    _opt_int(signal.get("time_stop_minutes")),
                    signal.get("time_stop_session"),
                    signal.get("tp_policy_version"),
                    signal.get("sl_policy_version"),
                    signal.get("exit_policy_version"),
                    _opt_bool(signal.get("allow_overnight")),
                    _opt_bool(signal.get("allow_reentry")),
                    time_stop_deadline_at,
                    now,
                    now,
                    # zone 필드 ($49~$55)
                    *_zone_insert_params(signal),
                )
                if row:
                    signal_id = row["id"]
                    await _upsert_primary_trade_plan(
                        conn,
                        signal_id=signal_id,
                        strategy_code=signal.get("strategy"),
                        strategy_version=signal.get("strategy_version"),
                        entry_price=signal.get("entry_price") or signal.get("cur_prc"),
                        tp_price=signal.get("target_price") or signal.get("tp1_price"),
                        sl_price=signal.get("stop_price") or signal.get("sl_price"),
                        planned_rr=signal.get("single_tp_rr") or signal.get("raw_rr") or signal.get("rr_ratio"),
                        effective_rr=signal.get("effective_rr") or signal.get("rr_ratio"),
                        tp_model=signal.get("tp_method"),
                        sl_model=signal.get("sl_method"),
                        time_stop_type=signal.get("time_stop_type"),
                        time_stop_minutes=signal.get("time_stop_minutes"),
                        time_stop_session=signal.get("time_stop_session"),
                        trailing_basis=signal.get("trailing_basis"),
                        trailing_pct=signal.get("trailing_pct"),
                    )
                    await _insert_position_state_event(
                        conn,
                        signal_id=signal_id,
                        event_type="SIGNAL_CREATED",
                        position_status="PENDING" if action == "ENTER" else "CLOSED",
                        payload={
                            "action": action,
                            "skip_entry": bool(skip_entry),
                            "rr_ratio": _sf(signal.get("rr_ratio")),
                            "effective_rr": _sf(signal.get("effective_rr")),
                        },
                    )
                return row["id"] if row else None
    except asyncpg.ForeignKeyViolationError as e:
        logger.warning(
            "[DBWriter] insert_python_signal FK violation (stk_cd not in stock_master) [%s %s]: %s",
            signal.get("stk_cd"), signal.get("strategy"), e,
        )
        return None
    except Exception as e:
        logger.error("[DBWriter] insert_python_signal error [%s %s]: %s", signal.get("stk_cd"), signal.get("strategy"), e)
        return None


async def insert_score_components(
    pool,
    signal_id: int,
    strategy: str,
    components: dict,
    total_score: float,
    threshold: float,
) -> bool:
    if not signal_id:
        return False
    try:
        sg = components.get("strategy_specific", {})
        await pool.execute(
            """
            INSERT INTO signal_score_components
                (signal_id, strategy,
                 base_score, time_bonus, vol_score, momentum_score,
                 technical_score, demand_score, risk_penalty,
                 strategy_components,
                 total_score, threshold_used, passed_threshold,
                 computed_at)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13, NOW())
            ON CONFLICT (signal_id) DO UPDATE SET
                total_score      = EXCLUDED.total_score,
                passed_threshold = EXCLUDED.passed_threshold,
                computed_at      = NOW()
            """,
            signal_id,
            strategy,
            _opt_num(components.get("base_score")),
            _opt_num(components.get("time_bonus")),
            _opt_num(components.get("vol_score")),
            _opt_num(components.get("momentum_score")),
            _opt_num(components.get("technical_score")),
            _opt_num(components.get("demand_score")),
            _opt_num(components.get("risk_penalty")),
            json.dumps(sg, ensure_ascii=False) if sg else None,
            round(total_score, 2),
            round(threshold, 2),
            total_score >= threshold,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] insert_score_components error signal_id=%s: %s", signal_id, e)
        return False


async def record_overnight_eval(
    pool,
    signal_id: int,
    verdict: str,
    overnight_score: float,
) -> bool:
    if not signal_id:
        return False
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, signal_id)
                if not row or not _is_active_signal(row["signal_status"], row["exit_type"]):
                    return False
                await conn.execute(
                    """
                    UPDATE trading_signals
                    SET signal_status = CASE WHEN $2 = 'HOLD' THEN 'OVERNIGHT_HOLD' ELSE signal_status END,
                        position_status = CASE WHEN $2 = 'HOLD' THEN 'OVERNIGHT' ELSE position_status END,
                        overnight_verdict = $2,
                        overnight_score = $3,
                        is_overnight = CASE WHEN $2 = 'HOLD' THEN TRUE ELSE FALSE END
                    WHERE id = $1
                    """,
                    signal_id,
                    verdict,
                    round(overnight_score, 2),
                )
                await _insert_position_state_event(
                    conn,
                    signal_id=signal_id,
                    event_type="OVERNIGHT_EVAL",
                    position_status="OVERNIGHT" if verdict == "HOLD" else row["position_status"],
                    payload={"verdict": verdict, "overnight_score": round(overnight_score, 2)},
                )
        return True
    except Exception as e:
        logger.error("[DBWriter] record_overnight_eval error signal_id=%s: %s", signal_id, e)
        return False


async def insert_overnight_eval(
    pool,
    signal_id: int,
    position_id: Optional[int],
    stk_cd: str,
    strategy: str,
    verdict: str,
    java_overnight_score: Optional[float],
    final_score: float,
    confidence: str,
    reason: str,
    *,
    pnl_pct: Optional[float] = None,
    flu_rt: Optional[float] = None,
    cntr_strength: Optional[float] = None,
    rsi14: Optional[float] = None,
    ma_alignment: Optional[str] = None,
    bid_ratio: Optional[float] = None,
    entry_price: Optional[float] = None,
    cur_price: Optional[float] = None,
    score_components: Optional[dict] = None,
) -> bool:
    if not signal_id:
        return False
    try:
        sc_json = json.dumps(score_components) if score_components else None
        await pool.execute(
            """
            INSERT INTO overnight_evaluations
                (signal_id, position_id, stk_cd, strategy,
                 java_overnight_score, verdict, final_score, confidence, reason,
                 pnl_pct, flu_rt, cntr_strength, rsi14,
                 ma_alignment, bid_ratio, entry_price, cur_prc_at_eval,
                 score_components, evaluated_at)
            VALUES
                ($1,  $2,  $3,  $4,
                 $5,  $6,  $7,  $8,  $9,
                 $10, $11, $12, $13,
                 $14, $15, $16, $17,
                 $18::jsonb, NOW())
            """,
            signal_id,
            position_id,
            stk_cd,
            strategy,
            round(java_overnight_score, 2) if java_overnight_score is not None else None,
            verdict,
            round(final_score, 2),
            confidence,
            reason,
            round(pnl_pct, 4) if pnl_pct is not None else None,
            round(flu_rt, 4) if flu_rt is not None else None,
            round(cntr_strength, 2) if cntr_strength is not None else None,
            round(rsi14, 2) if rsi14 is not None else None,
            ma_alignment,
            round(bid_ratio, 3) if bid_ratio is not None else None,
            int(entry_price) if entry_price is not None else None,
            int(cur_price) if cur_price is not None else None,
            sc_json,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] insert_overnight_eval error signal_id=%s: %s", signal_id, e)
        return False


async def upsert_daily_indicators(pool, stk_cd: str, date_str: str, ind: dict) -> bool:
    try:
        await pool.execute(
            """
            INSERT INTO daily_indicators
                (date, stk_cd,
                 close_price, open_price, high_price, low_price, volume, volume_ratio,
                 ma5, ma20, ma60, ma120, vol_ma20,
                 rsi14, stoch_k, stoch_d,
                 bb_upper, bb_mid, bb_lower, bb_width_pct, pct_b,
                 atr14, atr_pct,
                 macd_line, macd_signal, macd_hist,
                 is_bullish_aligned, is_above_ma20, is_new_high_52w, golden_cross_today,
                 swing_high_20d, swing_low_20d, swing_high_60d, swing_low_60d,
                 computed_at)
            VALUES
                ($1, $2,
                 $3,  $4,  $5,  $6,  $7,  $8,
                 $9,  $10, $11, $12, $13,
                 $14, $15, $16,
                 $17, $18, $19, $20, $21,
                 $22, $23,
                 $24, $25, $26,
                 $27, $28, $29, $30,
                 $31, $32, $33, $34,
                 NOW())
            ON CONFLICT (date, stk_cd) DO UPDATE SET
                close_price        = EXCLUDED.close_price,
                ma5                = EXCLUDED.ma5,
                ma20               = EXCLUDED.ma20,
                ma60               = EXCLUDED.ma60,
                rsi14              = EXCLUDED.rsi14,
                bb_upper           = EXCLUDED.bb_upper,
                bb_lower           = EXCLUDED.bb_lower,
                atr14              = EXCLUDED.atr14,
                is_bullish_aligned = EXCLUDED.is_bullish_aligned,
                golden_cross_today = EXCLUDED.golden_cross_today,
                swing_high_20d     = EXCLUDED.swing_high_20d,
                swing_low_20d      = EXCLUDED.swing_low_20d,
                computed_at        = NOW()
            """,
            date_str, stk_cd,
            _opt_int(ind.get("close_price")), _opt_int(ind.get("open_price")),
            _opt_int(ind.get("high_price")), _opt_int(ind.get("low_price")),
            ind.get("volume"), _opt_num(ind.get("volume_ratio")),
            _opt_int(ind.get("ma5")), _opt_int(ind.get("ma20")),
            _opt_int(ind.get("ma60")), _opt_int(ind.get("ma120")),
            ind.get("vol_ma20"),
            _opt_num(ind.get("rsi14")), _opt_num(ind.get("stoch_k")), _opt_num(ind.get("stoch_d")),
            _opt_int(ind.get("bb_upper")), _opt_int(ind.get("bb_mid")), _opt_int(ind.get("bb_lower")),
            _opt_num(ind.get("bb_width_pct")), _opt_num(ind.get("pct_b")),
            _opt_num(ind.get("atr14")), _opt_num(ind.get("atr_pct")),
            _opt_num(ind.get("macd_line")), _opt_num(ind.get("macd_signal")), _opt_num(ind.get("macd_hist")),
            ind.get("is_bullish_aligned"), ind.get("is_above_ma20"),
            ind.get("is_new_high_52w"), ind.get("golden_cross_today"),
            _opt_int(ind.get("swing_high_20d")), _opt_int(ind.get("swing_low_20d")),
            _opt_int(ind.get("swing_high_60d")), _opt_int(ind.get("swing_low_60d")),
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] upsert_daily_indicators error %s %s: %s", stk_cd, date_str, e)
        return False


async def confirm_open_position(
    pool,
    signal_id: int,
    *,
    ai_score: Optional[float],
    tp1_price: Optional[float] = None,
    tp2_price: Optional[float] = None,
    sl_price: Optional[float] = None,
    rr_ratio: Optional[float] = None,
    trailing_pct: Optional[float] = None,
    trailing_activation: Optional[float] = None,
    trailing_basis: Optional[str] = None,
    strategy_version: Optional[str] = None,
    time_stop_type: Optional[str] = None,
    time_stop_minutes: Optional[int] = None,
    time_stop_session: Optional[str] = None,
    raw_rr: Optional[float] = None,
    single_tp_rr: Optional[float] = None,
    effective_rr: Optional[float] = None,
    min_rr_ratio: Optional[float] = None,
    rr_skip_reason: Optional[str] = None,
    stop_max_pct: Optional[float] = None,
    tp_policy_version: Optional[str] = None,
    sl_policy_version: Optional[str] = None,
    exit_policy_version: Optional[str] = None,
    allow_overnight: Optional[bool] = None,
    allow_reentry: Optional[bool] = None,
) -> bool:
    if not signal_id:
        return False
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, signal_id)
                if not row or row["signal_status"] in TERMINAL_SIGNAL_STATUSES:
                    return False

                base_ts = row["entry_at"] or row["executed_at"] or row["created_at"] or datetime.now(timezone.utc)
                deadline_at = _resolve_time_stop_deadline_utc(
                    created_at_utc=base_ts if getattr(base_ts, "tzinfo", None) else base_ts.replace(tzinfo=timezone.utc),
                    time_stop_type=time_stop_type or row["time_stop_type"],
                    time_stop_minutes=time_stop_minutes if time_stop_minutes is not None else row["time_stop_minutes"],
                    time_stop_session=time_stop_session or row["time_stop_session"],
                )
                await conn.execute(
                    """
                    UPDATE trading_signals
                    SET action = 'ENTER',
                        signal_status = CASE
                            WHEN signal_status IN ('PENDING', 'CANCELLED') OR signal_status IS NULL THEN 'SENT'
                            ELSE signal_status
                        END,
                        position_status = 'ACTIVE',
                        ai_score = COALESCE($2, ai_score),
                        tp1_price = COALESCE($3::NUMERIC, tp1_price),
                        tp2_price = COALESCE($4::NUMERIC, tp2_price),
                        sl_price = COALESCE($5::NUMERIC, sl_price),
                        rr_ratio = COALESCE($6::NUMERIC, rr_ratio),
                        entry_at = COALESCE(entry_at, executed_at, created_at, NOW()),
                        monitor_enabled = TRUE,
                        is_overnight = FALSE,
                        overnight_verdict = NULL,
                        overnight_score = NULL,
                        tp1_hit_at = NULL,
                        peak_price = NULL,
                        trailing_pct = COALESCE($7::NUMERIC, trailing_pct),
                        trailing_activation = COALESCE($8::NUMERIC, trailing_activation),
                        trailing_basis = COALESCE($9, trailing_basis),
                        strategy_version = COALESCE($10, strategy_version),
                        time_stop_type = COALESCE($11, time_stop_type),
                        time_stop_minutes = COALESCE($12, time_stop_minutes),
                        time_stop_session = COALESCE($13, time_stop_session),
                        raw_rr = COALESCE($14::NUMERIC, raw_rr),
                        single_tp_rr = COALESCE($15::NUMERIC, single_tp_rr),
                        effective_rr = COALESCE($16::NUMERIC, effective_rr),
                        min_rr_ratio = COALESCE($17::NUMERIC, min_rr_ratio),
                        rr_skip_reason = COALESCE($18, rr_skip_reason),
                        stop_max_pct = COALESCE($19::NUMERIC, stop_max_pct),
                        tp_policy_version = COALESCE($20, tp_policy_version),
                        sl_policy_version = COALESCE($21, sl_policy_version),
                        exit_policy_version = COALESCE($22, exit_policy_version),
                        allow_overnight = COALESCE($23, allow_overnight),
                        allow_reentry = COALESCE($24, allow_reentry),
                        time_stop_deadline_at = COALESCE($25, time_stop_deadline_at)
                    WHERE id = $1
                    """,
                    signal_id,
                    round(ai_score, 2) if ai_score is not None else None,
                    int(tp1_price) if tp1_price else None,
                    int(tp2_price) if tp2_price else None,
                    int(sl_price) if sl_price else None,
                    round(rr_ratio, 2) if rr_ratio is not None else None,
                    round(trailing_pct, 2) if trailing_pct is not None else None,
                    int(trailing_activation) if trailing_activation is not None else None,
                    trailing_basis,
                    strategy_version,
                    time_stop_type,
                    int(time_stop_minutes) if time_stop_minutes is not None else None,
                    time_stop_session,
                    _opt_num(raw_rr),
                    _opt_num(single_tp_rr),
                    _opt_num(effective_rr),
                    _opt_num(min_rr_ratio),
                    rr_skip_reason,
                    _opt_num(stop_max_pct),
                    tp_policy_version,
                    sl_policy_version,
                    exit_policy_version,
                    _opt_bool(allow_overnight),
                    _opt_bool(allow_reentry),
                    deadline_at,
                )
                await _upsert_primary_trade_plan(
                    conn,
                    signal_id=signal_id,
                    strategy_code=row["strategy"],
                    strategy_version=strategy_version or row["strategy_version"],
                    entry_price=row["entry_price"],
                    tp_price=tp1_price or row["tp1_price"],
                    sl_price=sl_price or row["sl_price"],
                    planned_rr=single_tp_rr or raw_rr or rr_ratio or row["rr_ratio"],
                    effective_rr=effective_rr or rr_ratio or row["rr_ratio"],
                    tp_model=row["tp_method"],
                    sl_model=row["sl_method"],
                    time_stop_type=time_stop_type or row["time_stop_type"],
                    time_stop_minutes=time_stop_minutes if time_stop_minutes is not None else row["time_stop_minutes"],
                    time_stop_session=time_stop_session or row["time_stop_session"],
                    trailing_basis=trailing_basis or row["trailing_basis"],
                    trailing_pct=trailing_pct if trailing_pct is not None else row["trailing_pct"],
                )
                await _insert_position_state_event(
                    conn,
                    signal_id=signal_id,
                    event_type="POSITION_OPENED",
                    position_status="ACTIVE",
                    payload={
                        "rr_ratio": round(rr_ratio, 3) if rr_ratio is not None else None,
                        "effective_rr": _opt_num(effective_rr or rr_ratio),
                        "time_stop_deadline_at": deadline_at,
                    },
                )
        return True
    except Exception as e:
        logger.error("[DBWriter] confirm_open_position error signal_id=%s: %s", signal_id, e)
        return False


async def cancel_open_position_by_signal(pool, signal_id: int) -> bool:
    if not signal_id:
        return False
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, signal_id)
                await conn.execute(
                    """
                    UPDATE trading_signals
                    SET action = 'CANCEL',
                        signal_status = 'CANCELLED',
                        position_status = 'CLOSED',
                        monitor_enabled = FALSE,
                        is_overnight = FALSE,
                        overnight_verdict = NULL,
                        overnight_score = NULL
                    WHERE id = $1
                    """,
                    signal_id,
                )
                if row:
                    await _insert_position_state_event(
                        conn,
                        signal_id=signal_id,
                        event_type="SIGNAL_CANCELLED",
                        position_status="CLOSED",
                        payload={"previous_status": row["signal_status"]},
                    )
        return True
    except Exception as e:
        logger.error("[DBWriter] cancel_open_position_by_signal error signal_id=%s: %s", signal_id, e)
        return False


async def insert_ai_cancel_signal(
    pool,
    *,
    signal_id: Optional[int],
    stk_cd: str,
    strategy: str,
    ai_score: Optional[float],
    confidence: Optional[str],
    reason: Optional[str],
    cancel_reason: Optional[str],
    raw_payload: Optional[dict] = None,
) -> bool:
    try:
        await pool.execute(
            """
            INSERT INTO ai_cancel_signal (
                signal_id, stk_cd, strategy, ai_score, confidence,
                reason, cancel_reason, raw_payload, created_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8::jsonb, NOW()
            )
            """,
            signal_id,
            normalize_stock_code(stk_cd),
            strategy,
            round(ai_score, 2) if ai_score is not None else None,
            confidence,
            reason,
            cancel_reason,
            json.dumps(raw_payload, ensure_ascii=False, default=str) if raw_payload is not None else None,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] insert_ai_cancel_signal error signal_id=%s: %s", signal_id, e)
        return False


async def insert_rule_cancel_signal(
    pool,
    *,
    signal_id: Optional[int],
    stk_cd: str,
    strategy: str,
    rule_score: Optional[float],
    cancel_type: str,
    reason: Optional[str],
    raw_payload: Optional[dict] = None,
) -> bool:
    try:
        await pool.execute(
            """
            INSERT INTO rule_cancel_signal (
                signal_id, stk_cd, strategy, rule_score, cancel_type,
                reason, raw_payload, created_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7::jsonb, NOW()
            )
            """,
            signal_id,
            normalize_stock_code(stk_cd),
            strategy,
            round(rule_score, 2) if rule_score is not None else None,
            cancel_type,
            reason,
            json.dumps(raw_payload, ensure_ascii=False, default=str) if raw_payload is not None else None,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] insert_rule_cancel_signal error signal_id=%s: %s", signal_id, e)
        return False




async def mark_tp1_hit(pool, position_id: int, cur_prc: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, position_id)
                if not row or not _is_active_signal(row["signal_status"], row["exit_type"]):
                    return False
                if str(row["position_status"] or "ACTIVE") != "ACTIVE":
                    return False
                await conn.execute(
                    """
                    UPDATE trading_signals
                    SET position_status = 'PARTIAL_TP',
                        tp1_hit_at = NOW(),
                        peak_price = $2
                    WHERE id = $1
                    """,
                    position_id,
                    int(cur_prc),
                )
                await _insert_position_state_event(
                    conn,
                    signal_id=position_id,
                    event_type="TP1_REACHED",
                    position_status="PARTIAL_TP",
                    peak_price=cur_prc,
                    trailing_stop_price=cur_prc,
                    payload={"tp1_price": _opt_int(row["tp1_price"]), "trigger_price": int(cur_prc)},
                )
        return True
    except Exception as e:
        logger.error("[DBWriter] mark_tp1_hit error position_id=%s: %s", position_id, e)
        return False


async def update_peak_price(pool, position_id: int, peak_price: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, position_id)
                if not row or not _is_active_signal(row["signal_status"], row["exit_type"]):
                    return False
                if str(row["position_status"] or "ACTIVE") not in {"ACTIVE", "PARTIAL_TP", "OVERNIGHT"}:
                    return False
                current_peak = _opt_int(row["peak_price"])
                if current_peak is not None and current_peak >= peak_price:
                    return True
                await conn.execute(
                    "UPDATE trading_signals SET peak_price = $2, trailing_stop_price = $3 WHERE id = $1",
                    position_id,
                    int(peak_price),
                    int(peak_price),
                )
                await _insert_position_state_event(
                    conn,
                    signal_id=position_id,
                    event_type="PEAK_UPDATED",
                    position_status=row["position_status"],
                    peak_price=peak_price,
                    trailing_stop_price=peak_price,
                    payload={"previous_peak": current_peak, "new_peak": int(peak_price)},
                )
        return True
    except Exception as e:
        logger.error("[DBWriter] update_peak_price error position_id=%s: %s", position_id, e)
        return False


async def close_open_position(
    pool,
    position_id: int,
    *,
    signal_id: int,
    exit_type: str,
    exit_price: int,
    realized_pnl_pct: float,
) -> bool:
    signal_status = "WIN" if realized_pnl_pct >= 0 else "LOSS"
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, signal_id)
                if not row or not _is_active_signal(row["signal_status"], row["exit_type"]):
                    return False
                await conn.execute(
                    """
                    UPDATE trading_signals SET
                        signal_status = $2,
                        exit_type = $3,
                        exit_price = $4,
                        exit_pnl_pct = $5,
                        exited_at = NOW(),
                        position_status = 'CLOSED',
                        monitor_enabled = FALSE
                    WHERE id = $1
                    """,
                    signal_id,
                    signal_status,
                    exit_type,
                    exit_price,
                    round(realized_pnl_pct, 4),
                )
                await _insert_trade_outcome(
                    conn,
                    signal_id=signal_id,
                    row=row,
                    exit_reason=exit_type,
                    exit_price=exit_price,
                    realized_pnl_pct=realized_pnl_pct,
                )
                await close_shadow_trade(
                    conn,
                    signal_id=signal_id,
                    exit_reason=exit_type,
                    exit_price=exit_price,
                    realized_pnl_pct=realized_pnl_pct,
                    data_quality_detail={"closed_by": "position_monitor"},
                )
                await _insert_position_state_event(
                    conn,
                    signal_id=signal_id,
                    event_type="POSITION_CLOSED",
                    position_status="CLOSED",
                    peak_price=dict(row).get("peak_price"),
                    trailing_stop_price=dict(row).get("peak_price"),
                    payload={
                        "exit_type": exit_type,
                        "exit_price": int(exit_price),
                        "realized_pnl_pct": round(realized_pnl_pct, 4),
                    },
                )
        return True
    except Exception as e:
        logger.error("[DBWriter] close_open_position error position_id=%s signal_id=%s: %s", position_id, signal_id, e)
        return False


async def insert_human_confirm_request(
    pool,
    payload: dict,
    *,
    rule_score: Optional[float],
    rr_ratio: Optional[float],
) -> Optional[dict]:
    try:
        payload = dict(payload)
        payload["stk_cd"] = normalize_stock_code(payload.get("stk_cd", ""))
        if not payload["stk_cd"]:
            logger.error("[DBWriter] insert_human_confirm_request aborted: stk_cd is empty (strategy=%s)", payload.get("strategy"))
            return None
        if not payload.get("strategy"):
            logger.error("[DBWriter] insert_human_confirm_request aborted: strategy is empty (stk_cd=%s)", payload["stk_cd"])
            return None
        requested_at = datetime.now(timezone.utc)
        expires_at = _next_trading_day_preopen_utc(requested_at)
        signal_id = payload.get("id")
        request_key = f"hc-{signal_id or payload.get('stk_cd', 'unk')}-{uuid4().hex[:8]}"
        row = await pool.fetchrow(
            """
            INSERT INTO human_confirm_requests (
                request_key, signal_id, stk_cd, stk_nm, strategy,
                rule_score, rr_ratio, status, payload,
                requested_at, expires_at, last_enqueued_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, 'PENDING', $8::jsonb,
                $9, $10, $9
            )
            RETURNING request_key, expires_at
            """,
            request_key,
            signal_id,
            payload.get("stk_cd", ""),
            payload.get("stk_nm"),
            payload.get("strategy", ""),
            round(rule_score, 2) if rule_score is not None else None,
            round(rr_ratio, 2) if rr_ratio is not None else None,
            json.dumps(payload, ensure_ascii=False, default=str),
            requested_at,
            expires_at,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBWriter] insert_human_confirm_request error [%s %s]: %s", payload.get("stk_cd"), payload.get("strategy"), e)
        return None


async def update_human_confirm_request_status(
    pool,
    request_key: str,
    *,
    status: str,
    decision_chat_id: Optional[int] = None,
    decision_message_id: Optional[int] = None,
    ai_score: Optional[float] = None,
    ai_action: Optional[str] = None,
    ai_confidence: Optional[str] = None,
    ai_reason: Optional[str] = None,
) -> bool:
    try:
        await pool.execute(
            """
            UPDATE human_confirm_requests
            SET status = $2,
                decided_at = CASE
                    WHEN $2 IN ('APPROVED', 'REJECTED', 'COMPLETED', 'FAILED')
                    THEN NOW()
                    ELSE decided_at
                END,
                decision_chat_id = COALESCE($3, decision_chat_id),
                decision_message_id = COALESCE($4, decision_message_id),
                ai_score = COALESCE($5, ai_score),
                ai_action = COALESCE($6, ai_action),
                ai_confidence = COALESCE($7, ai_confidence),
                ai_reason = COALESCE($8, ai_reason)
            WHERE request_key = $1
            """,
            request_key,
            status,
            decision_chat_id,
            decision_message_id,
            round(ai_score, 2) if ai_score is not None else None,
            ai_action,
            ai_confidence,
            ai_reason,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] update_human_confirm_request_status error request_key=%s: %s", request_key, e)
        return False


async def mark_human_confirm_request_sent(
    pool,
    request_key: str,
    *,
    decision_chat_id: Optional[int] = None,
    decision_message_id: Optional[int] = None,
) -> bool:
    try:
        await pool.execute(
            """
            UPDATE human_confirm_requests
            SET last_sent_at = NOW(),
                decision_chat_id = COALESCE($2, decision_chat_id),
                decision_message_id = COALESCE($3, decision_message_id)
            WHERE request_key = $1
            """,
            request_key,
            decision_chat_id,
            decision_message_id,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] mark_human_confirm_request_sent error request_key=%s: %s", request_key, e)
        return False
