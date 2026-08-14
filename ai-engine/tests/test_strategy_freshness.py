from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_realtime_reader_suppresses_cancelled_tick():
    from redis_reader import get_tick_with_status

    rdb = AsyncMock()
    rdb.hgetall = AsyncMock(return_value={
        "cur_prc": "50000",
        "flu_rt": "12.0",
        "cntr_str": "300",
        "updated_at_ms": "1000",
    })

    result = await get_tick_with_status(rdb, "005930", now_ms=7001)

    assert result["status"]["state"] == "cancel"
    assert result["source"] == "stale"
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_realtime_reader_allows_caution_hoga():
    from redis_reader import get_hoga_with_status

    rdb = AsyncMock()
    rdb.hgetall = AsyncMock(return_value={
        "total_buy_bid_req": "2000",
        "total_sel_bid_req": "1000",
        "updated_at_ms": "1000",
    })

    result = await get_hoga_with_status(rdb, "005930", now_ms=2500)

    assert result["status"]["state"] == "caution"
    assert result["source"] == "redis"
    assert result["data"]["total_buy_bid_req"] == "2000"


@pytest.mark.asyncio
async def test_strength_reader_does_not_read_samples_when_meta_is_cancelled():
    from redis_reader import get_strength_with_status

    rdb = AsyncMock()
    rdb.hgetall = AsyncMock(return_value={"updated_at_ms": "1000"})
    rdb.lrange = AsyncMock(return_value=["300", "300", "300"])

    result = await get_strength_with_status(rdb, "005930", now_ms=12001)

    assert result["status"]["state"] == "cancel"
    assert result["data"] is None
    assert result["source"] == "stale"
    rdb.lrange.assert_not_awaited()


@pytest.mark.asyncio
async def test_s1_cancelled_strength_uses_rest_fallback(monkeypatch):
    import strategy_1_gap_opening as s1

    monkeypatch.setattr(
        s1,
        "get_strength_with_status",
        AsyncMock(return_value={
            "data": None,
            "source": "stale",
            "status": {"state": "cancel"},
        }),
    )
    monkeypatch.setattr(s1, "fetch_cntr_strength", AsyncMock(return_value=132.0))
    monkeypatch.setattr(s1.asyncio, "sleep", AsyncMock())

    value, source = await s1._get_strength_value("token", "005930", rdb=AsyncMock())

    assert value == 132.0
    assert source == "rest"


@pytest.mark.asyncio
async def test_s2_cancelled_strong_tick_cannot_pass_price_gate(monkeypatch):
    import strategy_2_vi_pullback as s2

    rdb = AsyncMock()
    rdb.hgetall = AsyncMock(return_value={
        "cur_prc": "9800",
        "cntr_str": "300",
        "updated_at_ms": "1000",
    })
    monkeypatch.setattr(
        s2,
        "get_tick_with_status",
        AsyncMock(return_value={
            "data": {},
            "source": "stale",
            "status": {"state": "cancel"},
        }),
    )

    result = await s2.check_vi_pullback(
        "token",
        {"stk_cd": "005930", "vi_price": 10000},
        rdb,
    )

    assert result is None


@pytest.mark.asyncio
async def test_s10_cancelled_strong_tick_is_not_replaced_by_expected(monkeypatch):
    import strategy_10_new_high as s10

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], []])
    rdb.hgetall = AsyncMock(return_value={
        "exp_flu_rt": "14.0",
        "exp_cntr_pric": "50000",
    })
    monkeypatch.setattr(s10, "fetch_volume_surge_map_all", AsyncMock(return_value={"005930": 500.0}))
    monkeypatch.setattr(
        s10,
        "get_tick_with_status",
        AsyncMock(return_value={
            "data": {},
            "source": "stale",
            "status": {"state": "cancel"},
        }),
    )

    result = await s10.scan_new_high_swing("token", rdb=rdb)

    assert result == []
    rdb.hgetall.assert_not_awaited()


@pytest.mark.asyncio
async def test_s13_cancelled_strong_tick_cannot_pass_momentum_gate(monkeypatch):
    import strategy_13_box_breakout as s13

    candles = [
        {
            "cur_prc": "110" if idx == 0 else "100",
            "open_pric": "100",
            "high_pric": "112" if idx == 0 else "102",
            "low_pric": "98",
            "trde_qty": "5000" if idx == 0 else "1000",
        }
        for idx in range(130)
    ]
    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], []])
    monkeypatch.setattr(s13.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s13, "fetch_daily_candles", AsyncMock(return_value=candles))
    monkeypatch.setattr(s13, "detect_box_breakout", lambda *args, **kwargs: (True, 5.0))
    monkeypatch.setattr(s13, "calc_bollinger", lambda *args, **kwargs: [])
    monkeypatch.setattr(s13, "calc_mfi", lambda *args, **kwargs: [])
    monkeypatch.setattr(s13, "calc_rsi", lambda *args, **kwargs: [55.0])
    monkeypatch.setattr(
        s13,
        "get_tick_with_status",
        AsyncMock(return_value={
            "data": {},
            "source": "stale",
            "status": {"state": "cancel"},
        }),
    )

    result = await s13.scan_box_breakout("token", rdb=rdb)

    assert result == []


@pytest.mark.asyncio
async def test_s11_cancelled_strong_tick_uses_weak_safe_fallback(monkeypatch):
    import strategy_11_frgn_cont as s11

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(return_value=[])
    raw_items = [{
        "stk_cd": "005930",
        "cur_prc": "10100",
        "dm1": "1000000",
        "dm2": "900000",
        "dm3": "800000",
        "tot": "2700000",
    }]
    stale_tick = {
        "data": {},
        "source": "stale",
        "status": {"state": "cancel"},
    }
    weak_strength = AsyncMock(return_value=(90.0, "rest"))
    monkeypatch.setattr(s11.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s11, "fetch_frgn_cont_buy", AsyncMock(return_value=raw_items))
    monkeypatch.setattr(s11, "get_tick_with_status", AsyncMock(return_value=stale_tick))
    monkeypatch.setattr(
        s11,
        "fetch_daily_candles",
        AsyncMock(return_value=[{"cur_prc": "10100", "open_pric": "10000"}]),
    )
    monkeypatch.setattr(s11, "fetch_cntr_strength_cached", weak_strength)

    result = await s11.scan_frgn_cont_swing("token", rdb=rdb)

    assert result == []
    weak_strength.assert_awaited_once()


@pytest.mark.asyncio
async def test_s14_cancelled_strong_tick_cannot_pass_strength_gate(monkeypatch):
    import strategy_14_oversold_bounce as s14

    candles = [
        {"cur_prc": "10000", "high_pric": "10200", "low_pric": "9800", "trde_qty": "500000"}
        for _ in range(65)
    ]
    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], []])
    stale_tick = {
        "data": {},
        "source": "stale",
        "status": {"state": "cancel"},
    }
    weak_strength = AsyncMock(return_value=(98.0, "rest"))
    monkeypatch.setattr(s14.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s14, "fetch_daily_candles", AsyncMock(return_value=candles))
    monkeypatch.setattr(s14, "calc_rsi", lambda *args, **kwargs: [30.0, 29.0])
    monkeypatch.setattr(s14, "calc_atr", lambda *args, **kwargs: [150.0] * 20)
    monkeypatch.setattr(s14, "get_tick_with_status", AsyncMock(return_value=stale_tick))
    monkeypatch.setattr(s14, "fetch_cntr_strength_cached", weak_strength)

    result = await s14.scan_oversold_bounce("token", rdb=rdb)

    assert result == []
    weak_strength.assert_awaited_once()


@pytest.mark.asyncio
async def test_s15_cancelled_strong_realtime_values_do_not_raise_score(monkeypatch):
    import strategy_15_momentum_align as s15

    candles = [{
        "cur_prc": "101",
        "open_pric": "100",
        "high_pric": "102",
        "low_pric": "99",
        "trde_qty": "2000",
    }] + [{
        "cur_prc": "100",
        "open_pric": "100",
        "high_pric": "102",
        "low_pric": "99",
        "trde_qty": "1000",
    } for _ in range(39)]
    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], []])
    stale_tick = {"data": {}, "source": "stale", "status": {"state": "cancel"}}
    stale_strength = {"data": None, "source": "stale", "status": {"state": "cancel"}}
    safe_strength = AsyncMock(return_value=(100.0, "rest"))
    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {}

    monkeypatch.setattr(s15.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s15, "fetch_daily_candles", AsyncMock(return_value=candles))
    monkeypatch.setattr(s15, "get_tick_with_status", AsyncMock(return_value=stale_tick))
    monkeypatch.setattr(s15, "get_strength_with_status", AsyncMock(return_value=stale_strength))
    monkeypatch.setattr(s15, "fetch_cntr_strength_cached", safe_strength)
    monkeypatch.setattr(s15, "calc_rsi", lambda *args, **kwargs: [55.0, 54.0])
    monkeypatch.setattr(s15, "calc_macd", lambda *args, **kwargs: ([2.0, 1.0], [1.0, 1.0], [1.0, 0.5, 0.2]))
    monkeypatch.setattr(s15, "calc_bollinger", lambda *args, **kwargs: [(120.0, 100.0, 80.0)])
    monkeypatch.setattr(s15, "calc_atr", lambda *args, **kwargs: [2.0])
    monkeypatch.setattr(s15, "calc_stochastic", lambda *args, **kwargs: ([60.0], [50.0]))
    monkeypatch.setattr(s15, "get_vwap_minute", AsyncMock(return_value=SimpleNamespace(vwap=90.0)))
    monkeypatch.setattr(s15, "calc_tp_sl", MagicMock(return_value=fake_tp_sl))
    monkeypatch.setattr(s15, "fetch_stk_nm", AsyncMock(return_value="test"))

    result = await s15.scan_momentum_align("token", rdb=rdb)

    assert len(result) == 1
    assert result[0]["cntr_strength"] == 100.0
    assert result[0]["score"] == 83.6
    safe_strength.assert_awaited_once()
