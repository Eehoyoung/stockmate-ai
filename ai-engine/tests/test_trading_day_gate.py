import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from trading_day_gate import scheduled_market_status


class FakeRedis:
    def __init__(self, value=None):
        self.value = value

    async def get(self, _key):
        return self.value


KST = ZoneInfo("Asia/Seoul")


def test_uses_toss_closed_status_for_weekday():
    now = datetime(2026, 8, 17, 8, 0, tzinfo=KST)
    assert asyncio.run(scheduled_market_status(FakeRedis("CLOSED"), now)) == "CLOSED"


def test_unknown_weekday_fails_closed_at_caller():
    now = datetime(2026, 8, 18, 8, 0, tzinfo=KST)
    assert asyncio.run(scheduled_market_status(FakeRedis(), now)) == "UNKNOWN"


def test_weekend_needs_no_redis_calendar():
    now = datetime(2026, 8, 16, 8, 0, tzinfo=KST)
    assert asyncio.run(scheduled_market_status(FakeRedis("OPEN"), now)) == "CLOSED"
