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


def _next_trading_day_preopen_utc(base_dt: Optional[datetime] = None) -> datetime:
    base = base_dt.astimezone(KST) if base_dt else datetime.now(KST)
    candidate = base.date() + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    next_run_kst = datetime.combine(candidate, datetime.min.time(), tzinfo=KST).replace(hour=7)
    return next_run_kst.astimezone(timezone.utc)


def _is_active_signal(signal_status: Optional[str], exit_type: Optional[str]) -> bool:
    return (signal_status or "PENDING") in ACTIVE_SIGNAL_STATUSES and not exit_type


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
                news_ctrl        = $21
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
    now = datetime.utcnow()
    status = "SENT" if action == "ENTER" else "CANCELLED"
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO trading_signals (
                stk_cd, strategy, signal_status, action, confidence,
                rule_score, ai_score, signal_score, ai_reason, skip_entry,
                entry_price, target_price, stop_price,
                tp1_price, tp2_price, sl_price,
                gap_pct, vol_ratio, cntr_strength, bid_ratio, pullback_pct,
                entry_type, theme_name, market_type,
                created_at, scored_at
            ) VALUES (
                $1,$2,$3,$4,$5,
                $6,$7,$8,$9,$10,
                $11,$12,$13,
                $14,$15,$16,
                $17,$18,$19,$20,$21,
                $22,$23,$24,
                $25,$26
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
            _sf(signal.get("gap_pct")),
            _sf(signal.get("vol_ratio")),
            _sf(signal.get("cntr_strength") or signal.get("cntr_str")),
            _sf(signal.get("bid_ratio")),
            _sf(signal.get("pullback_pct")),
            signal.get("entry_type"),
            signal.get("theme_name"),
            signal.get("market_type"),
            now,
            now,
        )
        return row["id"] if row else None
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
) -> bool:
    if not signal_id:
        return False
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await _load_signal_for_update(conn, signal_id)
                if not row or row["signal_status"] in TERMINAL_SIGNAL_STATUSES:
                    return False

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
                        time_stop_session = COALESCE($13, time_stop_session)
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
        logger.error("[DBWriter] get_active_positions error: %s", e)
        return []


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
                if str(row["position_status"] or "ACTIVE") != "PARTIAL_TP":
                    return False
                current_peak = _opt_int(row["peak_price"])
                if current_peak is not None and current_peak >= peak_price:
                    return True
                await conn.execute(
                    "UPDATE trading_signals SET peak_price = $2 WHERE id = $1",
                    position_id,
                    int(peak_price),
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
