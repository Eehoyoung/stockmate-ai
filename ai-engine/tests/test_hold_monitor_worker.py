import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.run(coro)


def _rdb():
    rdb = MagicMock()
    rdb.get = AsyncMock(return_value=None)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.lrange = AsyncMock(return_value=[])
    return rdb


def _ctx():
    return {
        "tick": {"cur_prc": "9900"},
        "hoga": {"total_buy_bid_req": "300", "total_sel_bid_req": "100"},
        "strength": 130.0,
        "vi": {},
        "freshness": {},
        "market_type": "001",
        "kospi_flu_rt": 0.3,
    }


def _payload(**overrides):
    payload = {
        "hold_monitor_key": "S8_GOLDEN_CROSS:005930",
        "strategy": "S8_GOLDEN_CROSS",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "action": "HOLD",
        "confidence": "LOW",
        "rule_score": 88.0,
        "ai_score": 72.0,
        "cur_prc": 10000,
        "entry_price": 10000,
        "tp1_price": 11000,
        "sl_price": 9700,
        "rr_ratio": 0.7,
        "buy_zone": {"low": 9700, "high": 10000, "strength": 4, "anchors": ["ma20"]},
    }
    payload.update(overrides)
    return payload


def test_evaluate_hold_item_promotes_high_score_ai_hold_to_enter():
    rdb = _rdb()

    with patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.qw._refresh_stale_ctx", new_callable=AsyncMock), \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {"s8": 92.0})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None), \
         patch("hold_monitor_worker.qw._apply_session_enter_guard", side_effect=lambda payload, ctx: payload), \
         patch("hold_monitor_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
         patch(
             "hold_monitor_worker.analyze_signal",
             new_callable=AsyncMock,
             return_value={
                 "action": "HOLD",
                 "ai_score": 90.0,
                 "confidence": "HIGH",
                 "reason": "setup improved",
             },
         ):
        from hold_monitor_worker import evaluate_hold_item

        result = _run(evaluate_hold_item(rdb, _payload()))

    assert result["action"] == "ENTER"
    assert result["hold_monitor_promoted"] is True
    assert result["hold_promoted_to_enter"] is True
    assert result["cur_prc"] == 9900


def test_is_after_close_deletes_from_1530():
    from hold_monitor_worker import _is_after_close

    kst = timezone(timedelta(hours=9))
    assert _is_after_close(datetime(2026, 6, 17, 15, 29, tzinfo=kst)) is False
    assert _is_after_close(datetime(2026, 6, 17, 15, 30, tzinfo=kst)) is True
