import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _s8_candles(today_volume=2500):
    candles = []
    for idx in range(65):
        price = 110 if idx == 0 else 100
        volume = today_volume if idx == 0 else 1000
        candles.append({
            "cur_prc": str(price),
            "open_pric": "100",
            "high_pric": str(price + 2),
            "low_pric": str(price - 2),
            "trde_qty": str(volume),
        })
    return candles


@pytest.mark.asyncio
async def test_s8_enriches_same_time_volume_and_volume_profile(monkeypatch):
    import strategy_8_golden_cross as s8

    rdb = MagicMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], []])
    rdb.hgetall = AsyncMock(return_value={
        "flu_rt": "3.2",
        "cntr_str": "132",
        "updated_at_ms": str(int(time.time() * 1000)),
    })

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {
        "tp1_price": 116,
        "sl_price": 104,
        "rr_ratio": 1.5,
    }

    # Partial daily volume is only 0.4x; complete ka10055 data must drive the gate.
    monkeypatch.setattr(s8, "fetch_daily_candles", AsyncMock(return_value=_s8_candles(today_volume=400)))
    monkeypatch.setattr(s8, "detect_golden_cross", lambda candles: (True, False, 1.2))
    monkeypatch.setattr(s8, "calc_rsi", lambda closes, period: [55])
    monkeypatch.setattr(s8, "calc_macd", lambda closes: ([0], [0], [2, 1]))
    monkeypatch.setattr(s8, "calc_bollinger", lambda closes, period=20, num_std=2.0: [(118, 110, 102)])
    monkeypatch.setattr(s8, "calc_atr", lambda highs, lows, closes, period: [2.0])
    monkeypatch.setattr(s8, "calc_tp_sl", MagicMock(return_value=fake_tp_sl))
    monkeypatch.setattr(s8, "fetch_stk_nm", AsyncMock(return_value="삼성전자"))
    monkeypatch.setattr(
        s8,
        "fetch_same_time_volume_ratio_cached",
        AsyncMock(return_value=({"same_time_volume_ratio": 1.7}, {"api_id": "ka10055"})),
    )
    monkeypatch.setattr(
        s8,
        "fetch_volume_profile",
        AsyncMock(return_value=(
            {
                "support": {"low": 106, "high": 108, "ratio": 20},
                "resistance": {"low": 120, "high": 122, "ratio": 25},
            },
            {"api_id": "ka10025", "target_verified": True},
        )),
    )

    result = await s8.scan_golden_cross("token", rdb=rdb)

    assert len(result) == 1
    signal = result[0]
    assert signal["same_time_volume_ratio"] == 1.7
    assert signal["daily_volume_ratio"] == 0.4
    assert signal["vol_ratio"] == 1.7
    assert signal["volume_ratio_source"] == "ka10055_same_time"
    assert signal["volume_profile_meta"]["api_id"] == "ka10025"
    assert signal["volume_profile_adjusted"] is True
    assert signal["tp1_price"] == 120
