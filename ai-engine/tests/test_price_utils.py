import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from price_utils import get_tick_size, round_to_tick, normalize_signal_prices


def test_get_tick_size_ranges():
    assert get_tick_size(1999) == 1
    assert get_tick_size(2000) == 5
    assert get_tick_size(5000) == 10
    assert get_tick_size(20000) == 50
    assert get_tick_size(50000) == 100
    assert get_tick_size(200000) == 500
    assert get_tick_size(500000) == 1000


def test_round_to_tick_nearest():
    assert round_to_tick(2003) == 2005
    assert round_to_tick(49997) == 50000
    assert round_to_tick(84321) == 84300


def test_normalize_signal_prices_adjusts_public_fields():
    sig = {
        "cur_prc": 84321,
        "tp1_price": 86123,
        "tp2_price": 87456,
        "sl_price": 83234,
        "claude_tp1": 86234,
        "claude_sl": 83321,
    }
    normalize_signal_prices(sig)
    assert sig["cur_prc"] == 84300
    assert sig["tp1_price"] % 100 == 0
    assert sig["tp2_price"] % 100 == 0
    assert sig["sl_price"] % 100 == 0
    assert sig["claude_tp1"] % 100 == 0
    assert sig["claude_sl"] % 100 == 0
