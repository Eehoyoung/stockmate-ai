import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.run(coro)


def _rdb():
    rdb = MagicMock()
    rdb.get = AsyncMock(return_value=None)
    rdb.lpush = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.hset = AsyncMock(return_value=1)
    return rdb


def _pos(**overrides):
    pos = {
        "id": 1,
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "strategy": "S8_GOLDEN_CROSS",
        "entry_price": 10000,
        "sl_price": 9700,
        "tp1_price": 11000,
        "tp2_price": None,
        "trailing_activation": 0,
        "trailing_pct": 1.5,
        "peak_price": None,
        "status": "ACTIVE",
        "signal_id": 42,
    }
    pos.update(overrides)
    return pos


def _ai_scored_payloads(rdb):
    calls = [c for c in rdb.lpush.await_args_list if c.args[0] == "ai_scored_queue"]
    return [json.loads(c.args[1]) for c in calls]


def test_sl_hit_sends_exactly_one_sell_message():
    rdb = _rdb()

    with patch("position_monitor.get_tick_data", new_callable=AsyncMock, return_value={"cur_prc": "9500"}), \
         patch("position_monitor.update_shadow_trade_mark", new_callable=AsyncMock), \
         patch("position_monitor.close_open_position", new_callable=AsyncMock, return_value=True):
        from position_monitor import _check_position

        _run(_check_position(rdb, object(), _pos()))

    payloads = _ai_scored_payloads(rdb)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "SELL_SIGNAL"
    assert payloads[0]["exit_type"] == "SL_HIT"


def test_tp1_hit_sends_exactly_one_sell_message():
    rdb = _rdb()

    with patch("position_monitor.get_tick_data", new_callable=AsyncMock, return_value={"cur_prc": "11500"}), \
         patch("position_monitor.update_shadow_trade_mark", new_callable=AsyncMock), \
         patch("position_monitor.close_open_position", new_callable=AsyncMock, return_value=True):
        from position_monitor import _check_position

        _run(_check_position(rdb, object(), _pos(sl_price=9700, tp1_price=11000)))

    payloads = _ai_scored_payloads(rdb)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "SELL_SIGNAL"
    assert payloads[0]["exit_type"] == "TP1_HIT"


def test_trailing_stop_sends_exactly_one_sell_message():
    rdb = _rdb()

    with patch("position_monitor.get_tick_data", new_callable=AsyncMock, return_value={"cur_prc": "10300"}), \
         patch("position_monitor.update_shadow_trade_mark", new_callable=AsyncMock), \
         patch("position_monitor.update_peak_price", new_callable=AsyncMock), \
         patch("position_monitor.close_open_position", new_callable=AsyncMock, return_value=True):
        from position_monitor import _check_position

        _run(_check_position(rdb, object(), _pos(
            sl_price=9000,
            tp1_price=0,
            trailing_activation=10200,
            trailing_pct=5.0,
            peak_price=11000,
        )))

    payloads = _ai_scored_payloads(rdb)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "SELL_SIGNAL"
    assert payloads[0]["exit_type"] == "TRAILING_STOP"
