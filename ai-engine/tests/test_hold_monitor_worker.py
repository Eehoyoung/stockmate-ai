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
    rdb.incrby = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.lrange = AsyncMock(return_value=[])
    rdb.zrem = AsyncMock(return_value=1)
    rdb.hdel = AsyncMock(return_value=1)
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


def test_evaluate_hold_item_returns_queue_worker_recheck_candidate():
    rdb = _rdb()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", False), \
         patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.qw._refresh_stale_ctx", new_callable=AsyncMock) as mock_refresh, \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {"s8": 92.0})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None):
        from hold_monitor_worker import evaluate_hold_item

        result = _run(evaluate_hold_item(rdb, _payload()))

    assert result["type"] == "HOLD_MONITOR_RECHECK"
    assert result["action"] == "HOLD"
    assert result["execution_decision"] == "WATCH"
    assert result["hold_monitor_recheck"] is True
    assert result["hold_monitor_promoted"] is False
    assert result["cur_prc"] == 9900
    mock_refresh.assert_not_awaited()
    assert result["hold_monitor_last_ai_at"] > 0


def test_evaluate_hold_item_blocks_recheck_within_ai_cooldown():
    """Guards against 2026-07-29's 051900 incident: rule gates cleared every ~10s while
    Claude kept returning HOLD, firing a real Claude call each cycle. Once a recheck has
    fired, a second call within HOLD_MONITOR_AI_COOLDOWN_SEC must not fire another."""
    rdb = _rdb()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", False), \
         patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {"s8": 92.0})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None):
        from hold_monitor_worker import evaluate_hold_item

        payload = _payload(hold_monitor_last_ai_at=__import__("time").time())
        result = _run(evaluate_hold_item(rdb, payload))

    assert result == {}
    assert payload["hold_monitor_last_gate"] == "ai cooldown active"


def test_evaluate_hold_item_skips_ai_when_score_stalled_since_last_call():
    """2026-08-12 관측: 종목 278470(S15)이 rule_score 90~100을 30분간 유지하며 매
    쿨다운(60초)마다 Claude를 재호출했지만 ai_score는 72~76 노이즈만 오갔다. 쿨다운을
    넘겼어도 직전 Claude 호출 시점 대비 rule_score가 거의 안 움직였다면 재호출을
    건너뛰어야 한다."""
    rdb = _rdb()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", False), \
         patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {"s8": 92.0})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None):
        from hold_monitor_worker import evaluate_hold_item

        # cooldown 만료(오래 전 호출) + 직전 호출 rule_score(90.0)와 새 rule_score(92.0)
        # 차이가 HOLD_MONITOR_MIN_SCORE_DELTA(5.0) 미만 → 정체로 간주해야 함
        payload = _payload(
            hold_monitor_last_ai_at=0.0,
            hold_monitor_last_ai_rule_score=90.0,
        )
        result = _run(evaluate_hold_item(rdb, payload))

    assert result == {}
    assert "stalled" in payload["hold_monitor_last_gate"]


def test_evaluate_hold_item_calls_ai_when_score_moved_enough():
    """반대로 rule_score가 임계값 이상 움직였다면(정체가 아니라 실제 변화) 쿨다운이
    지난 뒤에는 정상적으로 Claude를 재호출해야 한다."""
    rdb = _rdb()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", False), \
         patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {"s8": 92.0})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None):
        from hold_monitor_worker import evaluate_hold_item

        payload = _payload(
            hold_monitor_last_ai_at=0.0,
            hold_monitor_last_ai_rule_score=70.0,  # 92.0과 22점 차이 -> 정체 아님
        )
        result = _run(evaluate_hold_item(rdb, payload))

    assert result["type"] == "HOLD_MONITOR_RECHECK"
    assert payload["hold_monitor_last_ai_rule_score"] == 92.0


def test_evaluate_hold_item_first_call_never_stalled():
    """비교 대상(직전 호출 rule_score)이 아예 없는 최초 평가는 정체 판정 대상이 아니다."""
    rdb = _rdb()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", False), \
         patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {"s8": 92.0})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None):
        from hold_monitor_worker import evaluate_hold_item

        result = _run(evaluate_hold_item(rdb, _payload()))

    assert result["type"] == "HOLD_MONITOR_RECHECK"


def test_process_due_items_requeues_via_telegram_queue_not_scored_queue():
    rdb = _rdb()
    rdb.zrangebyscore = AsyncMock(return_value=["S8_GOLDEN_CROSS:005930"])
    rdb.zrem = AsyncMock(return_value=1)
    rdb.hget = AsyncMock(return_value='{"hold_monitor_key":"S8_GOLDEN_CROSS:005930","strategy":"S8_GOLDEN_CROSS","stk_cd":"005930"}')
    captured = []

    async def capture_push(_rdb, payload):
        captured.append(payload)

    with patch("hold_monitor_worker.evaluate_hold_item", new_callable=AsyncMock, return_value={
        "type": "HOLD_MONITOR_RECHECK",
        "strategy": "S8_GOLDEN_CROSS",
        "stk_cd": "005930",
        "execution_decision": "WATCH",
    }), patch("hold_monitor_worker.push_telegram_queue", side_effect=capture_push):
        from hold_monitor_worker import process_due_items

        promoted = _run(process_due_items(rdb))

    assert promoted == 1
    assert captured[0]["type"] == "HOLD_MONITOR_RECHECK"
    rdb.hdel.assert_awaited_with("hold_monitor:items", "S8_GOLDEN_CROSS:005930")


def test_refresh_ctx_uses_rest_only_when_enabled_and_budget_available():
    rdb = _rdb()
    ctx = _ctx()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", True), \
         patch("hold_monitor_worker.HOLD_MONITOR_MAX_REST_CALLS_PER_MIN", 30), \
         patch("hold_monitor_worker.qw._refresh_stale_ctx", new_callable=AsyncMock) as mock_refresh:
        from hold_monitor_worker import _refresh_ctx_for_hold_monitor

        _run(_refresh_ctx_for_hold_monitor(ctx, "005930", rdb, _payload(), "S8_GOLDEN_CROSS"))

    mock_refresh.assert_awaited_once()


def test_refresh_ctx_skips_rest_when_budget_exhausted():
    rdb = _rdb()
    rdb.get = AsyncMock(return_value="30")
    ctx = _ctx()

    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", True), \
         patch("hold_monitor_worker.HOLD_MONITOR_MAX_REST_CALLS_PER_MIN", 30), \
         patch("hold_monitor_worker.qw._refresh_stale_ctx", new_callable=AsyncMock) as mock_refresh:
        from hold_monitor_worker import _refresh_ctx_for_hold_monitor

        _run(_refresh_ctx_for_hold_monitor(ctx, "005930", rdb, _payload(), "S8_GOLDEN_CROSS"))

    mock_refresh.assert_not_awaited()
    assert "hold_monitor_rest_budget_exhausted" in ctx["refresh_meta"]["retry_failures"]


def test_is_after_close_deletes_from_1530():
    from hold_monitor_worker import _is_after_close

    kst = timezone(timedelta(hours=9))
    assert _is_after_close(datetime(2026, 6, 17, 15, 29, tzinfo=kst)) is False
    assert _is_after_close(datetime(2026, 6, 17, 15, 30, tzinfo=kst)) is True


def test_process_due_items_notifies_release_when_dropped_terminal():
    rdb = _rdb()
    rdb.zrangebyscore = AsyncMock(return_value=["S8_GOLDEN_CROSS:005930"])
    rdb.hget = AsyncMock(return_value='{"hold_monitor_key":"S8_GOLDEN_CROSS:005930","strategy":"S8_GOLDEN_CROSS","stk_cd":"005930"}')
    released = []

    async def capture_release(_rdb, payload):
        released.append(payload)

    with patch("hold_monitor_worker.evaluate_hold_item", new_callable=AsyncMock, return_value={}), \
         patch("hold_monitor_worker._is_after_close", return_value=False), \
         patch("hold_monitor_worker._requeue", new_callable=AsyncMock, return_value=False), \
         patch("hold_monitor_worker.push_score_only_queue", side_effect=capture_release):
        from hold_monitor_worker import process_due_items

        promoted = _run(process_due_items(rdb))

    assert promoted == 0
    assert len(released) == 1
    assert released[0]["type"] == "HOLD_RELEASED"
    assert released[0]["stk_cd"] == "005930"
    rdb.hdel.assert_awaited_with("hold_monitor:items", "S8_GOLDEN_CROSS:005930")


def test_process_due_items_does_not_notify_when_requeued():
    rdb = _rdb()
    rdb.zrangebyscore = AsyncMock(return_value=["S8_GOLDEN_CROSS:005930"])
    rdb.hget = AsyncMock(return_value='{"hold_monitor_key":"S8_GOLDEN_CROSS:005930","strategy":"S8_GOLDEN_CROSS","stk_cd":"005930"}')
    released = []

    async def capture_release(_rdb, payload):
        released.append(payload)

    with patch("hold_monitor_worker.evaluate_hold_item", new_callable=AsyncMock, return_value={}), \
         patch("hold_monitor_worker._is_after_close", return_value=False), \
         patch("hold_monitor_worker._requeue", new_callable=AsyncMock, return_value=True), \
         patch("hold_monitor_worker.push_score_only_queue", side_effect=capture_release):
        from hold_monitor_worker import process_due_items

        promoted = _run(process_due_items(rdb))

    assert promoted == 0
    assert released == []


def test_release_all_for_close_notifies_each_item_then_clears():
    rdb = _rdb()
    rdb.hgetall = AsyncMock(return_value={
        "S8_GOLDEN_CROSS:005930": '{"hold_monitor_key":"S8_GOLDEN_CROSS:005930","strategy":"S8_GOLDEN_CROSS","stk_cd":"005930"}',
        "S9_PULLBACK_SWING:000660": '{"hold_monitor_key":"S9_PULLBACK_SWING:000660","strategy":"S9_PULLBACK_SWING","stk_cd":"000660"}',
    })
    released = []

    async def capture_release(_rdb, payload):
        released.append(payload)

    with patch("hold_monitor_worker.push_score_only_queue", side_effect=capture_release), \
         patch("hold_monitor_worker.clear_hold_monitor_queue", new_callable=AsyncMock) as mock_clear:
        from hold_monitor_worker import _release_all_for_close

        count = _run(_release_all_for_close(rdb))

    assert count == 2
    assert {r["stk_cd"] for r in released} == {"005930", "000660"}
    assert all(r["type"] == "HOLD_RELEASED" for r in released)
    mock_clear.assert_awaited_once()


def test_evaluate_hold_item_stops_after_per_item_ai_recheck_limit():
    rdb = _rdb()
    with patch("hold_monitor_worker.HOLD_MONITOR_USE_REST_FALLBACK", False), \
         patch("hold_monitor_worker.qw._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
         patch("hold_monitor_worker.rule_score", return_value=(92.0, {})), \
         patch("hold_monitor_worker.should_skip_ai", return_value=False), \
         patch("hold_monitor_worker.qw._rr_prefilter_reason", return_value=None), \
         patch("hold_monitor_worker.qw._s8_buy_zone_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._s1_fallback_quality_failure", return_value=None), \
         patch("hold_monitor_worker.qw._hard_gate_failure", return_value=None), \
         patch("hold_monitor_worker.qw._freshness_cancel_reason", return_value=None):
        from hold_monitor_worker import evaluate_hold_item, HOLD_MONITOR_MAX_AI_RECHECKS
        payload = _payload(hold_monitor_last_ai_at=0.0, hold_monitor_ai_rechecks=HOLD_MONITOR_MAX_AI_RECHECKS)
        result = _run(evaluate_hold_item(rdb, payload))

    assert result == {}
    assert payload["hold_monitor_last_gate"] == "AI recheck limit reached"
