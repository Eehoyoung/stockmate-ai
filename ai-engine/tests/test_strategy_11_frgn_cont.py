import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_s11_enriches_investor_flow_and_bid_ratio(monkeypatch):
    import strategy_11_frgn_cont as s11

    rdb = MagicMock()
    rdb.lrange = AsyncMock(return_value=[])
    rdb.hgetall = AsyncMock(return_value={"flu_rt": "3.0", "cntr_str": "125"})

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {"tp1_price": 10500, "sl_price": 9500, "rr_ratio": 1.0}

    raw_items = [{
        "stk_cd": "005930",
        "cur_prc": "10000",
        "dm1": "1000000",
        "dm2": "900000",
        "dm3": "800000",
        "tot": "2700000",
    }]

    monkeypatch.setattr(s11, "fetch_frgn_cont_buy", AsyncMock(return_value=raw_items))
    monkeypatch.setattr(
        s11,
        "fetch_investor_flow_summary_cached",
        AsyncMock(return_value=(
            {"smart_money": 7000, "foreign": 5000, "institution": 2000, "individual": -7000},
            {"api_id": "ka10061"},
        )),
    )
    monkeypatch.setattr(s11, "fetch_hoga", AsyncMock(return_value=1.25))
    monkeypatch.setattr(s11, "fetch_stk_nm", AsyncMock(return_value="삼성전자"))
    monkeypatch.setattr(s11, "fetch_daily_candles", AsyncMock(return_value=[]))
    monkeypatch.setattr(s11, "calc_tp_sl", MagicMock(return_value=fake_tp_sl))

    result = await s11.scan_frgn_cont_swing("token", rdb=rdb)

    assert len(result) == 1
    signal = result[0]
    assert signal["bid_ratio"] == 1.25
    assert signal["investor_smart_money"] == 7000
    assert signal["investor_flow_meta"]["api_id"] == "ka10061"
    assert signal["score"] > 0
