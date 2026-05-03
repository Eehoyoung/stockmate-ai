import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_writer_stub = types.ModuleType("db_writer")
for name in (
    "update_human_confirm_request_status",
    "confirm_open_position",
    "cancel_open_position_by_signal",
    "insert_ai_cancel_signal",
    "insert_rule_cancel_signal",
):
    setattr(db_writer_stub, name, None)
sys.modules.setdefault("db_writer", db_writer_stub)

from confirm_worker import _apply_claude_rr_override, _resolve_regime_rr_policy


def test_confirm_worker_bear_exempt_strategy_uses_bull_rr_threshold():
    ctx = {
        "market_type": "001",
        "kospi_flu_rt": -1.2,
        "kosdaq_flu_rt": 0.1,
    }

    regime, threshold = _resolve_regime_rr_policy(ctx, "S9_PULLBACK_SWING")

    assert regime == "bear"
    assert threshold == 0.65


def test_confirm_worker_claude_rr_allows_bear_exempt_above_relaxed_threshold():
    payload = {
        "action": "ENTER",
        "strategy": "S9_PULLBACK_SWING",
        "stk_cd": "005930",
        "cur_prc": 10000,
        "claude_tp1": 10800,
        "claude_sl": 9000,
    }
    ctx = {
        "market_type": "001",
        "kospi_flu_rt": -1.2,
    }

    result = _apply_claude_rr_override(payload, ctx)

    assert result["action"] == "ENTER"
    assert result["rr_regime"] == "bear"
    assert result["rr_regime_threshold"] == 0.65
    assert result["rr_ratio"] >= result["rr_regime_threshold"]
