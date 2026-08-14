import logging
import os
import sys
import importlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_s7_scan_summary_logged_even_when_pass_zero(monkeypatch, caplog):
    """운영 관측성 회귀 테스트: 후보가 있어도 전부 탈락(pass=0)하면
    [S7][scan_summary] INFO 로그가 사유와 함께 항상 찍혀야 한다."""
    import strategy_7_ichimoku_breakout as s7

    rdb = AsyncMock()

    async def lrange(key, start, end):
        if key == "candidates:s7:001":
            return ["005930"]
        return []

    rdb.lrange = AsyncMock(side_effect=lrange)
    monkeypatch.setattr(s7.asyncio, "sleep", AsyncMock())
    # 일봉 부족 → daily_bars_insufficient 사유로 탈락
    monkeypatch.setattr(s7, "fetch_daily_candles", AsyncMock(return_value=[]))

    with caplog.at_level(logging.INFO, logger="strategy_7_ichimoku_breakout"):
        result = await s7.scan_ichimoku_breakout("token", rdb=rdb)

    assert result == []
    summary_logs = [r for r in caplog.records if "[S7][scan_summary]" in r.message]
    assert len(summary_logs) == 1
    msg = summary_logs[0].message
    assert "candidate_count=1" in msg
    assert "evaluated=1" in msg
    assert "pass=0" in msg
    assert "daily_bars_insufficient" in msg


@pytest.mark.asyncio
async def test_s7_reads_expanded_strategy_owned_candidate_pool_when_available(monkeypatch):
    monkeypatch.setenv("S7_POOL_READ_LIMIT", "180")
    import strategy_7_ichimoku_breakout
    strategy_7_ichimoku_breakout = importlib.reload(strategy_7_ichimoku_breakout)

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[[], []])

    result = await strategy_7_ichimoku_breakout.scan_ichimoku_breakout("token", rdb=rdb)

    assert result == []
    assert rdb.lrange.await_args_list[0].args == ("candidates:s7:001", 0, 179)
    assert rdb.lrange.await_args_list[1].args == ("candidates:s7:101", 0, 179)


@pytest.mark.asyncio
async def test_s7_uses_complete_same_time_ratio_for_volume_condition(monkeypatch):
    import strategy_7_ichimoku_breakout as s7

    candles = [
        {
            "cur_prc": "110" if idx == 0 else "100",
            "open_pric": "100",
            "high_pric": "112" if idx == 0 else "102",
            "low_pric": "98",
            "trde_qty": "400" if idx == 0 else "1000",
        }
        for idx in range(80)
    ]
    ichi = SimpleNamespace(
        price_above_cloud=True,
        tenkan_above_kijun=True,
        is_bullish_cloud=True,
        chikou_above_price=False,
        kijun_rising=False,
        cloud_thickness_pct=1.0,
        cloud_top=90.0,
        cloud_bottom=85.0,
        tenkan=105.0,
        kijun=100.0,
    )
    rdb = AsyncMock()

    async def lrange(key, start, end):
        if key == "candidates:s7:001":
            return ["005930"]
        if key == "ws:strength:005930":
            return ["120"]
        return []

    rdb.lrange = AsyncMock(side_effect=lrange)
    rdb.hgetall = AsyncMock(return_value={
        "flu_rt": "3.0",
        "updated_at_ms": str(int(time.time() * 1000)),
    })

    tp_sl = MagicMock()
    tp_sl.to_signal_fields.return_value = {"rr_ratio": 1.8}
    monkeypatch.setattr(s7.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s7, "fetch_daily_candles", AsyncMock(return_value=candles))
    monkeypatch.setattr(s7, "calc_ichimoku", lambda *args: ichi)
    monkeypatch.setattr(s7, "calc_rsi", lambda *args: [55.0])
    monkeypatch.setattr(s7, "calc_atr", lambda *args: [2.0])
    monkeypatch.setattr(s7, "fetch_minute_candles", AsyncMock(return_value=[]))
    monkeypatch.setattr(s7, "get_vwap_minute", AsyncMock(return_value=SimpleNamespace(vwap=None)))
    monkeypatch.setattr(s7, "fetch_stk_nm", AsyncMock(return_value="삼성전자"))
    monkeypatch.setattr(s7, "calc_tp_sl", MagicMock(return_value=tp_sl))
    monkeypatch.setattr(
        s7,
        "fetch_same_time_volume_ratio_cached",
        AsyncMock(return_value=({"same_time_volume_ratio": 1.8}, {"api_id": "ka10055", "complete": True})),
    )
    monkeypatch.setattr(s7, "fetch_volume_profile", AsyncMock(return_value=({}, {"api_id": "ka10025"})))

    result = await s7.scan_ichimoku_breakout("token", rdb=rdb)

    assert len(result) == 1
    assert result[0]["daily_volume_ratio"] == 0.4
    assert result[0]["vol_ratio"] == 1.8
    assert result[0]["volume_ratio_source"] == "ka10055_same_time"
