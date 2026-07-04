import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_signal_readiness_gate_marks_fast_rule_pass_as_candidate():
    from stockScore import StockSnapshot, apply_signal_readiness_gate

    snap = StockSnapshot(stk_cd="005930", stk_nm="삼성전자", token="")
    signal = {"strategy": "S10_NEW_HIGH", "action": "ENTER"}

    result = apply_signal_readiness_gate(signal, snap, enable_ai=False)

    assert result["readiness_action"] == "ENTER_CANDIDATE"
    assert result["manual_review_only"] is True
    assert "fast rule pass" in result["readiness_reasons"][0]


def test_signal_readiness_gate_downgrades_enter_on_stale_data():
    from stockScore import StockSnapshot, apply_signal_readiness_gate

    snap = StockSnapshot(stk_cd="005930", stk_nm="삼성전자", token="")
    snap.freshness = {"tick": {"state": "cancel", "age_ms": 7000}}
    signal = {"strategy": "S10_NEW_HIGH", "action": "ENTER"}

    result = apply_signal_readiness_gate(signal, snap, enable_ai=True)

    assert result["readiness_action"] == "HOLD"
    assert "tick stale" in result["readiness_reasons"]


def test_signal_readiness_gate_maps_cancel_to_avoid():
    from stockScore import StockSnapshot, apply_signal_readiness_gate

    snap = StockSnapshot(stk_cd="005930", stk_nm="삼성전자", token="")
    signal = {"strategy": "S10_NEW_HIGH", "action": "CANCEL"}

    result = apply_signal_readiness_gate(signal, snap, enable_ai=True)

    assert result["readiness_action"] == "AVOID"


def test_signal_readiness_gate_downgrades_enter_on_stale_vi():
    from stockScore import StockSnapshot, apply_signal_readiness_gate

    snap = StockSnapshot(stk_cd="005930", stk_nm="?쇱꽦?꾩옄", token="")
    snap.freshness = {"vi": {"state": "cancel", "age_ms": 25000}}
    signal = {"strategy": "S10_NEW_HIGH", "action": "ENTER"}

    result = apply_signal_readiness_gate(signal, snap, enable_ai=True)

    assert result["readiness_action"] == "HOLD"
    assert "vi stale" in result["readiness_reasons"]
