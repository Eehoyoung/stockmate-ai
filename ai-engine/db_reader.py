"""
db_reader.py
Python ai-engine PostgreSQL read helpers (asyncpg based).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from position_lifecycle import ACTIVE_POSITION_STATES, ACTIVE_SIGNAL_STATUSES

logger = logging.getLogger(__name__)
KST    = timezone(timedelta(hours=9))


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
        target_date = datetime.now(KST).date()
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
            datetime.now(KST).date() - timedelta(days=days + 5),
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
        row = await pool.fetchrow("SELECT * FROM daily_pnl WHERE date = $1", datetime.now(KST).date())
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_today_pnl error: %s", e)
        return None


async def get_active_positions(pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT
                id, stk_cd, stk_nm, strategy, market_type,
                entry_price, tp1_price, tp2_price, sl_price,
                tp_method, sl_method, rr_ratio,
                signal_status, exit_type, created_at, executed_at,
                position_status, entry_at, tp1_hit_at, peak_price, trailing_pct, trailing_activation,
                trailing_basis, strategy_version, time_stop_type, time_stop_minutes, time_stop_session,
                monitor_enabled, is_overnight, overnight_verdict, overnight_score
            FROM trading_signals
            WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
              AND COALESCE(monitor_enabled, TRUE) = TRUE
            ORDER BY COALESCE(entry_at, executed_at, created_at)
            """
        )
        positions = []
        for row in rows:
            pos = _build_position_row(row)
            if pos["status"] in ACTIVE_POSITION_STATES and pos["monitor_enabled"]:
                positions.append(pos)
        return positions
    except Exception as e:
        logger.error("[DBReader] get_active_positions error: %s", e)
        return []


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


# ── 감사·이력 조회 ──

async def get_cancel_signals(pool, stk_cd: str, days: int = 7) -> list[dict]:
    """stk_cd 기준으로 최근 N일 AI/RULE 취소 신호를 UNION 조회한다."""
    try:
        rows = await pool.fetch(
            """
            SELECT 'AI' AS cancel_type, id, signal_id, stk_cd, strategy,
                   ai_score AS score, confidence, reason,
                   cancel_reason AS detail, created_at
            FROM ai_cancel_signal
            WHERE stk_cd = $1
              AND created_at >= NOW() - ($2 || ' days')::INTERVAL
            UNION ALL
            SELECT 'RULE' AS cancel_type, id, signal_id, stk_cd, strategy,
                   rule_score AS score, cancel_type AS confidence, reason,
                   NULL AS detail, created_at
            FROM rule_cancel_signal
            WHERE stk_cd = $1
              AND created_at >= NOW() - ($2 || ' days')::INTERVAL
            ORDER BY created_at DESC
            """,
            stk_cd,
            str(days),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[DBReader] get_cancel_signals error stk_cd=%s: %s", stk_cd, e)
        return []


async def get_position_state_events(pool, signal_id: int) -> list[dict]:
    """signal_id에 연결된 포지션 상태 이벤트 이력을 최신순으로 반환한다."""
    try:
        rows = await pool.fetch(
            """
            SELECT id, event_type, event_ts, position_status,
                   peak_price, trailing_stop_price, payload
            FROM position_state_events
            WHERE signal_id = $1
            ORDER BY event_ts DESC
            """,
            signal_id,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[DBReader] get_position_state_events error signal_id=%s: %s", signal_id, e)
        return []


async def get_trade_plan(pool, signal_id: int) -> Optional[dict]:
    """signal_id의 기본(variant_rank=1) 매매 플랜을 반환한다."""
    try:
        row = await pool.fetchrow(
            """
            SELECT id, strategy_code, strategy_version, plan_name,
                   tp_model, sl_model, tp_price, sl_price, tp_pct, sl_pct,
                   planned_rr, effective_rr, time_stop_type, time_stop_minutes,
                   time_stop_session, trailing_rule, partial_tp_rule,
                   planned_exit_priority, variant_rank, created_at
            FROM trade_plans
            WHERE signal_id = $1
            ORDER BY variant_rank ASC, id ASC
            LIMIT 1
            """,
            signal_id,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_trade_plan error signal_id=%s: %s", signal_id, e)
        return None


async def get_trade_outcome(pool, signal_id: int) -> Optional[dict]:
    """signal_id의 가장 최근 거래 결과를 반환한다."""
    try:
        row = await pool.fetchrow(
            """
            SELECT id, plan_id, exit_reason, exit_ts, exit_price, filled_qty,
                   realized_rr_gross, realized_rr_net, realized_pnl,
                   tp_hit_before_sl_flag, tp_reached_within_horizon_flag,
                   timeout_flag, touch_mode, execution_quality_flag
            FROM trade_outcomes
            WHERE signal_id = $1
            ORDER BY exit_ts DESC
            LIMIT 1
            """,
            signal_id,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_trade_outcome error signal_id=%s: %s", signal_id, e)
        return None


async def get_human_confirm_request(pool, signal_id: int) -> Optional[dict]:
    """signal_id에 연결된 가장 최근 사람 확인 요청 레코드를 반환한다."""
    try:
        row = await pool.fetchrow(
            """
            SELECT id, stk_cd, strategy, status, expires_at, created_at,
                   last_sent_at, requested_at, decided_at,
                   payload, ai_score, ai_action, ai_confidence, ai_reason
            FROM human_confirm_requests
            WHERE signal_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            signal_id,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_human_confirm_request error signal_id=%s: %s", signal_id, e)
        return None


async def get_recent_cancel_stats(pool, strategy: str, days: int = 30) -> dict:
    """전략별 최근 N일 AI/RULE 취소 통계를 집계한다."""
    defaults: dict = {"ai_cancel_count": 0, "rule_cancel_count": 0, "avg_ai_score": None}
    try:
        row = await pool.fetchrow(
            """
            SELECT
                COUNT(CASE WHEN cancel_type = 'AI'   THEN 1 END) AS ai_cancel_count,
                COUNT(CASE WHEN cancel_type = 'RULE' THEN 1 END) AS rule_cancel_count,
                AVG(CASE  WHEN cancel_type = 'AI'   THEN score END) AS avg_ai_score
            FROM (
                SELECT 'AI' AS cancel_type, ai_score AS score
                FROM ai_cancel_signal
                WHERE strategy = $1
                  AND created_at >= NOW() - ($2 || ' days')::INTERVAL
                UNION ALL
                SELECT 'RULE', rule_score
                FROM rule_cancel_signal
                WHERE strategy = $1
                  AND created_at >= NOW() - ($2 || ' days')::INTERVAL
            ) t
            """,
            strategy,
            str(days),
        )
        if row:
            return {
                "ai_cancel_count": int(row["ai_cancel_count"] or 0),
                "rule_cancel_count": int(row["rule_cancel_count"] or 0),
                "avg_ai_score": round(float(row["avg_ai_score"]), 2) if row["avg_ai_score"] is not None else None,
            }
        return defaults
    except Exception as e:
        logger.error("[DBReader] get_recent_cancel_stats error strategy=%s: %s", strategy, e)
        return defaults
