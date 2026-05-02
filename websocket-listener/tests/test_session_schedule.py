import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

KST = timezone(timedelta(hours=9))


def _kst(hour: int, minute: int, second: int = 0, weekday: int = 0) -> datetime:
    now = datetime.now(KST)
    days_diff = (weekday - now.weekday()) % 7
    base = now + timedelta(days=days_diff)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


@pytest.mark.parametrize(
    "hour,minute,second,expected",
    [
        (7, 29, 59, "closed"),
        (7, 30, 0, "closed"),
        (7, 59, 59, "closed"),
        (8, 0, 0, "pre_market"),
        (8, 50, 0, "opening_auction"),
        (9, 0, 29, "opening_auction"),
        (9, 0, 30, "main_market"),
        (15, 20, 0, "closing_auction"),
        (15, 30, 0, "after_preopen"),
        (15, 40, 0, "after_market"),
        (19, 59, 59, "after_market"),
        (20, 0, 0, "post_quiet"),
        (20, 10, 0, "closed"),
    ],
)
def test_market_session_boundaries(hour, minute, second, expected):
    import ws_client

    with patch("ws_client._now_kst", return_value=_kst(hour, minute, second)):
        assert ws_client._get_market_session() == expected


def test_early_connect_window_is_separate_from_market_session():
    import ws_client

    with patch("ws_client._now_kst", return_value=_kst(7, 30)):
        assert ws_client._get_market_session() == "closed"
        assert ws_client._is_early_connect_window() is True
        assert ws_client._is_market_hours() is True

    with patch("ws_client._now_kst", return_value=_kst(8, 0)):
        assert ws_client._get_market_session() == "pre_market"
        assert ws_client._is_early_connect_window() is False
        assert ws_client._is_market_hours() is True


@pytest.mark.parametrize("weekday", [5, 6])
def test_weekend_is_closed(weekday):
    import ws_client

    with patch("ws_client._now_kst", return_value=_kst(10, 0, weekday=weekday)):
        assert ws_client._get_market_session() == "closed"
        assert ws_client._is_market_hours() is False


@pytest.mark.asyncio
async def test_after_market_subscribes_0b_0d_1h_without_0h():
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930", "000660"], ["005930"])
        await ws_client._subscribe_by_phase(ws, rdb, "after_market")

    sent_types = []
    for call in ws.send.call_args_list:
        payload = json.loads(call.args[0])
        if payload["trnm"] == "REG":
            sent_types.extend(payload["data"][0]["type"])

    assert sent_types == ["0B", "0D", "1h"]


@pytest.mark.asyncio
async def test_pre_market_subscribes_0b_0h_0d_1h():
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930", "000660"], ["005930"])
        await ws_client._subscribe_by_phase(ws, rdb, "pre_market")

    sent_types = []
    for call in ws.send.call_args_list:
        payload = json.loads(call.args[0])
        if payload["trnm"] == "REG":
            sent_types.extend(payload["data"][0]["type"])

    assert sent_types == ["0B", "0H", "0D", "1h"]


@pytest.mark.asyncio
async def test_closed_session_clears_subscriptions_only():
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930"], ["005930"])
        await ws_client._subscribe_by_phase(ws, rdb, "post_quiet")

    trnms = [json.loads(call.args[0])["trnm"] for call in ws.send.call_args_list]
    assert trnms == ["UNREG", "UNREG", "UNREG", "UNREG"]


def test_expected_silent_close_after_2000_sessions():
    import ws_client

    assert ws_client._is_expected_silent_close("post_quiet", 1000) is True
    assert ws_client._is_expected_silent_close("closed", 1001) is True
    assert ws_client._is_expected_silent_close("after_market", 1000) is False


@pytest.mark.asyncio
async def test_health_session_is_feature_flagged_off_by_default():
    import health_server

    health_server.EXPOSE_WS_SESSION = False
    health_server.set_ws_session("main_market")
    response = await health_server._health_handler(None)
    body = json.loads(response.text)

    assert "session" not in body["websocket"]


@pytest.mark.asyncio
async def test_health_session_can_be_exposed_with_flag():
    import health_server

    health_server.EXPOSE_WS_SESSION = True
    health_server.set_ws_session("after_market")
    response = await health_server._health_handler(None)
    body = json.loads(response.text)

    assert body["websocket"]["session"] == "after_market"
    health_server.EXPOSE_WS_SESSION = False
