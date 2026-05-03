"""
position_monitor.py
실시간 포지션 모니터링 워커 — 30초 폴링

청산 트리거 (우선순위 순):
  1. SL_HIT         — cur_prc <= sl_price                          (즉시)
  2. TP2_HIT        — cur_prc >= tp2_price                         (즉시)
  3. TP1_HIT        — cur_prc >= tp1_price (처음 한 번, PARTIAL_TP로 전환)
  4. TRAILING_STOP  — peak_price 갱신 후 cur_prc <= peak*(1-trailing_pct%)  (즉시)
  5. TREND_REVERSAL — downtrend_score >= 3 → Claude 판단 → exit=true 시 청산

각 트리거 발동 시:
  - DB close_open_position() / mark_tp1_hit()
  - ai_scored_queue 에 SELL_SIGNAL 발행 → telegram-bot 이 수신
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from analyzer import analyze_exit
from db_reader import get_active_positions
from db_writer import (
    update_peak_price,
    close_open_position,
    update_shadow_trade_mark,
)
from downtrend_detector import compute_reversal_score
from http_utils import fetch_stk_nm
from redis_reader import get_tick_data

logger = logging.getLogger("position_monitor")
KST = timezone(timedelta(hours=9))

# ── 전략별 트레일링 스탑 비율 (%) ────────────────────────────────
_TRAILING_PCT_BY_STRATEGY: dict[str, float] = {
    # Swing (3~7거래일)
    "S7_ICHIMOKU_BREAKOUT": 2.5,
    "S8_GOLDEN_CROSS":    2.5,
    "S9_PULLBACK_SWING":  2.5,
    "S15_MOMENTUM_ALIGN": 2.5,
    "S3_INST_FRGN":       2.5,
    "S5_PROG_FRGN":       2.5,
    "S11_FRGN_CONT":      2.5,
    # Day trade (당일~익일)
    "S1_GAP_OPEN":        1.0,
    "S2_VI_PULLBACK":     1.0,
    "S4_BIG_CANDLE":      1.0,
    # Event/breakout
    "S6_THEME_LAGGARD":   2.0,
    "S10_NEW_HIGH":       2.0,
    "S13_BOX_BREAKOUT":   2.0,
    # Close/bounce
    "S12_CLOSING":        1.5,
    "S14_OVERSOLD_BOUNCE": 1.5,
}

_TRAILING_PCT_DEFAULT = 1.5   # DB 컬럼 기본값 (이 값일 때만 전략 티어로 덮어씀)

_TIME_STOP_PNL_GUARD: dict[str, float] = {
    "S1_GAP_OPEN": 1.0,
    "S2_VI_PULLBACK": 0.8,
    "S3_INST_FRGN": 2.5,
    "S4_BIG_CANDLE": 1.0,
    "S5_PROG_FRGN": 2.5,
    "S6_THEME_LAGGARD": 1.0,
    "S7_ICHIMOKU_BREAKOUT": 3.0,
    "S8_GOLDEN_CROSS": 3.0,
    "S9_PULLBACK_SWING": 2.5,
    "S10_NEW_HIGH": 4.0,
    "S11_FRGN_CONT": 3.0,
    "S12_CLOSING": 1.5,
    "S13_BOX_BREAKOUT": 3.0,
    "S14_OVERSOLD_BOUNCE": 1.5,
    "S15_MOMENTUM_ALIGN": 3.0,
}


def _get_trailing_pct(strategy: str) -> float:
    """전략 이름 기반 트레일링 스탑 비율(%) 반환. 매핑 없으면 기본값 1.5."""
    return _TRAILING_PCT_BY_STRATEGY.get(strategy.upper(), _TRAILING_PCT_DEFAULT)


def _business_days_held(entry_at, now_kst: datetime) -> int:
    if entry_at is None:
        return 0
    if hasattr(entry_at, "tzinfo") and entry_at.tzinfo is not None:
        cur = entry_at.astimezone(KST).date()
    else:
        cur = entry_at.date()
    end = now_kst.date()
    days = 0
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _resolve_time_stop_policy(pos: dict) -> tuple[str, int | None, str]:
    strategy = str(pos.get("strategy") or "").upper()
    stored_type = str(pos.get("time_stop_type") or "").strip()
    stored_minutes = pos.get("time_stop_minutes")
    stored_session = str(pos.get("time_stop_session") or "").strip()
    if stored_type or stored_minutes is not None or stored_session:
        return stored_type, int(stored_minutes) if stored_minutes is not None else None, stored_session

    defaults: dict[str, tuple[str, int | None, str]] = {
        "S1_GAP_OPEN": ("intraday_minutes", 30, "same_day_close"),
        "S2_VI_PULLBACK": ("intraday_minutes", 15, "same_day_close"),
        "S3_INST_FRGN": ("trading_days", 2, ""),
        "S4_BIG_CANDLE": ("intraday_minutes", 20, "same_day_close"),
        "S5_PROG_FRGN": ("trading_days", 2, ""),
        "S6_THEME_LAGGARD": ("session_close", None, "same_day_close"),
        "S7_ICHIMOKU_BREAKOUT": ("trading_days", 5, ""),
        "S8_GOLDEN_CROSS": ("trading_days", 7, ""),
        "S9_PULLBACK_SWING": ("trading_days", 5, ""),
        "S10_NEW_HIGH": ("trading_days", 10, ""),
        "S11_FRGN_CONT": ("trading_days", 7, ""),
        "S12_CLOSING": ("session_close", None, "next_day_morning"),
        "S13_BOX_BREAKOUT": ("trading_days", 7, ""),
        "S14_OVERSOLD_BOUNCE": ("trading_days", 3, ""),
        "S15_MOMENTUM_ALIGN": ("trading_days", 10, ""),
    }
    return defaults.get(strategy, ("", None, ""))


def _should_trigger_time_stop(
    pos: dict,
    *,
    cur_prc: int,
    entry_price: int,
    tp1_price: int,
    status: str,
    now_kst: datetime,
) -> tuple[bool, str]:
    if status not in {"ACTIVE", "OVERNIGHT"}:
        return False, ""

    entry_at = pos.get("entry_at")
    if entry_at is None or entry_price <= 0:
        return False, ""

    if hasattr(entry_at, "tzinfo") and entry_at.tzinfo is not None:
        entry_kst = entry_at.astimezone(KST)
    else:
        entry_kst = entry_at.replace(tzinfo=KST)

    hold_min = max(0, int((now_kst - entry_kst).total_seconds() // 60))
    pnl_pct = _pnl(entry_price, cur_prc)
    strategy = str(pos.get("strategy") or "").upper()
    pnl_guard = _TIME_STOP_PNL_GUARD.get(strategy, 2.0)
    time_stop_type, time_stop_minutes, time_stop_session = _resolve_time_stop_policy(pos)

    if time_stop_type == "intraday_minutes" and time_stop_minutes is not None:
        if hold_min >= time_stop_minutes and cur_prc < max(tp1_price, entry_price) and pnl_pct < pnl_guard:
            return True, f"{time_stop_minutes}분 내 follow-through 부재"

    if time_stop_type == "session_close" and time_stop_session == "same_day_close":
        if entry_kst.date() == now_kst.date() and now_kst.hour == 15 and now_kst.minute >= 18:
            return True, "당일 전략 장마감 정리"

    if time_stop_type == "session_close" and time_stop_session == "next_day_morning":
        if now_kst.date() > entry_kst.date():
            if (now_kst.hour > 10 or (now_kst.hour == 10 and now_kst.minute >= 30)) and pnl_pct < pnl_guard:
                return True, "익일 오전 continuation 실패"

    if time_stop_type == "trading_days" and time_stop_minutes is not None:
        days_held = _business_days_held(entry_at, now_kst)
        if days_held >= time_stop_minutes and cur_prc < max(tp1_price, entry_price) and pnl_pct < pnl_guard:
            return True, f"{time_stop_minutes}거래일 내 목표 미달"

    if time_stop_session == "same_day_close" and now_kst.hour == 15 and now_kst.minute >= 18:
        if strategy in {"S1_GAP_OPEN", "S2_VI_PULLBACK", "S4_BIG_CANDLE", "S6_THEME_LAGGARD"}:
            return True, "당일 전략 장마감 정리"

    return False, ""


MONITOR_INTERVAL_SEC    = int(os.getenv("POSITION_MONITOR_INTERVAL_SEC", "30"))
REVERSAL_CLAUDE_ENABLED = os.getenv("REVERSAL_CLAUDE_ENABLED", "true").lower() == "true"
# 포지션당 Claude 호출 쿨다운 (초) — 동일 포지션에 연속 호출 방지
_CLAUDE_CALL_COOLDOWN   = int(os.getenv("REVERSAL_CLAUDE_COOLDOWN_SEC", "120"))
REDIS_TOKEN_KEY         = "kiwoom:token"
SELL_RECO_QUEUE_KEY     = os.getenv("SELL_RECOMMENDATION_QUEUE", "ai_scored_queue")
SELL_RECO_DEDUP_TTL_SEC = int(os.getenv("SELL_RECOMMENDATION_DEDUP_TTL_SEC", "43200"))

# {position_id: last_claude_call_ts}
_last_claude_call: dict[int, float] = {}


async def run_position_monitor(rdb, pg_pool):
    """
    engine.py 에서 asyncio.create_task(run_position_monitor(rdb, pg_pool)) 로 등록.
    pg_pool 이 None 이면 DB 연결 불가 → 경고 후 즉시 종료.
    """
    if pg_pool is None:
        logger.warning("[PosMon] PostgreSQL 풀 없음 — position_monitor 비활성화")
        return

    logger.info("[PosMon] 포지션 모니터 시작 (interval=%ds)", MONITOR_INTERVAL_SEC)
    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL_SEC)
            await _scan_all(rdb, pg_pool)
        except asyncio.CancelledError:
            logger.info("[PosMon] 포지션 모니터 종료")
            break
        except Exception as e:
            logger.error("[PosMon] 스캔 루프 오류: %s", e, exc_info=True)
            await asyncio.sleep(10)


async def _scan_all(rdb, pg_pool):
    positions = await get_active_positions(pg_pool)
    if not positions:
        return
    logger.debug("[PosMon] 활성 포지션 %d건 스캔", len(positions))

    trailing_count = sum(1 for p in positions if p.get("peak_price") and p.get("trailing_pct"))
    if trailing_count > 0:
        today = datetime.now(KST).strftime("%Y-%m-%d")
        try:
            await rdb.hset(f"exit_daily:{today}", "trailing_active", trailing_count)
            await rdb.expire(f"exit_daily:{today}", 86400)
        except Exception as e:
            logger.debug("[PosMon] trailing_active 기록 실패: %s", e)

    tasks = [_check_position(rdb, pg_pool, pos) for pos in positions]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _check_position(rdb, pg_pool, pos: dict):
    position_id = pos["id"]
    stk_cd      = pos["stk_cd"]
    entry_price = int(pos["entry_price"] or 0)
    sl_price    = int(pos["sl_price"]    or 0)
    tp1_price   = int(pos["tp1_price"]   or 0) if pos.get("tp1_price") else 0
    tp2_price   = int(pos["tp2_price"]   or 0) if pos.get("tp2_price") else 0
    trailing_activation = int(pos["trailing_activation"] or 0) if pos.get("trailing_activation") else 0
    stored_trailing = float(pos.get("trailing_pct") or _TRAILING_PCT_DEFAULT)
    strategy_name   = pos.get("strategy", "")
    reassessment = await _load_reassessment(rdb, position_id)
    # DB에 저장된 값이 구 기본값(1.5)일 때만 전략 티어로 교체.
    # 수동으로 설정된 값(1.5 와 다른 값)은 그대로 유지.
    dynamic_trailing = reassessment.get("dynamic_trailing_pct") if reassessment else None
    if dynamic_trailing is not None:
        try:
            trailing_pct = float(dynamic_trailing)
        except (TypeError, ValueError):
            trailing_pct = stored_trailing
    elif stored_trailing == _TRAILING_PCT_DEFAULT:
        trailing_pct = _get_trailing_pct(strategy_name)
    else:
        trailing_pct = stored_trailing
    peak_price  = int(pos["peak_price"]) if pos.get("peak_price") else None
    status      = pos.get("status", "ACTIVE")
    now_kst     = datetime.now(KST)

    # ── 현재가 읽기 (ws:tick) ─────────────────────────────────
    tick    = await get_tick_data(rdb, stk_cd)
    cur_prc = _parse_int(tick.get("cur_prc"))
    if cur_prc is None or cur_prc <= 0:
        logger.debug("[PosMon] ws:tick 없음 stk_cd=%s — 스킵", stk_cd)
        return

    signal_id   = pos.get("signal_id") or 0
    await update_shadow_trade_mark(
        pg_pool,
        signal_id=signal_id,
        cur_prc=cur_prc,
        data_quality="OK",
        data_quality_detail={
            "source": "position_monitor",
            "stk_cd": stk_cd,
            "tick_seen_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # ── 1. SL_HIT ────────────────────────────────────────────
    if sl_price > 0 and cur_prc <= sl_price:
        pnl_pct = _pnl(entry_price, cur_prc)
        await _publish_sell_recommendation(
            rdb, pos, cur_prc, "SL", pnl_pct,
            trigger_price=sl_price,
            urgent=True,
            partial=False,
            reassessment=reassessment,
        )
        ok = await close_open_position(
            pg_pool, position_id,
            signal_id=signal_id,
            exit_type="SL_HIT",
            exit_price=cur_prc,
            realized_pnl_pct=pnl_pct,
        )
        if ok:
            await _publish_sell(rdb, pos, cur_prc, "SL_HIT", pnl_pct)
        return

    # ── 2. TIME_STOP ─────────────────────────────────────────
    should_stop, time_stop_reason = _should_trigger_time_stop(
        pos,
        cur_prc=cur_prc,
        entry_price=entry_price,
        tp1_price=tp1_price,
        status=status,
        now_kst=now_kst,
    )
    if should_stop:
        pnl_pct = _pnl(entry_price, cur_prc)
        extra = {
            "time_stop_reason": time_stop_reason,
            "time_stop_type": pos.get("time_stop_type"),
            "time_stop_minutes": pos.get("time_stop_minutes"),
            "time_stop_session": pos.get("time_stop_session"),
        }
        await _publish_sell_recommendation(
            rdb, pos, cur_prc, "TIME_STOP", pnl_pct,
            trigger_price=cur_prc,
            urgent=False,
            partial=False,
            reassessment=reassessment,
            extra=extra,
        )
        ok = await close_open_position(
            pg_pool, position_id,
            signal_id=signal_id,
            exit_type="TIME_STOP",
            exit_price=cur_prc,
            realized_pnl_pct=pnl_pct,
        )
        if ok:
            await _publish_sell(rdb, pos, cur_prc, "TIME_STOP", pnl_pct, extra=extra)
        return

    # ── 3. TRAILING_STOP (ACTIVE/OVERNIGHT after activation) ───
    if status in {"ACTIVE", "OVERNIGHT"} and trailing_activation > 0 and trailing_pct > 0:
        if cur_prc >= trailing_activation:
            if peak_price is None or cur_prc > peak_price:
                await update_peak_price(pg_pool, position_id, cur_prc)
                peak_price = cur_prc
            if peak_price is not None:
                trailing_threshold = int(peak_price * (1.0 - trailing_pct / 100.0))
                if cur_prc <= trailing_threshold:
                    pnl_pct = _pnl(entry_price, cur_prc)
                    await _publish_sell_recommendation(
                        rdb, pos, cur_prc, "TRAILING", pnl_pct,
                        trigger_price=trailing_threshold,
                        urgent=True,
                        partial=False,
                        reassessment=reassessment,
                        extra={"peak_price": peak_price, "trailing_pct": trailing_pct},
                    )
                    ok = await close_open_position(
                        pg_pool, position_id,
                        signal_id=signal_id,
                        exit_type="TRAILING_STOP",
                        exit_price=cur_prc,
                        realized_pnl_pct=pnl_pct,
                    )
                    if ok:
                        await _publish_sell(rdb, pos, cur_prc, "TRAILING_STOP", pnl_pct,
                                            extra={"peak_price": peak_price, "trailing_pct": trailing_pct})
                    return

    # ── 4. TP_HIT (single target, full close) ───────
    if status == "ACTIVE" and tp1_price > 0 and cur_prc >= tp1_price:
        pnl_pct = _pnl(entry_price, cur_prc)
        ok = await close_open_position(
            pg_pool, position_id,
            signal_id=signal_id,
            exit_type="TP1_HIT",
            exit_price=cur_prc,
            realized_pnl_pct=pnl_pct,
        )
        if ok:
            await _publish_sell_recommendation(
                rdb, pos, cur_prc, "TP", pnl_pct,
                trigger_price=tp1_price,
                urgent=False,
                partial=False,
                reassessment=reassessment,
            )
            await _publish_sell(rdb, pos, cur_prc, "TP1_HIT", pnl_pct, partial=False)
        return

    # ── 5. legacy PARTIAL_TP trailing compatibility ───────────
    if status == "PARTIAL_TP":
        # peak_price 갱신
        if peak_price is None or cur_prc > peak_price:
            await update_peak_price(pg_pool, position_id, cur_prc)
            peak_price = cur_prc

        trailing_threshold = int(peak_price * (1.0 - trailing_pct / 100.0))
        if cur_prc <= trailing_threshold:
            pnl_pct = _pnl(entry_price, cur_prc)
            await _publish_sell_recommendation(
                rdb, pos, cur_prc, "TRAILING", pnl_pct,
                trigger_price=trailing_threshold,
                urgent=True,
                partial=False,
                reassessment=reassessment,
                extra={"peak_price": peak_price, "trailing_pct": trailing_pct},
            )
            ok = await close_open_position(
                pg_pool, position_id,
                signal_id=signal_id,
                exit_type="TRAILING_STOP",
                exit_price=cur_prc,
                realized_pnl_pct=pnl_pct,
            )
            if ok:
                await _publish_sell(rdb, pos, cur_prc, "TRAILING_STOP", pnl_pct,
                                    extra={"peak_price": peak_price, "trailing_pct": trailing_pct})
            return

    # ── 5. TREND_REVERSAL 감지 ────────────────────────────────
    reversal = await compute_reversal_score(rdb, stk_cd, entry_price=entry_price, cur_prc=cur_prc)
    if not reversal["triggered"]:
        return

    # Claude 호출 쿨다운 체크
    now_ts = asyncio.get_event_loop().time()
    last_call = _last_claude_call.get(position_id, 0.0)
    if now_ts - last_call < _CLAUDE_CALL_COOLDOWN:
        logger.debug("[PosMon] TREND_REVERSAL 쿨다운 중 position_id=%d", position_id)
        return

    _last_claude_call[position_id] = now_ts

    if not REVERSAL_CLAUDE_ENABLED:
        # Claude 비활성 → reversal score만으로 청산
        pnl_pct = _pnl(entry_price, cur_prc)
        ok = await close_open_position(
            pg_pool, position_id,
            signal_id=signal_id,
            exit_type="TREND_REVERSAL",
            exit_price=cur_prc,
            realized_pnl_pct=pnl_pct,
        )
        if ok:
            await _publish_sell(rdb, pos, cur_prc, "TREND_REVERSAL", pnl_pct,
                                extra={"reversal_score": reversal["score"], "ai_verdict": "SKIP"})
        return

    # Claude 2차 판단
    _today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        await rdb.hincrby(f"exit_daily:{_today}", "reversal_claude_calls", 1)
        await rdb.expire(f"exit_daily:{_today}", 86400)
    except Exception as _e:
        logger.debug("[PosMon] reversal_claude_calls 기록 실패: %s", _e)
    exit_result = await analyze_exit(
        {**pos, "entry_price": entry_price, "sl_price": sl_price},
        reversal,
        rdb=rdb,
    )
    if exit_result.get("exit"):
        pnl_pct = _pnl(entry_price, cur_prc)
        ok = await close_open_position(
            pg_pool, position_id,
            signal_id=signal_id,
            exit_type="TREND_REVERSAL",
            exit_price=cur_prc,
            realized_pnl_pct=pnl_pct,
        )
        if ok:
            await _publish_sell(
                rdb, pos, cur_prc, "TREND_REVERSAL", pnl_pct,
                extra={
                    "reversal_score": reversal["score"],
                    "ai_verdict":     "EXIT",
                    "ai_confidence":  exit_result.get("confidence"),
                    "ai_reason":      exit_result.get("reason"),
                },
            )
    else:
        logger.info("[PosMon] TREND_REVERSAL Claude 보유 유지 stk_cd=%s score=%.1f reason=%s",
                    stk_cd, reversal["score"], exit_result.get("reason"))


async def _record_exit_daily(rdb, exit_type: str, entry_at) -> None:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    key   = f"exit_daily:{today}"
    try:
        pipe = rdb.pipeline()
        pipe.hincrby(key, "total", 1)
        pipe.hincrby(key, exit_type, 1)
        if entry_at is not None:
            from datetime import timezone as _tz
            now_aware = datetime.now(_tz.utc)
            if hasattr(entry_at, "tzinfo") and entry_at.tzinfo is None:
                entry_at = entry_at.replace(tzinfo=_tz.utc)
            hold_min = (now_aware - entry_at).total_seconds() / 60.0
            pipe.hincrbyfloat(key, "hold_time_sum_min", hold_min)
            pipe.hincrby(key, "exit_count_with_time", 1)
        pipe.expire(key, 86400)
        await pipe.execute()
    except Exception as e:
        logger.debug("[PosMon] exit_daily 기록 실패: %s", e)


async def _load_reassessment(rdb, position_id: int) -> dict:
    try:
        raw = await rdb.get(f"position_ctx:{position_id}")
        return json.loads(raw) if raw else {}
    except Exception as exc:
        logger.debug("[PosMon] reassessment load failed position_id=%s: %s", position_id, exc)
        return {}


async def _publish_sell_recommendation(
    rdb,
    pos: dict,
    cur_prc: int,
    recommendation_type: str,
    pnl_pct: float,
    *,
    trigger_price: int,
    urgent: bool,
    partial: bool,
    reassessment: dict | None = None,
    extra: dict | None = None,
):
    position_id = pos["id"]
    dedup_key = f"sell_reco_dedup:{position_id}:{recommendation_type}"
    try:
        is_new = await rdb.set(dedup_key, "1", nx=True, ex=SELL_RECO_DEDUP_TTL_SEC)
    except Exception as exc:
        logger.debug("[PosMon] sell recommendation dedup failed position_id=%s type=%s: %s",
                     position_id, recommendation_type, exc)
        is_new = True
    if not is_new:
        return

    stk_nm = pos.get("stk_nm", "")
    if not stk_nm:
        try:
            token = await rdb.get(REDIS_TOKEN_KEY)
            if token:
                stk_nm = await fetch_stk_nm(rdb, token, pos["stk_cd"])
        except Exception as exc:
            logger.debug("[PosMon] stk_nm lookup failed [%s]: %s", pos["stk_cd"], exc)

    reason_summary = _build_recommendation_reason(recommendation_type, reassessment or {}, extra or {})
    payload = {
        "type": "SELL_RECOMMENDATION",
        "action": "SELL_RECOMMENDATION",
        "recommendation_type": recommendation_type,
        "position_id": position_id,
        "signal_id": pos.get("signal_id"),
        "stk_cd": pos["stk_cd"],
        "stk_nm": stk_nm,
        "strategy": pos.get("strategy", ""),
        "entry_price": pos.get("entry_price"),
        "cur_prc": cur_prc,
        "trigger_price": trigger_price,
        "sl_price": pos.get("sl_price"),
        "tp1_price": pos.get("tp1_price"),
        "tp2_price": pos.get("tp2_price"),
        "realized_pnl_pct": round(pnl_pct, 4),
        "partial": partial,
        "urgent": urgent,
        "reason_summary": reason_summary,
        "trend_state": (reassessment or {}).get("trend_state"),
        "momentum_state": (reassessment or {}).get("momentum_state"),
        "exit_bias": (reassessment or {}).get("exit_bias"),
        "timestamp": datetime.now(KST).isoformat(),
    }
    if extra:
        payload.update(extra)

    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        await rdb.lpush(SELL_RECO_QUEUE_KEY, serialized)
        await rdb.expire(SELL_RECO_QUEUE_KEY, 43200)
        logger.info("[PosMon] SELL_RECOMMENDATION published stk_cd=%s type=%s partial=%s urgent=%s",
                    pos["stk_cd"], recommendation_type, partial, urgent)
    except Exception as exc:
        logger.error("[PosMon] SELL_RECOMMENDATION publish failed stk_cd=%s: %s", pos["stk_cd"], exc)


def _build_recommendation_reason(recommendation_type: str, reassessment: dict, extra: dict) -> str:
    base_map = {
        "TP1": "TP1 도달로 부분매도 추천",
        "SL": "손절가 이탈로 즉시 손절 추천",
        "TRAILING": "트레일링 스탑 발동으로 잔여 물량 매도 추천",
        "TIME_STOP": "시간 손절 기준 도달로 포지션 정리 추천",
    }
    parts = [base_map.get(recommendation_type, recommendation_type)]
    summary = reassessment.get("reason_summary")
    if summary:
        parts.append(summary)
    if recommendation_type == "TRAILING" and extra.get("peak_price") and extra.get("trailing_pct") is not None:
        parts.append(f"고점 {int(extra['peak_price']):,}원 대비 {float(extra['trailing_pct']):.1f}% 하락")
    if recommendation_type == "TIME_STOP" and extra.get("time_stop_reason"):
        parts.append(str(extra["time_stop_reason"]))
    return " / ".join(parts)


async def _publish_sell(
    rdb,
    pos:       dict,
    cur_prc:   int,
    exit_type: str,
    pnl_pct:   float,
    *,
    partial:   bool = False,
    extra:     dict | None = None,
):
    """
    ai_scored_queue 에 SELL_SIGNAL 발행.
    telegram-bot signals.js 가 폴링하여 수신.
    """
    stk_nm = pos.get("stk_nm", "")
    if not stk_nm:
        try:
            token = await rdb.get(REDIS_TOKEN_KEY)
            if token:
                stk_nm = await fetch_stk_nm(rdb, token, pos["stk_cd"])
        except Exception as nm_err:
            logger.debug("[PosMon] stk_nm 조회 실패 [%s]: %s", pos["stk_cd"], nm_err)

    payload = {
        "type":       "SELL_SIGNAL",
        "action":     "SELL",
        "exit_type":  exit_type,
        "partial":    partial,                    # TP1_HIT = 부분 청산
        "position_id": pos["id"],
        "signal_id":  pos.get("signal_id"),
        "stk_cd":     pos["stk_cd"],
        "stk_nm":     stk_nm,
        "strategy":   pos.get("strategy", ""),
        "entry_price": pos.get("entry_price"),
        "cur_prc":    cur_prc,
        "sl_price":   pos.get("sl_price"),
        "tp1_price":  pos.get("tp1_price"),
        "tp2_price":  pos.get("tp2_price"),
        "realized_pnl_pct": round(pnl_pct, 4),
        "timestamp":  datetime.now(KST).isoformat(),
    }
    if extra:
        payload.update(extra)

    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        await rdb.lpush("ai_scored_queue", serialized)
        await rdb.expire("ai_scored_queue", 43200)
        logger.info(
            "[PosMon] SELL_SIGNAL 발행 stk_cd=%s exit_type=%s pnl=%.2f%% partial=%s",
            pos["stk_cd"], exit_type, pnl_pct, partial,
        )
        await _record_exit_daily(rdb, exit_type, pos.get("entry_at"))
    except Exception as e:
        logger.error("[PosMon] SELL_SIGNAL 발행 실패 stk_cd=%s: %s", pos["stk_cd"], e)


def _pnl(entry_price: int, cur_prc: int) -> float:
    if entry_price <= 0:
        return 0.0
    return (cur_prc - entry_price) / entry_price * 100.0


def _parse_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "").replace("+", "")))
    except (TypeError, ValueError):
        return None
