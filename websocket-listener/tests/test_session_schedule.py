import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call, patch

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


def test_default_holiday_is_closed():
    import ws_client

    holiday = datetime(2026, 7, 17, 10, 0, tzinfo=KST)
    with patch("ws_client._now_kst", return_value=holiday):
        assert ws_client._get_market_session() == "closed"
        assert ws_client._is_market_hours() is False


@pytest.mark.asyncio
async def test_after_market_subscribes_0b_0d_0w_1h_without_0h():
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    rdb.smembers.return_value = set()
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930", "000660"], ["005930"])
        await ws_client._subscribe_by_phase(ws, rdb, "after_market")

    sent_types = []
    for call in ws.send.call_args_list:
        payload = json.loads(call.args[0])
        if payload["trnm"] == "REG":
            sent_types.extend(payload["data"][0]["type"])

    assert sent_types == ["0B", "0D", "0w", "1h"]


@pytest.mark.asyncio
async def test_pre_market_subscribes_0b_0h_0d_0w_1h():
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    rdb.smembers.return_value = set()
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930", "000660"], ["005930"])
        await ws_client._subscribe_by_phase(ws, rdb, "pre_market")

    sent_types = []
    refresh_values = []
    for call in ws.send.call_args_list:
        payload = json.loads(call.args[0])
        if payload["trnm"] == "REG":
            sent_types.extend(payload["data"][0]["type"])
            refresh_values.append(payload["refresh"])

    assert sent_types == ["0B", "0D", "0w", "0H", "1h"]
    # 그룹 전체 교체는 기존 항목을 먼저 해제하므로 후보 회전 중 순간적인
    # 200종목 초과가 발생하지 않는다.
    assert refresh_values == ["0", "0", "0", "0", "0"]


@pytest.mark.asyncio
async def test_subscribe_by_phase_replaces_changed_group_atomically():
    """변경된 그룹은 refresh=0 스냅샷 한 번으로 교체한다."""
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    # 0B: 이미 "005930"(유지), "999999"(더 이상 미욕구 → REMOVE 대상) 구독 중
    # 0H/0D/0w/1h: 아무것도 구독하지 않은 상태
    rdb.smembers.side_effect = [
        {"005930", "999999"},  # 0B
        set(),                  # 0H
        set(),                  # 0D
        set(),                  # 0w
        set(),                  # 1h
    ]
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930", "000660", "035420"], ["005930", "000660"])
        await ws_client._subscribe_by_phase(ws, rdb, "pre_market")

    reg_payloads_0b = []
    for call in ws.send.call_args_list:
        payload = json.loads(call.args[0])
        if payload["grp_no"] != "1":
            continue
        entry = payload["data"][0]
        if "0B" not in entry["type"]:
            continue
        if payload["trnm"] == "REG":
            reg_payloads_0b.append(payload)

    assert len(reg_payloads_0b) == 1
    assert reg_payloads_0b[0]["refresh"] == "0"
    assert reg_payloads_0b[0]["data"][0]["item"] == ["005930", "000660", "035420"]


@pytest.mark.asyncio
async def test_closed_session_clears_subscriptions_only():
    import ws_client

    ws = AsyncMock()
    rdb = AsyncMock()
    existing = {
        "ws:subscribed:0B:1": {"005930"},
        "ws:subscribed:1h:3": {""},
        "ws:subscribed:0D:4": {"005930"},
        "ws:subscribed:0w:5": {"005930"},
    }
    rdb.smembers.side_effect = lambda key: existing.get(key, set())
    with patch("ws_client._get_ranked_candidates", new_callable=AsyncMock) as ranked, \
         patch("ws_client.asyncio.sleep", new_callable=AsyncMock):
        ranked.return_value = (["005930"], ["005930"])
        await ws_client._subscribe_by_phase(ws, rdb, "post_quiet")

    sent = [json.loads(call.args[0]) for call in ws.send.call_args_list]
    assert [payload["trnm"] for payload in sent] == ["REMOVE", "REMOVE", "REMOVE", "REMOVE"]
    assert [payload["data"][0]["type"][0] for payload in sent] == ["0B", "1h", "0D", "0w"]
    assert all("item" in payload["data"][0] for payload in sent)


@pytest.mark.asyncio
async def test_reset_local_subscription_sets_clears_connection_scoped_state():
    import ws_client

    rdb = AsyncMock()

    await ws_client._reset_local_subscription_sets(rdb)

    keys = [call.args[0] for call in rdb.delete.call_args_list]
    assert "ws:subscribed:0B" in keys
    assert "ws:subscribed:0B:1" in keys
    assert "ws:subscribed:0B:6" in keys
    assert "ws:desired:0B:6" in keys


@pytest.mark.asyncio
async def test_subscription_state_commits_only_after_success_ack():
    import ws_client

    ws_client._pending_ws_controls.clear()
    ws = AsyncMock()
    rdb = AsyncMock()
    rdb.smembers.side_effect = lambda key: {"005930", "000660"} if key == "ws:subscribed:0B:1" else set()
    payload = {
        "trnm": "REG",
        "grp_no": "1",
        "refresh": "0",
        "data": [{"item": ["005930", "000660"], "type": ["0B"]}],
    }

    await ws_client._send_ws_control(ws, payload, full_snapshot=True)
    assert rdb.sadd.await_count == 0

    # Real Kiwoom ACK payloads always echo grp_no="" regardless of the grp_no that was
    # requested; matching must still succeed using this real-world (empty) grp_no.
    await ws_client._apply_ws_control_ack(rdb, "REG", "", "0")
    assert call("ws:subscribed:0B") in rdb.delete.await_args_list
    assert call("ws:subscribed:0B:1") in rdb.delete.await_args_list
    union_call = next(c for c in rdb.sadd.await_args_list if c.args[0] == "ws:subscribed:0B")
    assert set(union_call.args[1:]) == {"005930", "000660"}
    assert call("ws:subscribed:0B:1", "005930", "000660") in rdb.sadd.await_args_list
    rdb.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_wildcard_subscription_is_tracked_after_success_ack():
    import ws_client

    ws_client._pending_ws_controls.clear()
    ws = AsyncMock()
    rdb = AsyncMock()
    rdb.smembers.side_effect = lambda key: {""} if key == "ws:subscribed:1h:3" else set()
    payload = {
        "trnm": "REG",
        "grp_no": "3",
        "refresh": "1",
        "data": [{"item": [""], "type": ["1h"]}],
    }

    await ws_client._send_ws_control(ws, payload)
    await ws_client._apply_ws_control_ack(rdb, "REG", "", "0")

    assert call("ws:subscribed:1h", "") in rdb.sadd.await_args_list
    assert call("ws:subscribed:1h:3", "") in rdb.sadd.await_args_list


def test_main_market_splits_200_tick_candidates_across_two_groups():
    import ws_client

    candidates = [f"{idx:06d}" for idx in range(200)]
    tick_groups = [group for group in ws_client._groups_for_session("main_market", candidates, candidates[:100]) if group[1] == "0B"]

    assert [(group_no, len(items)) for group_no, _, items in tick_groups] == [("1", 100), ("6", 100)]
    assert tick_groups[0][2] + tick_groups[1][2] == candidates


@pytest.mark.asyncio
async def test_failed_subscription_ack_does_not_commit_state():
    import ws_client

    ws_client._pending_ws_controls.clear()
    ws = AsyncMock()
    rdb = AsyncMock()
    payload = {
        "trnm": "REG",
        "grp_no": "1",
        "refresh": "0",
        "data": [{"item": ["005930"], "type": ["0B"]}],
    }

    await ws_client._send_ws_control(ws, payload, full_snapshot=True)
    await ws_client._apply_ws_control_ack(rdb, "REG", "", "105115")

    rdb.delete.assert_not_awaited()
    rdb.sadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_ack_timeout_rejects_operation_without_changing_acked_state():
    import ws_client

    ws_client._pending_ws_controls.clear()
    ws = AsyncMock()
    rdb = AsyncMock()
    payload = {
        "trnm": "REG",
        "grp_no": "1",
        "data": [{"item": ["005930"], "type": ["0B"]}],
    }
    await ws_client._send_ws_control(ws, payload, full_snapshot=True)
    operation = ws_client._pending_ws_controls["REG"][0]
    operation["sent_at_ms"] = 0

    expired = await ws_client._expire_pending_ws_controls(rdb)

    assert len(expired) == 1
    assert expired[0]["item_hash"]
    assert "REG" not in ws_client._pending_ws_controls
    rdb.sadd.assert_not_awaited()
    rdb.hset.assert_awaited()


@pytest.mark.asyncio
async def test_multi_group_ack_with_blank_grp_no_all_commit_without_timeout():
    """Regression test for the 2026-07-27 production incident.

    Kiwoom's REG/REMOVE ACK responses always echo grp_no="" (verified against
    production logs), never the grp_no that was actually requested. Before the fix,
    the pending-operation queue was keyed by (trnm, grp_no), so a real, immediate,
    successful ACK from Kiwoom (grp_no="") could never match the operations queued
    under keys like ("REG", "1"), ("REG", "3"), ("REG", "4"), ("REG", "5"). Every
    REG/REMOVE across every group therefore fell through to the 10s ACK-timeout path
    100% of the time despite Kiwoom having answered instantly.
    """
    import ws_client

    ws_client._pending_ws_controls.clear()
    ws = AsyncMock()
    rdb = AsyncMock()

    groups = [
        ("1", "0B", ["005930"]),
        ("4", "0D", ["005930"]),
        ("5", "0w", ["005930"]),
        ("3", "1h", [""]),
    ]
    for grp_no, ttype, items in groups:
        payload = {
            "trnm": "REG",
            "grp_no": grp_no,
            "refresh": "1",
            "data": [{"item": items, "type": [ttype]}],
        }
        await ws_client._send_ws_control(ws, payload, full_snapshot=False)

    # Kiwoom answers every request immediately and successfully, but always with an
    # empty grp_no, in the exact order the requests were sent (FIFO over the single
    # serialized connection).
    for _ in groups:
        await ws_client._apply_ws_control_ack(rdb, "REG", "", "0")

    # No operation should be left pending, so the 10s watcher has nothing left to
    # expire -- i.e. no ACK_TIMEOUT should ever fire for these operations.
    assert "REG" not in ws_client._pending_ws_controls
    expired = await ws_client._expire_pending_ws_controls(rdb)
    assert expired == []


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


@pytest.mark.asyncio
async def test_subscription_ack_is_exposed_in_health():
    import health_server

    health_server._subscription_ack = {}
    health_server.record_subscription_ack("REG", "1", "0", "")
    response = await health_server._health_handler(None)
    body = json.loads(response.text)

    assert body["websocket"]["subscription_ack"]["1"]["trnm"] == "REG"
    assert body["websocket"]["subscription_ack"]["1"]["return_code"] == "0"


@pytest.mark.asyncio
async def test_closed_session_is_healthy_but_trading_not_applicable():
    import health_server

    health_server._rdb = AsyncMock()
    health_server._rdb.ping.return_value = True
    health_server._rdb.llen.return_value = 0
    health_server.set_ws_connected(False, "session_closed")
    health_server.set_ws_session("closed")

    health = await health_server._health_handler(None)
    ready = await health_server._ready_handler(None)
    body = json.loads(health.text)

    assert body["status"] == "UP"
    assert body["trading_readiness"]["status"] == "NOT_APPLICABLE"
    assert ready.status == 200
