import json
import inspect
from unittest.mock import AsyncMock

import pytest


def test_signal_status_preserves_watch_semantics():
    from db_writer import _signal_status_for_action

    assert _signal_status_for_action("ENTER") == "SENT"
    assert _signal_status_for_action("HOLD") == "WATCHING"
    assert _signal_status_for_action("CANCEL") == "CANCELLED"

from db_writer import _is_monitorable_position, insert_signal_freshness_log, update_signal_score


def test_confirmed_enter_becomes_monitorable_paper_position():
    from db_writer import confirm_open_position

    source = inspect.getsource(confirm_open_position)
    assert "position_status = 'ACTIVE'" in source
    assert "monitor_enabled = TRUE" in source
    assert 'position_status="ACTIVE"' in source


def _row(signal_status="EXECUTED", position_status="ACTIVE", exit_type=None,
         executed_at="2026-08-03T10:00:00+09:00", entry_qty=10, remaining_qty=10):
    return {
        "signal_status": signal_status,
        "position_status": position_status,
        "exit_type": exit_type,
        "executed_at": executed_at,
        "entry_qty": entry_qty,
        "remaining_qty": remaining_qty,
    }


def test_expired_active_position_remains_monitorable():
    assert _is_monitorable_position(_row(signal_status="EXPIRED")) is True


def test_closed_expired_position_is_not_monitorable():
    assert _is_monitorable_position(_row(signal_status="EXPIRED", position_status="CLOSED")) is False


def test_position_with_exit_type_is_not_monitorable():
    assert _is_monitorable_position(_row(signal_status="EXECUTED", exit_type="TP1_HIT")) is False


def test_sent_signal_without_execution_evidence_is_not_monitorable():
    assert _is_monitorable_position(_row(
        signal_status="SENT", executed_at=None, entry_qty=None, remaining_qty=None,
    )) is False


@pytest.mark.asyncio
async def test_update_signal_score_merges_shadow_features_for_existing_java_signal():
    pool = AsyncMock()
    shadow = {
        "intraday_investor_flow": {
            "combined_slope": 25.0,
            "recent_reversal": True,
        }
    }

    ok = await update_signal_score(
        pool,
        42,
        rule_score=60.0,
        ai_score=70.0,
        rr_ratio=2.0,
        action="ENTER",
        confidence="HIGH",
        ai_reason="ok",
        tp_method=None,
        sl_method=None,
        skip_entry=False,
        shadow_features=shadow,
    )

    assert ok is True
    sql, *params = pool.execute.await_args.args
    assert "shadow_features" in sql
    # $35 remains the shadow_features parameter; later lineage parameters are additive.
    assert json.loads(params[34]) == shadow


@pytest.mark.asyncio
async def test_insert_signal_freshness_log_extracts_snapshot_fields():
    pool = AsyncMock()
    snapshot = {
        "schema_version": 1,
        "fields": {
            "tick": {"state": "caution", "source": "rest", "age_ms": 4200},
            "hoga": {"state": "caution", "source": "rest", "age_ms": 3100},
            "strength": {"state": "fresh", "source": "redis", "age_ms": 500},
            "vi": {"state": "missing", "source": "missing", "age_ms": None},
        },
        "cache_fields": ["strength"],
        "rest": {
            "fallback_used": True,
            "fallback_fields": ["tick", "hoga"],
            "attempted_fields": ["tick", "hoga"],
            "failures": [],
            "failure_classes": [],
            "budget_state": "ok",
            "budget_used": 3,
            "budget_limit": 50,
            "budget_remaining": 47,
        },
    }

    ok = await insert_signal_freshness_log(
        pool,
        signal_id=1234,
        stk_cd="068270",
        strategy="S15_MOMENTUM_ALIGN",
        action="CANCEL",
        freshness_status="CAUTION",
        snapshot=snapshot,
    )

    assert ok is True
    sql, *params = pool.execute.await_args.args
    assert "signal_data_freshness_log" in sql
    assert params[0] == 1234
    assert params[1] == "068270"
    assert params[2] == "S15_MOMENTUM_ALIGN"
    assert params[3] == "CANCEL"
    assert params[4] == "CAUTION"
    # tick_state, tick_source, tick_age_ms
    assert list(params[5:8]) == ["caution", "rest", 4200]
    # rest_fallback_used, rest_fallback_fields(json), rest_failure_classes(json)
    assert params[17] is True
    assert json.loads(params[18]) == ["tick", "hoga"]
    assert json.loads(params[19]) == []
    assert json.loads(params[20])["rest"]["fallback_used"] is True

    ok = await insert_signal_freshness_log(
        pool,
        signal_id=5678,
        stk_cd="005930",
        strategy="S1_GAP_OPEN",
        action="HOLD",
        snapshot=None,
    )
    assert ok is True


@pytest.mark.asyncio
async def test_insert_signal_freshness_log_db_error_does_not_raise():
    pool = AsyncMock()
    pool.execute.side_effect = Exception("connection lost")

    ok = await insert_signal_freshness_log(
        pool,
        signal_id=1,
        stk_cd="005930",
        strategy="S1_GAP_OPEN",
        action="ENTER",
        snapshot={},
    )

    assert ok is False
