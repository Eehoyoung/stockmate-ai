import logging
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_scan_big_candle_reads_s4_pool_from_both_markets(monkeypatch):
    import strategy_4_big_candle as s4

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], ["068270"]])

    monkeypatch.setattr(s4, "check_big_candle", AsyncMock(return_value=None))
    monkeypatch.setattr(s4.asyncio, "sleep", AsyncMock())

    result = await s4.scan_big_candle("token", rdb=rdb)

    assert result == []
    assert rdb.lrange.await_args_list[0].args[0] == "candidates:s4:001"
    assert rdb.lrange.await_args_list[1].args[0] == "candidates:s4:101"


@pytest.mark.asyncio
async def test_scan_big_candle_returns_empty_without_pool(monkeypatch):
    import strategy_4_big_candle as s4

    check_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(s4, "check_big_candle", check_mock)

    result = await s4.scan_big_candle("token", rdb=None)

    assert result == []
    check_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_big_candle_logs_scan_summary_even_when_pass_zero(monkeypatch, caplog):
    """운영 관측성 회귀 테스트: 스캔 사이클이 0건을 반환해도
    [S4][scan_summary] INFO 로그가 항상 찍혀야 한다."""
    import strategy_4_big_candle as s4

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930", "068270"], []])

    monkeypatch.setattr(s4, "check_big_candle", AsyncMock(return_value=None))
    monkeypatch.setattr(s4.asyncio, "sleep", AsyncMock())

    with caplog.at_level(logging.INFO, logger="strategy_4_big_candle"):
        result = await s4.scan_big_candle("token", rdb=rdb)

    assert result == []
    summary_logs = [r for r in caplog.records if "[S4][scan_summary]" in r.message]
    assert len(summary_logs) == 1
    assert "candidate_count=2" in summary_logs[0].message
    assert "evaluated=2" in summary_logs[0].message
    assert "pass=0" in summary_logs[0].message


@pytest.mark.asyncio
async def test_scan_big_candle_no_candidates_logs_summary(caplog):
    import strategy_4_big_candle as s4

    with caplog.at_level(logging.INFO, logger="strategy_4_big_candle"):
        result = await s4.scan_big_candle("token", rdb=None)

    assert result == []
    summary_logs = [r for r in caplog.records if "[S4][scan_summary]" in r.message]
    assert len(summary_logs) == 1
    assert "candidate_count=0" in summary_logs[0].message


@pytest.mark.asyncio
async def test_scan_big_candle_stops_at_signal_limit(monkeypatch):
    import strategy_4_big_candle as s4

    monkeypatch.setattr(s4, "_S4_SIGNAL_LIMIT", 1)
    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930", "068270", "000660"], []])

    fake_signal = {"stk_cd": "005930", "strategy": "S4_BIG_CANDLE"}
    check_mock = AsyncMock(return_value=fake_signal)
    monkeypatch.setattr(s4, "check_big_candle", check_mock)
    monkeypatch.setattr(s4.asyncio, "sleep", AsyncMock())

    result = await s4.scan_big_candle("token", rdb=rdb)

    assert result == [fake_signal]
    assert check_mock.await_count == 1
