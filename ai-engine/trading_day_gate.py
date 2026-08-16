"""Authoritative Korean trading-day gate shared through Redis.

The Java service publishes Toss market-calendar results as OPEN/CLOSED. Token-consuming
scheduled jobs fail closed when that value is missing; this prevents an outage or a
late startup from accidentally spending news/AI tokens on a holiday.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
KEY_PREFIX = "market:kr:calendar:"


async def scheduled_market_status(rdb, now: datetime | None = None) -> str:
    current = now.astimezone(KST) if now else datetime.now(KST)
    if current.weekday() >= 5:
        return "CLOSED"
    value = await rdb.get(f"{KEY_PREFIX}{current.date().isoformat()}")
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if value in {"OPEN", "CLOSED"}:
        return value
    return "UNKNOWN"
