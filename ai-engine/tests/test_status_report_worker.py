import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from status_report_worker import KST, _next_report_slot


def kst_datetime(year, month, day, hour, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=KST)


def test_next_report_slot_same_day_next_slot():
    now = kst_datetime(2026, 4, 20, 9, 1, 0)  # Monday
    assert _next_report_slot(now) == kst_datetime(2026, 4, 20, 12, 0, 0)


def test_next_report_slot_from_before_market_open():
    now = kst_datetime(2026, 4, 20, 8, 30, 0)  # Monday
    assert _next_report_slot(now) == kst_datetime(2026, 4, 20, 12, 0, 0)


def test_next_report_slot_after_last_slot_moves_to_next_business_day():
    now = kst_datetime(2026, 4, 20, 15, 0, 1)  # Monday
    assert _next_report_slot(now) == kst_datetime(2026, 4, 20, 15, 40, 0)


def test_next_report_slot_on_friday_after_close_skips_weekend():
    now = kst_datetime(2026, 4, 17, 16, 0, 0)  # Friday
    assert _next_report_slot(now) == kst_datetime(2026, 4, 20, 8, 30, 0)


def test_next_report_slot_on_weekend_skips_to_monday():
    now = kst_datetime(2026, 4, 18, 11, 0, 0)  # Saturday
    assert _next_report_slot(now) == kst_datetime(2026, 4, 20, 8, 30, 0)


def test_status_windows_match_final_runner_policy():
    from datetime import time
    from status_report_worker import STRATEGY_WINDOWS

    assert "S2_VI_PULLBACK" not in STRATEGY_WINDOWS
    assert STRATEGY_WINDOWS["S4_BIG_CANDLE"] == (time(10, 0), time(14, 30))
    assert STRATEGY_WINDOWS["S10_NEW_HIGH"] == (time(10, 0), time(14, 0))
    assert STRATEGY_WINDOWS["S11_FRGN_CONT"] == (time(10, 0), time(14, 30))
    assert STRATEGY_WINDOWS["S13_BOX_BREAKOUT"] == (time(10, 0), time(14, 0))


def test_status_pool_keys_match_strategy_owned_s9_policy():
    from status_report_worker import POOL_KEYS

    assert "S2_VI_PULLBACK" not in POOL_KEYS
    assert POOL_KEYS["S9_PULLBACK_SWING"] == ["candidates:s9:001", "candidates:s9:101"]


def test_s2_worker_status_is_loaded_from_redis_hash():
    from status_report_worker import _get_s2_worker_status

    rdb = AsyncMock()
    rdb.hgetall = AsyncMock(return_value={"last_event": "published"})

    result = asyncio.get_event_loop().run_until_complete(_get_s2_worker_status(rdb))

    assert result == {"last_event": "published"}
    rdb.hgetall.assert_awaited_once_with("status:s2_vi_watch_worker")


def test_published_status_report_has_distinct_logical_slot():
    from status_report_worker import _publish_status_report

    rdb = AsyncMock()
    rdb.llen.return_value = 0
    rdb.hgetall.return_value = {}
    rdb.type.return_value = "none"
    rdb.get.return_value = None
    rdb.keys.return_value = []
    report_time = kst_datetime(2026, 8, 3, 12, 0, 0)

    with patch("status_report_worker.datetime") as dt:
        dt.now.return_value = report_time
        asyncio.get_event_loop().run_until_complete(_publish_status_report(rdb))

    payload = json.loads(rdb.lpush.await_args.args[1])
    assert payload["type"] == "STATUS_REPORT"
    assert payload["logical_slot"] == "12:00"
    assert payload["timestamp"].startswith("2026-08-03T12:00:00")
