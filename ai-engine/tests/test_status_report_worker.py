from datetime import datetime, timezone, timedelta

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
