from __future__ import annotations

"""
news_scheduler.py

고정 시각에만 뉴스 수집/분석을 수행하고 Redis 및 텔레그램 브리핑 큐를 갱신한다.
정규 브리핑 시각:
  08:00 / 12:30 / 15:40 (평일)
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from news_analyzer import analyze_news
from news_collector import collect_news

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

NEWS_ENABLED = os.getenv("NEWS_ENABLED", "true").lower() == "true"

_SLOTS: list[dict[str, object]] = [
    {"time": (8, 0), "name": "MORNING"},
    {"time": (12, 30), "name": "MIDDAY"},
    {"time": (15, 40), "name": "CLOSE"},
]

_KEY_ANALYSIS = "news:analysis"
_KEY_SECTORS = "news:sector_recommend"
_KEY_SENTIMENT = "news:market_sentiment"
_KEY_SCORED_QUEUE = "ai_scored_queue"

_TTL_ANALYSIS = 43200
_TTL_ALERT_Q = 43200


def _now_kst() -> datetime:
    return datetime.now(KST)


def _ensure_kst(now: datetime | None) -> datetime:
    if now is None:
        return _now_kst()
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def _is_weekday(now: datetime | None = None) -> bool:
    current = _ensure_kst(now)
    return current.weekday() < 5


def _next_run_slot(now: datetime | None = None) -> dict[str, object]:
    current = _ensure_kst(now)
    today = current.date()

    for slot in _SLOTS:
        hour, minute = slot["time"]
        candidate = datetime(today.year, today.month, today.day, hour, minute, tzinfo=KST)
        if candidate > current:
            return {"slot": slot, "run_at": candidate}

    next_day = today + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    first_slot = _SLOTS[0]
    hour, minute = first_slot["time"]
    return {
        "slot": first_slot,
        "run_at": datetime(next_day.year, next_day.month, next_day.day, hour, minute, tzinfo=KST),
    }


def _slot_from_now(now: datetime | None = None) -> dict[str, object] | None:
    current = _ensure_kst(now)
    for slot in _SLOTS:
        if (current.hour, current.minute) == slot["time"]:
            return slot
    return None


def _sentiment_label(sentiment: str) -> str:
    return {
        "BULLISH": "강세 우위",
        "BEARISH": "약세 경계",
        "NEUTRAL": "중립 혼조",
    }.get(sentiment or "NEUTRAL", sentiment or "NEUTRAL")


def _normalize_lines(values: list[str] | None, limit: int) -> list[str]:
    if not values:
        return []
    return [str(v).strip() for v in values if str(v).strip()][:limit]


def _slot_header(slot_name: str) -> str:
    return {
        "MORNING": "🧠 <b>[오전 시황 브리핑 08:00]</b>",
        "MIDDAY": "📊 <b>[장중 시황 브리핑 12:30]</b>",
        "CLOSE": "📘 <b>[장마감 브리핑 15:40]</b>",
    }.get(slot_name, "📰 <b>[뉴스 브리핑]</b>")


def _persona_line(slot_name: str) -> str:
    return {
        "MORNING": "페르소나: 수석 매크로 애널리스트 + 헤드 트레이더",
        "MIDDAY": "페르소나: 수석 섹터 애널리스트 + 플로어 트레이더",
        "CLOSE": "페르소나: 탑티어 클로징 애널리스트 + 헤드 트레이더",
    }.get(slot_name, "페르소나: 탑급 애널리스트")


def _build_morning_message(analysis: dict) -> str:
    sentiment_label = _sentiment_label(str(analysis.get("market_sentiment", "NEUTRAL")))
    us_market = _normalize_lines(analysis.get("us_market_points", []), 3)
    us_sector = _normalize_lines(analysis.get("us_sector_points", []), 3)
    macro_points = _normalize_lines(analysis.get("macro_points", []), 3)
    sectors = _normalize_lines(analysis.get("recommended_sectors", []), 4)
    risk_factors = _normalize_lines(analysis.get("risk_factors", []), 3)

    lines = [
        _slot_header("MORNING"),
        _persona_line("MORNING"),
        "",
        f"시장 온도: <b>{sentiment_label}</b>",
    ]

    if us_market:
        lines.extend(["", "<b>1) 전일 미 3대지수</b>"])
        lines.extend([f"• {item}" for item in us_market])

    if us_sector:
        lines.extend(["", "<b>2) 미국 주도/부진 섹터</b>"])
        lines.extend([f"• {item}" for item in us_sector])

    if macro_points:
        lines.extend(["", "<b>3) 외부 변수</b>"])
        lines.extend([f"• {item}" for item in macro_points])

    outlook = str(analysis.get("korea_outlook", "") or "").strip()
    if outlook:
        lines.extend(["", "<b>4) 오늘 국장 예상 흐름</b>", outlook])

    if sectors:
        lines.extend(["", f"<b>5) 오늘 볼 섹터</b>\n{', '.join(sectors)}"])

    if risk_factors:
        lines.extend(["", "<b>체크 리스크</b>"])
        lines.extend([f"• {item}" for item in risk_factors])

    summary = str(analysis.get("summary", "") or "").strip()
    if summary:
        lines.extend(["", f"<b>한 줄 결론</b>\n{summary}"])

    return "\n".join(lines).strip()


def _build_midday_message(analysis: dict) -> str:
    sentiment_label = _sentiment_label(str(analysis.get("market_sentiment", "NEUTRAL")))
    midday_sectors = _normalize_lines(analysis.get("midday_sectors", []), 4)
    sectors = midday_sectors or _normalize_lines(analysis.get("recommended_sectors", []), 4)
    risk_factors = _normalize_lines(analysis.get("risk_factors", []), 3)
    index_commentary = str(analysis.get("midday_index_commentary", "") or "").strip()
    recap = str(analysis.get("midday_recap", "") or "").strip()
    outlook = str(analysis.get("afternoon_outlook", "") or "").strip()

    lines = [
        _slot_header("MIDDAY"),
        _persona_line("MIDDAY"),
        "",
        f"시장 온도: <b>{sentiment_label}</b>",
    ]

    if sectors:
        lines.extend(["", f"<b>1) 오전장 주도 섹터</b>\n{', '.join(sectors)}"])

    if index_commentary:
        lines.extend(["", "<b>2) 코스피 / 코스닥 흐름</b>", index_commentary])

    if recap:
        lines.extend(["", "<b>3) 오전장 복기</b>", recap])

    if outlook:
        lines.extend(["", "<b>4) 오후장 예상</b>", outlook])

    if risk_factors:
        lines.extend(["", "<b>체크 리스크</b>"])
        lines.extend([f"• {item}" for item in risk_factors])

    summary = str(analysis.get("summary", "") or "").strip()
    if summary:
        lines.extend(["", f"<b>한 줄 결론</b>\n{summary}"])

    return "\n".join(lines).strip()


def _build_close_message(analysis: dict) -> str:
    sentiment_label = _sentiment_label(str(analysis.get("market_sentiment", "NEUTRAL")))
    leaders = _normalize_lines(analysis.get("close_leaders", []), 4)
    risk_factors = _normalize_lines(analysis.get("risk_factors", []), 3)
    close_flow = str(analysis.get("close_flow", "") or "").strip()
    tomorrow_watch = str(analysis.get("tomorrow_watch", "") or "").strip()

    lines = [
        _slot_header("CLOSE"),
        _persona_line("CLOSE"),
        "",
        f"시장 온도: <b>{sentiment_label}</b>",
    ]

    if close_flow:
        lines.extend(["", "<b>1) 마감시황</b>", close_flow])

    if leaders:
        lines.extend(["", f"<b>2) 오늘 시장 주도 축</b>\n{', '.join(leaders)}"])

    if tomorrow_watch:
        lines.extend(["", "<b>3) 내일 체크포인트</b>", tomorrow_watch])

    if risk_factors:
        lines.extend(["", "<b>체크 리스크</b>"])
        lines.extend([f"• {item}" for item in risk_factors])

    summary = str(analysis.get("summary", "") or "").strip()
    if summary:
        lines.extend(["", f"<b>한 줄 결론</b>\n{summary}"])

    return "\n".join(lines).strip()


def _build_brief_message(analysis: dict, slot_name: str) -> str:
    if slot_name == "MORNING":
        return _build_morning_message(analysis)
    if slot_name == "MIDDAY":
        return _build_midday_message(analysis)
    if slot_name == "CLOSE":
        return _build_close_message(analysis)
    return _build_morning_message(analysis)


async def _save_to_redis(rdb, analysis: dict) -> None:
    try:
        await rdb.set(_KEY_ANALYSIS, json.dumps(analysis, ensure_ascii=False), ex=_TTL_ANALYSIS)
        await rdb.set(_KEY_SENTIMENT, analysis.get("market_sentiment", "NEUTRAL"), ex=_TTL_ANALYSIS)
        await rdb.set(_KEY_SECTORS, json.dumps(analysis.get("recommended_sectors", []), ensure_ascii=False), ex=_TTL_ANALYSIS)
        logger.info(
            "[NewsScheduler] Redis updated sentiment=%s sectors=%s urgent=%s",
            analysis.get("market_sentiment"),
            analysis.get("recommended_sectors"),
            analysis.get("urgent_news", []),
        )
    except Exception as e:
        logger.error("[NewsScheduler] Redis update failed: %s", e)


async def _load_cached_analysis(rdb) -> dict | None:
    try:
        raw = await rdb.get(_KEY_ANALYSIS)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("[NewsScheduler] cached analysis load failed: %s", e)
        return None


def _resolve_slot_name(slot_name: str | None = None, now: datetime | None = None) -> str:
    normalized = str(slot_name or "").strip().upper()
    if normalized in {"MORNING", "MIDDAY", "CLOSE"}:
        return normalized

    current = _ensure_kst(now)
    current_minutes = current.hour * 60 + current.minute
    if current_minutes < 12 * 60:
        return "MORNING"
    if current_minutes < 15 * 60 + 40:
        return "MIDDAY"
    return "CLOSE"


async def _emit_scheduled_brief(rdb, analysis: dict, slot_name: str, slot_time: tuple[int, int]) -> None:
    payload = {
        "type": "SCHEDULED_NEWS_BRIEF",
        "slot": f"{slot_time[0]:02d}:{slot_time[1]:02d}",
        "slot_name": slot_name,
        "market_sentiment": analysis.get("market_sentiment", "NEUTRAL"),
        "sectors": analysis.get("recommended_sectors", []),
        "urgent_news": analysis.get("urgent_news", []),
        "risk_factors": analysis.get("risk_factors", []),
        "summary": analysis.get("summary", ""),
        "message": _build_brief_message(analysis, slot_name),
        "ts": time.time(),
    }
    await rdb.lpush(_KEY_SCORED_QUEUE, json.dumps(payload, ensure_ascii=False))
    await rdb.expire(_KEY_SCORED_QUEUE, _TTL_ALERT_Q)
    await rdb.set("ops:scheduler:news_scheduler:last_status", "OK", ex=_TTL_ANALYSIS)
    await rdb.set("ops:scheduler:news_scheduler:last_success_at", _now_kst().isoformat(), ex=_TTL_ANALYSIS)
    await rdb.set("ops:scheduler:news_scheduler:last_slot", slot_name, ex=_TTL_ANALYSIS)
    logger.info("[NewsScheduler] scheduled brief published slot=%s", payload["slot"])


async def build_live_brief(rdb, slot_name: str | None = None, publish_queue: bool = False) -> dict:
    resolved_slot = _resolve_slot_name(slot_name)
    slot = next((item for item in _SLOTS if item["name"] == resolved_slot), _SLOTS[0])
    slot_time = tuple(slot["time"])

    news_list = await collect_news(rdb)
    if news_list:
        analysis = await analyze_news(news_list, rdb, slot_name=resolved_slot)
        analysis["news_count"] = len(news_list)
        analysis["analyzed_at"] = time.time()
        analysis["brief_slot"] = resolved_slot
        await _save_to_redis(rdb, analysis)
    else:
        logger.info("[NewsScheduler] live brief using cached analysis slot=%s", resolved_slot)
        analysis = await _load_cached_analysis(rdb)
        if not analysis:
            analysis = {
                "market_sentiment": await rdb.get(_KEY_SENTIMENT) or "NEUTRAL",
                "recommended_sectors": json.loads(await rdb.get(_KEY_SECTORS) or "[]"),
                "urgent_news": [],
                "risk_factors": [],
                "summary": "신규 뉴스가 적어 직전 브리핑과 현재 장 흐름 기준으로 해석합니다.",
                "confidence": "LOW",
                "us_market_points": [],
                "us_sector_points": [],
                "macro_points": [],
                "korea_outlook": "",
                "midday_sectors": [],
                "midday_index_commentary": "",
                "midday_recap": "",
                "afternoon_outlook": "",
                "close_flow": "",
                "close_leaders": [],
                "tomorrow_watch": "",
            }

        analysis["brief_slot"] = resolved_slot
        analysis["analyzed_at"] = analysis.get("analyzed_at", time.time())
        analysis["news_count"] = analysis.get("news_count", 0)

    message = _build_brief_message(analysis, resolved_slot)
    if publish_queue:
        await _emit_scheduled_brief(rdb, analysis, resolved_slot, slot_time)

    return {
        "slot_name": resolved_slot,
        "slot": f"{slot_time[0]:02d}:{slot_time[1]:02d}",
        "analysis": analysis,
        "message": message,
    }


async def run_once(rdb, slot: dict[str, object] | None = None) -> None:
    start = time.time()
    slot = slot or _slot_from_now() or _SLOTS[0]
    slot_name = str(slot["name"])
    slot_time = tuple(slot["time"])
    logger.info("[NewsScheduler] collecting news slot=%s", slot_name)

    try:
        news_list = await collect_news(rdb)
        if not news_list:
            logger.info("[NewsScheduler] no fresh news, using cached analysis for scheduled brief")
            cached = await _load_cached_analysis(rdb)
            if cached:
                await _emit_scheduled_brief(rdb, cached, slot_name, slot_time)
                return

            analysis = {
                "market_sentiment": await rdb.get(_KEY_SENTIMENT) or "NEUTRAL",
                "recommended_sectors": json.loads(await rdb.get(_KEY_SECTORS) or "[]"),
                "urgent_news": [],
                "risk_factors": [],
                "summary": "신규 뉴스가 많지 않아 직전 시장 톤을 이어서 해석합니다.",
                "confidence": "LOW",
                "us_market_points": [],
                "us_sector_points": [],
                "macro_points": [],
                "korea_outlook": "",
                "midday_sectors": [],
                "midday_index_commentary": "",
                "midday_recap": "",
                "afternoon_outlook": "",
                "close_flow": "",
                "close_leaders": [],
                "tomorrow_watch": "",
            }
            await _emit_scheduled_brief(rdb, analysis, slot_name, slot_time)
            return

        analysis = await analyze_news(news_list, rdb, slot_name=slot_name)
        analysis["news_count"] = len(news_list)
        analysis["analyzed_at"] = time.time()
        analysis["brief_slot"] = slot_name

        await _save_to_redis(rdb, analysis)
        await _emit_scheduled_brief(rdb, analysis, slot_name, slot_time)

        elapsed = time.time() - start
        logger.info(
            "[NewsScheduler] done slot=%s %.1fs news=%d sentiment=%s",
            slot_name,
            elapsed,
            len(news_list),
            analysis.get("market_sentiment", "NEUTRAL"),
        )
    except Exception as e:
        logger.error("[NewsScheduler] run error: %s", e)
        try:
            await rdb.set("ops:scheduler:news_scheduler:last_status", "ERROR", ex=_TTL_ANALYSIS)
        except Exception:
            pass


async def run_news_scheduler(rdb) -> None:
    if not NEWS_ENABLED:
        logger.info("[NewsScheduler] disabled")
        return

    schedule_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in [slot["time"] for slot in _SLOTS])
    logger.info("[NewsScheduler] started fixed schedule=%s", schedule_str)

    while True:
        next_info = _next_run_slot()
        next_slot = next_info["slot"]
        next_run = next_info["run_at"]
        delay = (next_run - _now_kst()).total_seconds()
        if delay > 0:
            logger.info(
                "[NewsScheduler] next run %s slot=%s (%.0fs)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                next_slot["name"],
                delay,
            )
            await asyncio.sleep(delay)

        if not _is_weekday():
            await asyncio.sleep(60)
            continue

        await run_once(rdb, next_slot)
        await asyncio.sleep(60)
