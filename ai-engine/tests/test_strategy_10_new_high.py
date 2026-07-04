import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _daily_candles():
    return [
        {"cur_prc": "12000", "open_pric": "11200", "high_pric": "12100", "low_pric": "11100", "trde_qty": "2000000"}
    ] + [
        {"cur_prc": "10000", "open_pric": "9900", "high_pric": "10200", "low_pric": "9800", "trde_qty": "1000000"}
        for _ in range(30)
    ]


@pytest.mark.asyncio
async def test_s10_sets_institution_foreign_confirm_and_volume_profile(monkeypatch):
    import strategy_10_new_high as s10

    rdb = MagicMock()
    rdb.lrange = AsyncMock(side_effect=[["005930"], []])
    rdb.hgetall = AsyncMock(return_value={"flu_rt": "4.5", "cur_prc": "12000", "stk_nm": "삼성전자"})

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {
        "tp1_price": 12600,
        "sl_price": 11400,
        "rr_ratio": 1.0,
    }

    eq_result = {
        "spread_pct": 0.1,
        "depth_score": 80,
        "sell_wall_score": 10,
        "vwap_position": "ABOVE",
        "first_low_break": False,
        "breakout_line_break": False,
        "close_position_pct": 80,
        "chase_risk_score": 20,
        "execution_quality": "OK",
        "reject_reason": None,
    }

    monkeypatch.setattr(s10, "fetch_volume_surge_map_all", AsyncMock(return_value={"005930": 180.0}))
    monkeypatch.setattr(s10, "fetch_cntr_strength_cached", AsyncMock(return_value=(135.0, "redis")))
    monkeypatch.setattr(s10, "fetch_hoga", AsyncMock(return_value=1.3))
    monkeypatch.setattr(s10, "fetch_daily_candles", AsyncMock(return_value=_daily_candles()))
    monkeypatch.setattr(s10, "calc_atr", lambda highs, lows, closes, period: [250.0])
    monkeypatch.setattr(s10, "calc_tp_sl", MagicMock(return_value=fake_tp_sl))
    monkeypatch.setattr(s10, "_fetch_hoga_raw_s10", AsyncMock(return_value={}))
    monkeypatch.setattr(s10, "_fetch_minute_chart_raw_s10", AsyncMock(return_value={}))
    monkeypatch.setattr(s10, "assess_execution_quality", MagicMock(return_value=eq_result))
    monkeypatch.setattr(s10, "should_hard_reject", MagicMock(return_value=False))
    monkeypatch.setattr(
        s10,
        "fetch_investor_flow_summary_cached",
        AsyncMock(return_value=({"smart_money": 5000, "foreign": 3000, "institution": 2000}, {"api_id": "ka10061"})),
    )
    monkeypatch.setattr(
        s10,
        "fetch_volume_profile",
        AsyncMock(return_value=(
            {
                "support": {"low": 11600, "high": 11700, "ratio": 18},
                "resistance": {"low": 13000, "high": 13200, "ratio": 22},
            },
            {"api_id": "ka10025", "target_verified": True},
        )),
    )

    result = await s10.scan_new_high_swing("token", rdb=rdb)

    assert len(result) == 1
    signal = result[0]
    assert signal["institution_foreign_confirm"] == "POSITIVE"
    assert signal["investor_smart_money"] == 5000
    assert signal["volume_profile_adjusted"] is True
    assert signal["tp1_price"] == 13000
