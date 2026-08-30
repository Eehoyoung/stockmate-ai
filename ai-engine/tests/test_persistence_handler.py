from unittest.mock import AsyncMock

import pytest

from scoring_pipeline.persistence_handler import persist_processed_signal


def _base_kwargs(**overrides):
    kwargs = dict(
        pg_pool=object(),
        signal_id=None,
        signal={},
        enriched={
            "freshness_status": "CAUTION",
            "market_data_observability": {"fields": {}, "rest": {"fallback_used": True}},
        },
        ctx={},
        strategy="S15_MOMENTUM_ALIGN",
        stk_cd="068270",
        action="CANCEL",
        confidence="LOW",
        reason="rule reason",
        display_reason="rule reason",
        cancel_reason="Rule threshold not met",
        cancel_type=None,
        r_score=39.0,
        ai_score_val=39.0,
        threshold=60.0,
        components={},
        rule_only_payload=None,
        insert_python_signal_fn=AsyncMock(return_value=9001),
        update_signal_score_fn=AsyncMock(),
        insert_score_components_fn=AsyncMock(),
        confirm_open_position_fn=AsyncMock(return_value=True),
        create_shadow_trade_fn=AsyncMock(),
        shadow_persistence_enabled=True,
        insert_rule_cancel_signal_fn=AsyncMock(),
        insert_ai_cancel_signal_fn=AsyncMock(),
        insert_signal_freshness_log_fn=AsyncMock(),
        cancel_open_position_by_signal_fn=AsyncMock(),
        normalize_market_type_fn=lambda x: x,
        fv_fn=lambda x, default=None: x if x is not None else default,
        logger=None,
    )
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_freshness_log_recorded_for_cancel_with_new_signal_id():
    kwargs = _base_kwargs()

    await persist_processed_signal(**kwargs)

    kwargs["insert_signal_freshness_log_fn"].assert_awaited_once()
    call = kwargs["insert_signal_freshness_log_fn"].await_args
    assert call.kwargs["signal_id"] == 9001
    assert call.kwargs["stk_cd"] == "068270"
    assert call.kwargs["strategy"] == "S15_MOMENTUM_ALIGN"
    assert call.kwargs["action"] == "CANCEL"
    assert call.kwargs["freshness_status"] == "CAUTION"
    assert call.kwargs["snapshot"]["rest"]["fallback_used"] is True


@pytest.mark.asyncio
async def test_freshness_log_recorded_for_enter_with_existing_signal_id():
    kwargs = _base_kwargs(
        signal_id=555,
        action="ENTER",
        cancel_reason=None,
    )

    await persist_processed_signal(**kwargs)

    kwargs["insert_signal_freshness_log_fn"].assert_awaited_once()
    assert kwargs["insert_signal_freshness_log_fn"].await_args.kwargs["signal_id"] == 555
    assert kwargs["insert_signal_freshness_log_fn"].await_args.kwargs["action"] == "ENTER"


@pytest.mark.asyncio
async def test_persistence_failure_blocks_delivery_when_db_id_missing():
    kwargs = _base_kwargs(insert_python_signal_fn=AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match="signal persistence failed"):
        await persist_processed_signal(**kwargs)

    kwargs["insert_signal_freshness_log_fn"].assert_not_awaited()


@pytest.mark.asyncio
async def test_freshness_log_fn_none_is_tolerated():
    kwargs = _base_kwargs(insert_signal_freshness_log_fn=None)

    # should not raise even though the freshness logger is not wired in
    await persist_processed_signal(**kwargs)


@pytest.mark.asyncio
async def test_hold_monitor_recheck_cancel_does_not_insert_duplicate_signal():
    kwargs = _base_kwargs(
        signal_id=None,
        action="CANCEL",
        enriched={
            "stk_cd": "068270",
            "strategy": "S11_FRGN_CONT",
            "hold_monitor_recheck": True,
        },
    )

    terminal = await persist_processed_signal(**kwargs)

    assert terminal is False
    kwargs["insert_python_signal_fn"].assert_not_awaited()
    kwargs["insert_ai_cancel_signal_fn"].assert_not_awaited()
    kwargs["insert_signal_freshness_log_fn"].assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_monitor_recheck_enter_is_still_persisted():
    kwargs = _base_kwargs(
        signal_id=None,
        action="ENTER",
        cancel_reason=None,
        enriched={
            "stk_cd": "068270",
            "strategy": "S11_FRGN_CONT",
            "hold_monitor_recheck": True,
            "entry_price": 10000,
            "tp1_price": 11000,
            "sl_price": 9500,
        },
    )

    await persist_processed_signal(**kwargs)

    kwargs["insert_python_signal_fn"].assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["ENTER", "CANCEL"])
async def test_shadow_forbidden_policy_does_not_persist_shadow_ledger(action):
    kwargs = _base_kwargs(
        action=action,
        cancel_reason=None if action == "ENTER" else "Rule threshold not met",
        shadow_persistence_enabled=False,
    )

    await persist_processed_signal(**kwargs)

    kwargs["create_shadow_trade_fn"].assert_not_awaited()
