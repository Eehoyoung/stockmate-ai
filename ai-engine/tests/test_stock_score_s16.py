import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _candles(count=60):
    candles = []
    for i in range(count):
        if i == 0:
            close = 107
            high = 108
            low = 101
            volume = 2200
        elif i < 20:
            close = 104 - (i * 0.2)
            high = 107
            low = 90
            volume = 1000
        elif i < 40:
            close = 96 - ((i - 20) * 0.1)
            high = 102
            low = 85
            volume = 900
        else:
            close = 94
            high = 101
            low = 84
            volume = 800
        candles.append({
            "cur_prc": str(round(close, 2)),
            "open_pric": str(round(close - 1, 2)),
            "high_pric": str(round(high, 2)),
            "low_pric": str(round(low, 2)),
            "trde_qty": str(volume),
            "trde_prica": "3000000000",
        })
    return candles


def test_run_all_checks_includes_s16_triggered_candidate():
    from s16_accumulation_state import STRATEGY_NAME
    from stockScore import StockSnapshot, run_all_checks

    snap = StockSnapshot(stk_cd="005930", stk_nm="Samsung", token="")
    snap.candles = _candles()
    snap.cur_prc = 107
    snap.avg_strength = 135
    snap.bid_ratio = 1.6
    snap.market_cap_eok = 5000
    snap.daily_strength = {"latest": 135, "avg_5": 130, "avg_20": 115, "strong_days": 5}
    snap.investor_flow = {"smart_money": 1, "foreign": 1, "institution": 1}
    snap.program_snapshot = {"program_net_buy_amt": 1, "program_net_buy_amt_chg": 1}

    matched, _ = run_all_checks(snap)
    s16 = [signal for signal in matched if signal["strategy"] == STRATEGY_NAME]

    assert len(s16) == 1
    assert s16[0]["score"] >= 80
    assert s16[0]["market_cap_eok"] == 5000
