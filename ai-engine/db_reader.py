"""
db_reader.py
Python ai-engine PostgreSQL read helpers (asyncpg based).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from position_lifecycle import ACTIVE_POSITION_STATES, ACTIVE_SIGNAL_STATUSES

logger = logging.getLogger(__name__)


def _is_active_signal(signal_status: Optional[str], exit_type: Optional[str]) -> bool:
    return (signal_status or "PENDING") in ACTIVE_SIGNAL_STATUSES and not exit_type


def _build_position_row(row) -> dict:
    data = dict(row)
    status = str(data.get("position_status") or "ACTIVE")
    if status not in ACTIVE_POSITION_STATES:
        status = "ACTIVE"
    data["status"] = status
    data["signal_id"] = data["id"]
    data["entry_at"] = data.get("entry_at") or data.get("executed_at") or data.get("created_at")
    data["monitor_enabled"] = True if data.get("monitor_enabled") is None else bool(data.get("monitor_enabled"))
    return data


async def get_daily_indicators(pool, stk_cd: str, target_date: Optional[date] = None) -> Optional[dict]:
    if target_date is None:
        target_date = date.today()
    try:
        row = await pool.fetchrow(
            "SELECT * FROM daily_indicators WHERE stk_cd = $1 AND date = $2",
            stk_cd,
            target_date,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_daily_indicators error %s: %s", stk_cd, e)
        return None


async def get_daily_indicators_range(pool, stk_cd: str, days: int = 20) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT * FROM daily_indicators
            WHERE stk_cd = $1 AND date >= $2
            ORDER BY date DESC
            LIMIT $3
            """,
            stk_cd,
            date.today() - timedelta(days=days + 5),
            days,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[DBReader] get_daily_indicators_range error %s: %s", stk_cd, e)
        return []


async def get_active_position(pool, stk_cd: str) -> Optional[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT id, stk_cd, stk_nm, strategy, market_type, entry_price, tp1_price, tp2_price, sl_price,
                   signal_status, exit_type, created_at, executed_at,
                   position_status, entry_at, tp1_hit_at, peak_price, trailing_pct, trailing_activation,
                   trailing_basis, strategy_version, time_stop_type, time_stop_minutes, time_stop_session,
                   monitor_enabled, is_overnight, overnight_verdict, overnight_score
            FROM trading_signals
            WHERE stk_cd = $1
              AND position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
              AND COALESCE(monitor_enabled, TRUE) = TRUE
            ORDER BY COALESCE(entry_at, executed_at, created_at) DESC
            """,
            stk_cd,
        )
        for row in rows:
            pos = _build_position_row(row)
            if _is_active_signal(row["signal_status"], row["exit_type"]) and pos["monitor_enabled"]:
                return pos
        return None
    except Exception as e:
        logger.error("[DBReader] get_active_position error %s: %s", stk_cd, e)
        return None


async def count_active_positions(pool) -> int:
    try:
        rows = await pool.fetch(
            """
            SELECT id, signal_status, exit_type, position_status, monitor_enabled
            FROM trading_signals
            WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
            """
        )
        count = 0
        for row in rows:
            if not _is_active_signal(row["signal_status"], row["exit_type"]):
                continue
            if row["position_status"] in ACTIVE_POSITION_STATES and (row["monitor_enabled"] is None or row["monitor_enabled"]):
                count += 1
        return count
    except Exception as e:
        logger.error("[DBReader] count_active_positions error: %s", e)
        return 0


async def get_portfolio_state(pool) -> dict:
    defaults = {
        "total_capital": 10_000_000,
        "max_position_pct": 10.0,
        "max_position_count": 5,
        "max_sector_pct": 30.0,
        "daily_loss_limit_pct": 3.0,
        "max_drawdown_pct": 10.0,
        "sl_mandatory": True,
        "min_rr_ratio": 1.0,
        "sizing_method": "FIXED_PCT",
    }
    try:
        row = await pool.fetchrow("SELECT * FROM portfolio_config WHERE id = 1")
        return dict(row) if row else defaults
    except Exception as e:
        logger.warning("[DBReader] get_portfolio_state error, using defaults: %s", e)
        return defaults


async def get_today_pnl(pool) -> Optional[dict]:
    try:
        row = await pool.fetchrow("SELECT * FROM daily_pnl WHERE date = $1", date.today())
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_today_pnl error: %s", e)
        return None


async def get_strategy_win_rate(pool, strategy: str, days: int = 20) -> Optional[float]:
    try:
        row = await pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE exit_type LIKE 'TP%') AS wins,
                COUNT(*) FILTER (WHERE exit_type IN ('SL_HIT', 'FORCE_CLOSE')) AS losses
            FROM trading_signals
            WHERE strategy = $1
              AND action = 'ENTER'
              AND exited_at >= NOW() - ($2 || ' days')::INTERVAL
              AND exit_type IS NOT NULL
            """,
            strategy,
            str(days),
        )
        if row:
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            total = wins + losses
            if total > 0:
                return round(wins / total * 100, 1)
        return None
    except Exception as e:
        logger.error("[DBReader] get_strategy_win_rate error %s: %s", strategy, e)
        return None
