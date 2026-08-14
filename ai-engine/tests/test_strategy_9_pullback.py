import os
import sys
import importlib
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_s9_reads_strategy_owned_candidate_pool_when_available(monkeypatch):
    monkeypatch.setenv("S9_POOL_READ_LIMIT", "180")
    import strategy_9_pullback
    strategy_9_pullback = importlib.reload(strategy_9_pullback)

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[[], []])

    result = await strategy_9_pullback.scan_pullback_swing("token", rdb=rdb)

    assert result == []
    assert rdb.lrange.await_args_list[0].args == ("candidates:s9:001", 0, 179)
    assert rdb.lrange.await_args_list[1].args == ("candidates:s9:101", 0, 179)


def _s9_candles():
    return [
        {
            "cur_prc": "105" if idx == 0 else "100",
            "open_pric": "100",
            "high_pric": "107" if idx == 0 else "102",
            "low_pric": "98",
            "trde_qty": "400" if idx == 0 else "1000",
        }
        for idx in range(62)
    ]


async def _scan_s9_with_volume_meta(monkeypatch, meta):
    import strategy_9_pullback as s9

    rdb = AsyncMock()

    async def lrange(key, start, end):
        if key == "candidates:s9:001":
            return ["005930"]
        return []

    rdb.lrange = AsyncMock(side_effect=lrange)
    rdb.hgetall = AsyncMock(return_value={
        "flu_rt": "2.0",
        "cntr_str": "120",
        "updated_at_ms": str(int(time.time() * 1000)),
    })
    rdb.get = AsyncMock(return_value=None)

    tp_sl = MagicMock()
    tp_sl.to_signal_fields.return_value = {"rr_ratio": 1.8}
    monkeypatch.setattr(s9.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s9, "fetch_daily_candles", AsyncMock(return_value=_s9_candles()))
    monkeypatch.setattr(s9, "detect_pullback_setup", lambda candles: (True, 0.5, 3.0))
    monkeypatch.setattr(s9, "calc_rsi", lambda *args: [50.0])
    monkeypatch.setattr(s9, "calc_stochastic", lambda *args: ([30.0, 20.0], [25.0, 25.0]))
    monkeypatch.setattr(s9, "fetch_hoga", AsyncMock(return_value=1.3))
    monkeypatch.setattr(s9, "fetch_stk_nm", AsyncMock(return_value="삼성전자"))
    monkeypatch.setattr(s9, "calc_tp_sl", MagicMock(return_value=tp_sl))
    monkeypatch.setattr(
        s9,
        "fetch_same_time_volume_ratio_cached",
        AsyncMock(return_value=({"same_time_volume_ratio": 1.5}, meta)),
    )
    return await s9.scan_pullback_swing("token", rdb=rdb)


@pytest.mark.asyncio
async def test_s9_uses_complete_same_time_ratio_for_volume_gate(monkeypatch):
    result = await _scan_s9_with_volume_meta(
        monkeypatch,
        {"api_id": "ka10055", "complete": True},
    )

    assert len(result) == 1
    assert result[0]["daily_volume_ratio"] == 0.4
    assert result[0]["vol_ratio"] == 1.5
    assert result[0]["volume_ratio_source"] == "ka10055_same_time"


@pytest.mark.asyncio
async def test_s9_rejects_incomplete_same_time_ratio_and_keeps_daily_gate(monkeypatch):
    result = await _scan_s9_with_volume_meta(
        monkeypatch,
        {"api_id": "ka10055", "complete": False},
    )

    assert result == []
