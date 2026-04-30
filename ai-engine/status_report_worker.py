from __future__ import annotations

"""
status_report_worker.py

KST 기준 지정된 슬롯에 전략/후보풀/큐/WS 상태를 요약해 ai_scored_queue로 발행한다.
telegram-bot 은 STATUS_REPORT 타입을 브로드캐스트한다.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger("status_report_worker")

KST = timezone(timedelta(hours=9))
STATUS_REPORT_ENABLED = os.getenv("ENABLE_STATUS_REPORT", "true").lower() == "true"
STATUS_REPORT_QUEUE_TTL = 43200
STATUS_REPORT_HEADER = "<b>전략 상태 브리핑</b>"


def _parse_report_slots() -> tuple[time, ...]:
    raw = os.getenv("STATUS_REPORT_SLOTS", "08:30,12:00,15:40")
    slots: list[time] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        hour_str, minute_str = token.split(":", 1)
        slots.append(time(int(hour_str), int(minute_str)))
    if not slots:
        slots.append(time(12, 0))
    return tuple(sorted(slots))


STATUS_REPORT_SLOTS = _parse_report_slots()

STRATEGY_WINDOWS: dict[str, tuple[time, time]] = {
    "S1_GAP_OPEN": (time(8, 50), time(9, 30)),
    "S3_INST_FRGN": (time(9, 30), time(14, 30)),
    "S4_BIG_CANDLE": (time(10, 0), time(14, 30)),
    "S5_PROG_FRGN": (time(10, 0), time(14, 0)),
    "S6_THEME_LAGGARD": (time(9, 30), time(13, 0)),
    "S7_ICHIMOKU_BREAKOUT": (time(10, 0), time(14, 30)),
    "S8_GOLDEN_CROSS": (time(10, 0), time(14, 30)),
    "S9_PULLBACK_SWING": (time(9, 30), time(13, 0)),
    "S10_NEW_HIGH": (time(10, 0), time(14, 0)),
    "S11_FRGN_CONT": (time(10, 0), time(14, 30)),
    "S12_CLOSING": (time(14, 30), time(15, 10)),
    "S13_BOX_BREAKOUT": (time(10, 0), time(14, 0)),
    "S14_OVERSOLD_BOUNCE": (time(10, 0), time(13, 0)),
    "S15_MOMENTUM_ALIGN": (time(9, 30), time(12, 0)),
}

POOL_KEYS: dict[str, list[str]] = {
    "S1_GAP_OPEN": ["candidates:s1:001", "candidates:s1:101"],
    "S3_INST_FRGN": ["candidates:s3:001", "candidates:s3:101"],
    "S4_BIG_CANDLE": ["candidates:s4:001", "candidates:s4:101"],
    "S5_PROG_FRGN": ["candidates:s5:001", "candidates:s5:101"],
    "S6_THEME_LAGGARD": ["candidates:s6:001", "candidates:s6:101"],
    "S7_ICHIMOKU_BREAKOUT": ["candidates:s7:001", "candidates:s7:101"],
    "S8_GOLDEN_CROSS": ["candidates:s8:001", "candidates:s8:101"],
    "S9_PULLBACK_SWING": ["candidates:s9:001", "candidates:s9:101"],
    "S10_NEW_HIGH": ["candidates:s10:001", "candidates:s10:101"],
    "S11_FRGN_CONT": ["candidates:s11:001", "candidates:s11:101"],
    "S12_CLOSING": ["candidates:s12:001", "candidates:s12:101"],
    "S13_BOX_BREAKOUT": ["candidates:s13:001", "candidates:s13:101"],
    "S14_OVERSOLD_BOUNCE": ["candidates:s14:001", "candidates:s14:101"],
    "S15_MOMENTUM_ALIGN": ["candidates:s15:001", "candidates:s15:101"],
}


def _is_active(now_kst: datetime, strategy: str) -> bool:
    window = STRATEGY_WINDOWS.get(strategy)
    if not window:
        return False
    start, end = window
    current = now_kst.time()
    return start <= current <= end


async def _pool_count(rdb, keys: list[str]) -> int:
    total = 0
    for key in keys:
        try:
            total += await rdb.llen(key)
        except Exception as e:
            logger.debug("[StatusReport] pool count failed [%s]: %s", key, e)
    return total


async def _get_recent_signal_stats(rdb, strategies: list[str]) -> dict[str, dict[str, int | str]]:
    stats: dict[str, dict[str, int | str]] = {}
    for strategy in strategies:
        try:
            signals = int(await rdb.get(f"status:signals_10m:{strategy}") or 0)
        except Exception:
            signals = 0
        try:
            enters = int(await rdb.get(f"status:decisions_10m:{strategy}:ENTER") or 0)
        except Exception:
            enters = 0
        try:
            cancels = int(await rdb.get(f"status:decisions_10m:{strategy}:CANCEL") or 0)
        except Exception:
            cancels = 0
        try:
            last_signal = await rdb.hgetall(f"status:last_signal:{strategy}")
        except Exception:
            last_signal = {}

        stats[strategy] = {
            "signals": signals,
            "enters": enters,
            "cancels": cancels,
            "last_stk_cd": last_signal.get("stk_cd", ""),
        }
    return stats


async def _get_s2_worker_status(rdb) -> dict[str, str]:
    try:
        return await rdb.hgetall("status:s2_vi_watch_worker")
    except Exception as e:
        logger.debug("[StatusReport] S2 worker status fetch failed: %s", e)
        return {}


def _build_message(
    now_kst: datetime,
    active: list[str],
    pool_counts: dict[str, int],
    queue_counts: dict[str, int],
    ws_online: bool,
    recent_stats: dict[str, dict[str, int | str]],
    position_count: int = 0,
    exit_today_count: int = 0,
    trailing_active_count: int = 0,
    reversal_claude_calls: int = 0,
    ws_event_mode: str = "unknown",
    pipeline_stats: dict[str, dict[str, int]] | None = None,
    exit_type_mix: dict[str, int] | None = None,
    avg_hold_time_min: float = 0.0,
) -> str:
    active_lines = [f"• {name}: 후보 {pool_counts.get(name, 0)}개" for name in active[:6]]
    if not active_lines:
        active_lines.append("• 현재 활성 전략 없음")

    top_pools = sorted(pool_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    pool_lines = [f"• {name}: {count}개" for name, count in top_pools if count > 0]
    if not pool_lines:
        pool_lines.append("• 후보풀 비어 있음")

    recent_lines = []
    for name in active[:6]:
        stat = recent_stats.get(name, {})
        signals = int(stat.get("signals", 0) or 0)
        enters = int(stat.get("enters", 0) or 0)
        cancels = int(stat.get("cancels", 0) or 0)
        last_stk_cd = str(stat.get("last_stk_cd", "") or "")
        if signals <= 0 and enters <= 0 and cancels <= 0:
            continue
        suffix = f" / 마지막 {last_stk_cd}" if last_stk_cd else ""
        recent_lines.append(
            f"• {name}: 신호 {signals}건 ENTER {enters}건 CANCEL {cancels}건{suffix}"
        )
    if not recent_lines:
        recent_lines.append("• 최근 10분 신호 없음")

    queue_lines = [
        f"• telegram_queue: {queue_counts.get('telegram_queue', 0)}",
        f"• ai_scored_queue: {queue_counts.get('ai_scored_queue', 0)}",
        f"• vi_watch_queue: {queue_counts.get('vi_watch_queue', 0)}",
        f"• error_queue: {queue_counts.get('error_queue', 0)}",
    ]

    pipeline_lines = []
    if pipeline_stats:
        for sname, stat in list(pipeline_stats.items())[:6]:
            c = stat.get("candidate", 0)
            rp = stat.get("rule_pass", 0)
            ap = stat.get("ai_pass", 0)
            pub = stat.get("publish", 0)
            if c == 0:
                continue
            pipeline_lines.append(f"• {sname}: 후보{c}→규칙{rp}→AI{ap}→발송{pub}")
    if not pipeline_lines:
        pipeline_lines.append("• 오늘 파이프라인 데이터 없음")

    ws_label = "정상" if ws_online else "오프라인"
    header = now_kst.strftime("%Y-%m-%d %H:%M")
    return (
        f"📤 {STATUS_REPORT_HEADER}\n"
        f"시각: {header} KST\n"
        f"WS: {ws_label}\n\n"
        f"<b>현재 메인 전략</b>\n" + "\n".join(active_lines) + "\n\n"
        f"<b>후보풀 상위</b>\n" + "\n".join(pool_lines) + "\n\n"
        f"<b>최근 10분 신호/판정</b>\n" + "\n".join(recent_lines) + "\n\n"
        f"<b>오늘 파이프라인 전환율</b>\n" + "\n".join(pipeline_lines) + "\n\n"
        f"<b>큐 상태</b>\n" + "\n".join(queue_lines) + "\n\n"
        f"<b>포지션 현황</b>\n"
        f"보유: {position_count}종목 | 오늘 청산: {exit_today_count}건 | 추적중: {trailing_active_count}건\n"
        f"역추세 Claude: {reversal_claude_calls}회 | 평균보유: {avg_hold_time_min:.0f}분 | DB이벤트모드: {ws_event_mode}"
        + (
            "\n" + " ".join(
                f"{k}:{v}" for k, v in (exit_type_mix or {}).items() if v > 0
            ) if exit_type_mix else ""
        )
    )


async def _publish_status_report(rdb) -> None:
    now_kst = datetime.now(KST)
    active = [name for name in STRATEGY_WINDOWS if _is_active(now_kst, name)]

    pool_counts: dict[str, int] = {}
    for strategy, keys in POOL_KEYS.items():
        pool_counts[strategy] = await _pool_count(rdb, keys)

    recent_stats = await _get_recent_signal_stats(rdb, list(STRATEGY_WINDOWS.keys()) + ["S2_VI_PULLBACK"])
    s2_worker_status = await _get_s2_worker_status(rdb)

    queue_counts = {}
    for key in ("telegram_queue", "ai_scored_queue", "vi_watch_queue", "error_queue"):
        try:
            queue_counts[key] = await rdb.llen(key)
        except Exception as e:
            logger.debug("[StatusReport] queue count failed [%s]: %s", key, e)
            queue_counts[key] = 0

    try:
        hb = await rdb.hgetall("ws:py_heartbeat")
        ws_online = bool(hb and hb.get("updated_at"))
    except Exception:
        ws_online = False

    # 포지션/청산 데이터 수집
    try:
        pos_type = await rdb.type("open_positions")
        if pos_type == "set":
            position_count = await rdb.scard("open_positions")
        elif pos_type == "hash":
            position_count = await rdb.hlen("open_positions")
        else:
            position_count = 0
    except Exception as e:
        logger.debug("[StatusReport] open_positions count failed: %s", e)
        position_count = 0

    try:
        ws_event_mode = await rdb.get("ws:db_writer:event_mode") or "unknown"
    except Exception as e:
        logger.debug("[StatusReport] ws_event_mode fetch failed: %s", e)
        ws_event_mode = "unknown"

    today = now_kst.strftime("%Y-%m-%d")
    exit_today_count = 0
    trailing_active_count = 0
    reversal_claude_calls = 0
    exit_type_mix: dict[str, int] = {}
    avg_hold_time_min = 0.0
    _EXIT_TYPES = ("SL_HIT", "TP1_HIT", "TP2_HIT", "TRAILING_STOP", "TREND_REVERSAL")
    try:
        exit_hash = await rdb.hgetall(f"exit_daily:{today}")
        exit_today_count = int(exit_hash.get("total", 0) or 0)
        trailing_active_count = int(exit_hash.get("trailing_active", 0) or 0)
        reversal_claude_calls = int(exit_hash.get("reversal_claude_calls", 0) or 0)
        for etype in _EXIT_TYPES:
            cnt = int(exit_hash.get(etype, 0) or 0)
            if cnt > 0:
                exit_type_mix[etype] = cnt
        hold_sum = float(exit_hash.get("hold_time_sum_min", 0) or 0)
        hold_cnt = int(exit_hash.get("exit_count_with_time", 0) or 0)
        if hold_cnt > 0:
            avg_hold_time_min = hold_sum / hold_cnt
    except Exception as e:
        logger.debug("[StatusReport] exit_daily fetch failed: %s", e)

    pipeline_stats: dict[str, dict[str, int]] = {}
    try:
        pattern_keys = await rdb.keys(f"pipeline_daily:{today}:*")
        for pkey in pattern_keys:
            sname = pkey.split(":", 2)[-1] if pkey.count(":") >= 2 else pkey
            raw = await rdb.hgetall(pkey)
            if raw:
                pipeline_stats[sname] = {k: int(v) for k, v in raw.items()}
    except Exception:
        pass

    payload = {
        "type": "STATUS_REPORT",
        "message": _build_message(
            now_kst, active, pool_counts, queue_counts, ws_online, recent_stats,
            position_count=position_count,
            exit_today_count=exit_today_count,
            trailing_active_count=trailing_active_count,
            reversal_claude_calls=reversal_claude_calls,
            ws_event_mode=ws_event_mode,
            pipeline_stats=pipeline_stats,
        ),
        "summary": {
            "active_strategies": active,
            "pool_counts": pool_counts,
            "queue_counts": queue_counts,
            "ws_online": ws_online,
            "recent_stats": recent_stats,
            "s2_worker_status": s2_worker_status,
            "position_count": position_count,
            "exit_today_count": exit_today_count,
            "trailing_active_count": trailing_active_count,
            "ws_event_mode": ws_event_mode,
            "pipeline_stats": pipeline_stats,
        },
        "timestamp": now_kst.isoformat(),
    }
    await rdb.lpush("ai_scored_queue", json.dumps(payload, ensure_ascii=False))
    await rdb.expire("ai_scored_queue", STATUS_REPORT_QUEUE_TTL)
    await rdb.set("ops:scheduler:status_report:last_status", "OK", ex=STATUS_REPORT_QUEUE_TTL)
    await rdb.set("ops:scheduler:status_report:last_success_at", now_kst.isoformat(), ex=STATUS_REPORT_QUEUE_TTL)
    logger.info("[StatusReport] STATUS_REPORT published active=%d", len(active))


def _is_business_day(now_kst: datetime) -> bool:
    return now_kst.weekday() < 5


def _next_report_slot(now_kst: datetime) -> datetime:
    base = now_kst.replace(second=0, microsecond=0)

    if not _is_business_day(now_kst):
        days_ahead = 7 - now_kst.weekday()
        first_slot = STATUS_REPORT_SLOTS[0]
        return (base + timedelta(days=days_ahead)).replace(hour=first_slot.hour, minute=first_slot.minute)

    for slot in STATUS_REPORT_SLOTS:
        candidate = base.replace(hour=slot.hour, minute=slot.minute)
        if candidate > now_kst:
            return candidate

    next_day = base + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    first_slot = STATUS_REPORT_SLOTS[0]
    return next_day.replace(hour=first_slot.hour, minute=first_slot.minute, second=0, microsecond=0)


async def _sleep_until_next_slot() -> None:
    now_kst = datetime.now(KST)
    next_slot = _next_report_slot(now_kst)
    sleep_seconds = max(1.0, (next_slot - now_kst).total_seconds())
    logger.info("[StatusReport] next scheduled briefing at %s KST (in %.0fs)",
                next_slot.strftime("%Y-%m-%d %H:%M"), sleep_seconds)
    await asyncio.sleep(sleep_seconds)


async def run_status_report_worker(rdb) -> None:
    if not STATUS_REPORT_ENABLED:
        logger.info("[StatusReport] disabled")
        return

    slots = ", ".join(f"{slot.hour:02d}:{slot.minute:02d}" for slot in STATUS_REPORT_SLOTS)
    logger.info("[StatusReport] started scheduled slots=%s KST", slots)
    while True:
        try:
            await _sleep_until_next_slot()
            await _publish_status_report(rdb)
        except asyncio.CancelledError:
            logger.info("[StatusReport] stopped")
            break
        except Exception as e:
            logger.error("[StatusReport] loop error: %s", e)
            try:
                await rdb.set("ops:scheduler:status_report:last_status", "ERROR", ex=STATUS_REPORT_QUEUE_TTL)
            except Exception:
                pass
            await asyncio.sleep(30)
