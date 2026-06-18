import os
import sys
import types
import asyncio
from unittest.mock import AsyncMock, patch

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
_previous_db_writer = sys.modules.get("db_writer")
sys.modules.setdefault("db_writer", db_writer_stub)

from confirm_worker import (
    _apply_claude_postprocess_hard_rules,
    _apply_claude_rr_override,
    _resolve_regime_rr_policy,
)

if _previous_db_writer is None:
    sys.modules.pop("db_writer", None)
else:
    sys.modules["db_writer"] = _previous_db_writer


def test_confirm_worker_bear_strategy_keeps_base_rr_threshold():
    ctx = {
        "market_type": "001",
        "kospi_flu_rt": -1.2,
        "kosdaq_flu_rt": 0.1,
    }

    regime, threshold = _resolve_regime_rr_policy(ctx, "S9_PULLBACK_SWING")

    assert regime == "bear"
    assert threshold == 1.45


def test_confirm_worker_claude_rr_blocks_bear_signal_below_base_threshold():
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

    assert result["action"] == "CANCEL"
    assert result["rr_regime"] == "bear"
    assert result["rr_regime_threshold"] == 1.45
    assert result["rr_ratio"] < result["rr_regime_threshold"]
    assert result["cancel_type"] == "CLAUDE_HARD_RULE"
    assert result["rr_quality_bucket"] == "POOR"
    assert result["claude_tp1"] is None
    assert result["claude_sl"] is None


def test_confirm_worker_claude_postprocess_blocks_invalid_tp_sl_schema():
    payload = {
        "action": "ENTER",
        "strategy": "S8_GOLDEN_CROSS",
        "stk_cd": "005930",
        "cur_prc": 10000,
        "claude_tp1": 9900,
        "claude_sl": 9700,
    }

    result = _apply_claude_postprocess_hard_rules(payload)

    assert result["action"] == "CANCEL"
    assert result["cancel_type"] == "CLAUDE_HARD_RULE"
    assert result["skip_entry"] is True
    assert result["claude_tp1"] is None


def test_confirm_worker_cancel_is_kept_internal_not_published():
    from confirm_worker import process_confirmed

    item = {
        "id": 1,
        "strategy": "S9_PULLBACK_SWING",
        "stk_cd": "005930",
        "rule_score": 80,
        "market_ctx": {"strength": 120, "market_type": "001"},
    }
    rdb = object()

    with patch("confirm_worker.pop_confirmed_queue", new_callable=AsyncMock, return_value=item), \
         patch("confirm_worker.check_daily_limit", new_callable=AsyncMock, return_value=False), \
         patch("confirm_worker.push_score_only_queue", new_callable=AsyncMock) as mock_score, \
         patch("confirm_worker.push_hold_monitor_queue", new_callable=AsyncMock) as mock_hold:
        result = asyncio.run(process_confirmed(rdb))

    assert result is True
    mock_score.assert_not_awaited()
    mock_hold.assert_not_awaited()
