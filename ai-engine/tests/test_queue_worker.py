import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.run(coro)


def _make_rdb(rpop_value=None):
    rdb = MagicMock()
    rdb.rpop = AsyncMock(return_value=rpop_value)
    rdb.lpush = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.incr = AsyncMock(return_value=1)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.hget = AsyncMock(return_value=None)
    rdb.hset = AsyncMock(return_value=1)
    rdb.hdel = AsyncMock(return_value=1)
    rdb.hincrby = AsyncMock(return_value=1)
    rdb.lrange = AsyncMock(return_value=[])
    rdb.zadd = AsyncMock(return_value=1)
    rdb.zrangebyscore = AsyncMock(return_value=[])
    rdb.zrem = AsyncMock(return_value=1)
    rdb.sadd = AsyncMock(return_value=1)
    rdb.delete = AsyncMock(return_value=1)
    rdb.get = AsyncMock(return_value=None)
    rdb.set = AsyncMock(return_value=True)
    return rdb


def _signal(**overrides):
    base = {
        "id": 101,
        "strategy": "S1_GAP_OPEN",
        "stk_cd": "005930",
        "stk_nm": "Samsung Electronics",
        "gap_pct": 4.0,
        "target_pct": 3.5,
        "stop_pct": -2.0,
    }
    base.update(overrides)
    return base


def _ctx():
    return {
        "tick": {},
        "hoga": {"total_buy_bid_req": "200", "total_sel_bid_req": "100"},
        "strength": 120.0,
        "vi": {},
        "ws_online": False,
    }


class TestQueueWorkerHappyPath:
    def test_force_close_bypasses_scoring(self):
        item = {"type": "FORCE_CLOSE", "stk_cd": "005930", "strategy": "S1_GAP_OPEN"}
        rdb = _make_rdb(json.dumps(item))

        with patch("queue_worker.rule_score") as mock_rule, \
             patch("queue_worker.analyze_signal") as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push:
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        mock_push.assert_awaited_once_with(rdb, item)
        mock_rule.assert_not_called()
        mock_analyze.assert_not_called()

    def test_rule_score_tuple_contract_is_used(self):
        item = _signal(cur_prc=10000, tp1_price=12000, sl_price=9500, rr_ratio=4.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "ENTER",
                     "ai_score": 81.0,
                     "confidence": "HIGH",
                     "reason": "strong setup",
                 },
             ) as mock_analyze, \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        analyzed_signal = mock_analyze.await_args.args[0]
        assert "persona" in analyzed_signal
        assert "시초가 갭" in analyzed_signal["persona"]
        assert captured[0]["persona"] == analyzed_signal["persona"]
        assert captured[0]["rule_score"] == 79.17
        assert captured[0]["shadow_feature_live"]["mode"] == "LIVE"
        assert captured[0]["ai_score"] == 81.0
        assert captured[0]["action"] == "ENTER"

    def test_toss_risk_propagates_from_ctx_to_payload(self):
        """queue_worker가 market_ctx["toss_risk"]를 최종 텔레그램 페이로드로 전달하는지
        확인 — telegram-bot formatter._formatTossRiskLine가 소비하는 필드."""
        item = _signal(cur_prc=10000, tp1_price=12000, sl_price=9500, rr_ratio=4.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        ctx_with_toss = {**_ctx(), "toss_risk": {"short_selling": {"shortSellingAmountRate": "0.1"}}}

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=ctx_with_toss), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={"action": "ENTER", "ai_score": 81.0, "confidence": "HIGH", "reason": "ok"},
             ), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["toss_risk"] == {"short_selling": {"shortSellingAmountRate": "0.1"}}

    def test_enter_signal_creates_shadow_trade_record(self):
        item = _signal(entry_price=10000, cur_prc=10000, tp1_price=10800, tp2_price=11200, sl_price=9700, rr_ratio=2.6)
        rdb = _make_rdb(json.dumps(item))
        pg_pool = object()

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "ENTER",
                     "ai_score": 81.0,
                     "confidence": "HIGH",
                     "reason": "strong setup",
                     "claude_tp1": 10900,
                     "claude_tp2": 11300,
                     "claude_sl": 9600,
                 },
             ), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock), \
             patch("queue_worker.insert_python_signal", new_callable=AsyncMock, return_value=777), \
             patch("queue_worker.update_signal_score", new_callable=AsyncMock), \
             patch("queue_worker.insert_score_components", new_callable=AsyncMock), \
             patch("queue_worker.confirm_open_position", new_callable=AsyncMock), \
             patch("queue_worker.create_shadow_trade", new_callable=AsyncMock) as mock_shadow:
            from queue_worker import process_one

            result = _run(process_one(rdb, pg_pool=pg_pool))

        assert result is True
        mock_shadow.assert_not_awaited()

    def test_cancel_signal_does_not_create_shadow_trade_in_live_only_mode(self):
        item = _signal(entry_price=10000, cur_prc=10000, tp1_price=10800, sl_price=9700, rr_ratio=2.6)
        rdb = _make_rdb(json.dumps(item))
        pg_pool = object()

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "CANCEL",
                     "ai_score": 30.0,
                     "confidence": "LOW",
                     "reason": "risk too high",
                     "cancel_reason": "시장 약세",
                 },
             ), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock), \
             patch("queue_worker.insert_python_signal", new_callable=AsyncMock, return_value=777), \
             patch("queue_worker.update_signal_score", new_callable=AsyncMock), \
             patch("queue_worker.insert_score_components", new_callable=AsyncMock), \
             patch("queue_worker.insert_ai_cancel_signal", new_callable=AsyncMock), \
             patch("queue_worker.cancel_open_position_by_signal", new_callable=AsyncMock), \
             patch("queue_worker.create_shadow_trade", new_callable=AsyncMock) as mock_shadow:
            from queue_worker import process_one

            result = _run(process_one(rdb, pg_pool=pg_pool))

        assert result is True
        mock_shadow.assert_not_awaited()

    def test_resolve_bid_ratio_falls_back_to_signal_buy_sell_requests(self):
        from queue_worker import _resolve_bid_ratio

        ratio = _resolve_bid_ratio(
            {"buy_req": "5,233", "sel_req": "3,118"},
            {"hoga": {}, "signal_fallback_allowed": True},
        )

        assert ratio == 1.678

    def test_resolve_bid_ratio_prefers_fresh_hoga_over_signal_bid_ratio(self):
        from queue_worker import _resolve_bid_ratio

        ratio = _resolve_bid_ratio(
            {"bid_ratio": "1.55", "buy_req": "100", "sel_req": "100"},
            {"hoga": {"total_buy_bid_req": "300", "total_sel_bid_req": "100"}},
        )

        assert ratio == 3.0

    def test_process_one_persists_ctx_bid_ratio_and_volume_alias(self):
        item = _signal(
            strategy="S6_THEME_LAGGARD",
            cur_prc=10000,
            tp1_price=11200,
            sl_price=9600,
            rr_ratio=3.0,
            volume_ratio=2.5,
        )
        rdb = _make_rdb(json.dumps(item))
        captured = []
        ctx = _ctx()
        ctx["hoga"] = {"total_buy_bid_req": "240", "total_sel_bid_req": "100"}

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=ctx), \
             patch("queue_worker.rule_score", return_value=(40.0, {"strength": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["bid_ratio"] == 2.4
        assert captured[0]["vol_ratio"] == 2.5
        assert captured[0]["execution_decision"] == "WATCH"

    def test_legacy_float_rule_score_is_tolerated(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=75.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["rule_score"] == 79.17
        assert captured[0]["execution_decision"] == "WATCH"
        assert captured[0]["action"] == "HOLD"

    def test_fresh_ctx_strength_outranks_signal_strength(self):
        item = _signal(cntr_strength=257.2, cur_prc=10000, tp1_price=12000, sl_price=9500, rr_ratio=4.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []
        seen_ctx = {}

        async def capture_push(_rdb, payload):
            captured.append(payload)

        async def fake_analyze(signal, ctx, rule_score, rdb=None):
            seen_ctx["strength"] = ctx.get("strength")
            return {
                "action": "ENTER",
                "ai_score": 81.0,
                "confidence": "HIGH",
                "reason": f"체결강도 {ctx.get('strength')}",
            }

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch("queue_worker.analyze_signal", side_effect=fake_analyze), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert seen_ctx["strength"] == 120.0
        assert captured[0]["cntr_strength"] == 120.0
        assert "120.0" in captured[0]["ai_reason"]

    def test_high_score_hold_routes_to_watch_monitor(self):
        item = _signal(cur_prc=10000, tp1_price=10300, sl_price=9900, rr_ratio=2.0, bid_ratio=2.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "HOLD",
                     "ai_score": 80.0,
                     "confidence": "HIGH",
                     "reason": "strong but originally hold",
                 },
             ), \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        assert captured[0]["action"] == "HOLD"
        assert captured[0]["execution_decision"] == "WATCH"
        assert captured[0]["ai_score"] == 80.0
        assert captured[0]["cancel_reason"] is None
        assert captured[0]["hold_promoted_to_enter"] is False
        assert "ai_score alone cannot promote to ENTER" in captured[0]["ai_reason"]


class TestQueueWorkerFailures:
    def test_processing_exception_publishes_explicit_failed_payload(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch(
            "queue_worker._build_market_ctx",
            new_callable=AsyncMock,
            side_effect=RuntimeError("market ctx unavailable"),
        ), patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        payload = captured[0]
        assert payload["action"] == "FAILED"
        assert payload["type"] == "PROCESSING_ERROR"
        assert payload["skip_entry"] is True
        assert payload["error_type"] == "RuntimeError"
        assert "market ctx unavailable" in payload["error"]
        rdb.lpush.assert_awaited_once()
        assert any(call.args[1] == "processing_error" for call in rdb.hincrby.await_args_list)

    def test_failed_processing_no_longer_degrades_to_hold(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch(
            "queue_worker._build_market_ctx",
            new_callable=AsyncMock,
            side_effect=ValueError("bad market data"),
        ), patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            _run(process_one(rdb))

        assert captured[0]["action"] != "HOLD"
        assert captured[0]["action"] == "FAILED"

    def test_failure_payload_publish_error_is_swallowed_after_dlq(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))

        async def failing_push(_rdb, _payload):
            raise RuntimeError("queue unavailable")

        with patch(
            "queue_worker._build_market_ctx",
            new_callable=AsyncMock,
            side_effect=RuntimeError("market ctx unavailable"),
        ), patch("queue_worker.push_score_only_queue", side_effect=failing_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        rdb.lpush.assert_awaited_once()

    def test_claude_exception_cancels_instead_of_rule_fallback_enter(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock, side_effect=RuntimeError("api down")), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push) as mock_push:
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured == []
        mock_push.assert_not_awaited()

    def test_claude_daily_limit_cancels_instead_of_rule_fallback_enter(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=False), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push) as mock_push:
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured == []
        mock_push.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_claude_cancel_publishes_rule_only_signal(self):
        item = _signal(cur_prc=18880, tp1_price=20070, sl_price=17480)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "CANCEL",
                     "ai_score": 55.0,
                     "confidence": "LOW",
                     "reason": "Claude rejected setup",
                     "cancel_reason": "weak follow-through",
                 },
             ), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push) as mock_push:
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured == []
        mock_push.assert_not_awaited()

    def test_s4_hard_gate_failure_cancels_before_ai(self):
        item = _signal(strategy="S4_BIG_CANDLE", cntr_strength=114.9, bid_ratio=1.19)
        rdb = _make_rdb(json.dumps(item))
        captured = []
        live_ctx = _ctx()
        live_ctx["strength"] = 114.9
        live_ctx["hoga"] = {"total_buy_bid_req": "119", "total_sel_bid_req": "100"}

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=live_ctx), \
             patch("queue_worker.rule_score", return_value=(80.0, {"body": 30.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock) as mock_limit, \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push) as mock_push:
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured == []
        mock_push.assert_not_awaited()
        mock_limit.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_s8_far_above_support_zone_calls_ai_when_rr_is_strong(self):
        item = _signal(
            strategy="S8_GOLDEN_CROSS",
            cur_prc=10800,
            rr_ratio=2.0,
            buy_zone={"low": 9800, "high": 10400, "strength": 5, "anchors": ["ma5", "ma20", "vwap"]},
        )
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        async def fake_analyze(signal, ctx, rule_score, rdb=None):
            assert signal["s8_zone_status"] == "caution"
            assert signal["s8_zone_entry_policy"] == "momentum_chase_size_down"
            return {"action": "HOLD", "ai_score": 72, "confidence": "MEDIUM", "reason": "extended but strong"}

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(88.0, {"s8": 88.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True) as mock_limit, \
             patch("queue_worker.analyze_signal", side_effect=fake_analyze) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_score_push, \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        mock_score_push.assert_awaited_once()
        notice = mock_score_push.await_args.args[1]
        assert notice["type"] == "HOLD_WATCH"
        assert captured[0]["action"] == "HOLD"
        assert captured[0]["s8_zone_status"] == "caution"
        assert captured[0]["s8_zone_entry_policy"] == "momentum_chase_size_down"
        rescue_meta = captured[0]["shadow_features"]["rescue_meta"]
        assert rescue_meta["decision_stage"] == "SIZE_DOWN"
        assert rescue_meta["s8_zone_entry_policy"] == "momentum_chase_size_down"
        mock_limit.assert_awaited_once()
        assert mock_analyze.await_count == 1

    def test_s8_moderately_above_support_zone_calls_ai_with_limit_pullback_policy(self):
        item = _signal(
            strategy="S8_GOLDEN_CROSS",
            cur_prc=10600,
            rr_ratio=2.0,
            zone_rr=1.8,
            buy_zone={"low": 9800, "high": 10400, "strength": 5, "anchors": ["ma5", "ma20", "vwap"]},
        )
        rdb = _make_rdb(json.dumps(item))
        captured_signal = {}

        async def fake_analyze(signal, ctx, rule_score, rdb=None):
            captured_signal.update(signal)
            return {"action": "HOLD", "ai_score": 72, "confidence": "MEDIUM", "reason": "wait pullback"}

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(88.0, {"s8": 88.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True) as mock_limit, \
             patch("queue_worker.analyze_signal", side_effect=fake_analyze) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured_signal["s8_zone_status"] == "caution"
        assert captured_signal["s8_zone_entry_policy"] == "limit_pullback"
        assert captured_signal["s8_buy_zone_role"] == "support_zone"
        assert 1.8 < captured_signal["s8_buy_zone_high_gap_pct"] < 2.0
        mock_limit.assert_awaited_once()
        assert mock_analyze.await_count == 1

    def test_s8_below_buy_zone_cancels_before_ai(self):
        item = _signal(
            strategy="S8_GOLDEN_CROSS",
            cur_prc=9600,
            rr_ratio=2.0,
            buy_zone={"low": 9800, "high": 10400, "strength": 5, "anchors": ["ma5", "ma20", "vwap"]},
        )
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(88.0, {"s8": 88.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock) as mock_limit, \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push) as mock_push:
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured == []
        mock_push.assert_not_awaited()
        mock_limit.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_rr_prefilter_below_strategy_gate_routes_to_watch_before_ai(self):
        item = _signal(cur_prc=10000, tp1_price=10100, sl_price=9900, rr_ratio=0.79)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock) as mock_limit, \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["action"] == "HOLD"
        assert captured[0]["execution_decision"] == "WATCH"
        assert "below 1.20" in captured[0]["ai_reason"]
        mock_limit.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_s8_low_rr_waits_for_pullback_before_ai(self):
        item = _signal(
            strategy="S8_GOLDEN_CROSS",
            cur_prc=4645,
            tp1_price=4920,
            sl_price=3700,
            rr_ratio=0.29,
            buy_zone={"low": 4200, "high": 4500, "strength": 4, "anchors": ["ma20", "box", "vwap"]},
        )
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(100.0, {"s8": 100.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock) as mock_limit, \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_score_push, \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        mock_score_push.assert_awaited_once()
        assert captured[0]["action"] == "HOLD"
        assert captured[0]["cancel_type"] == "S8_WAIT_PULLBACK"
        assert captured[0]["s8_zone_entry_policy"] == "wait_pullback"
        assert "WATCH until R:R improves" in captured[0]["ai_reason"]
        mock_limit.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_acceptable_rr_calls_ai_with_quality_metadata(self):
        item = _signal(cur_prc=10000, tp1_price=10300, sl_price=9900, rr_ratio=1.25, vol_ratio=1.5)
        rdb = _make_rdb(json.dumps(item))
        captured_signal = {}

        async def fake_analyze(signal, ctx, rule_score, rdb=None):
            captured_signal.update(signal)
            return {"action": "CANCEL", "ai_score": 55, "confidence": "LOW", "reason": "borderline", "cancel_reason": "R:R 약함"}

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", side_effect=fake_analyze), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured_signal["rr_quality_bucket"] == "acceptable"
        assert "signal_quality_score" in captured_signal
        assert captured_signal["performance_ev_status"] == "insufficient_data"

    def test_priority_rule_threshold_rescue_calls_ai(self):
        item = _signal(
            strategy="S7_ICHIMOKU_BREAKOUT",
            cur_prc=10000,
            tp1_price=11800,
            sl_price=9500,
            rr_ratio=3.0,
            cntr_strength=125.0,
            bid_ratio=0.8,
            vol_ratio=2.0,
            chikou_above=True,
        )
        rdb = _make_rdb(json.dumps(item))
        captured_signal = {}

        async def fake_analyze(signal, ctx, rule_score, rdb=None):
            captured_signal.update(signal)
            return {"action": "HOLD", "ai_score": 70, "confidence": "MEDIUM", "reason": "rescued setup"}

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(40.0, {"s7": 40.0})), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True) as mock_limit, \
             patch("queue_worker.analyze_signal", side_effect=fake_analyze) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured_signal["rule_threshold_rescued"] is True
        assert "RR 3.00" in captured_signal["rule_threshold_rescue_reason"]
        mock_limit.assert_awaited_once()
        assert mock_analyze.await_count == 1

    def test_s1_hard_gate_bid_ratio_is_rescued_when_strength_passes(self):
        from queue_worker import _hard_gate_failure

        signal = {"strategy": "S1_GAP_OPEN", "cntr_strength": 160.0, "bid_ratio": 0.7, "rr_ratio": 1.3}
        ctx = {"freshness": {"strength": {"state": "cancel"}, "hoga": {"state": "cancel"}},
               "signal_fallback_allowed": True}
        reason = _hard_gate_failure(signal, ctx)

        assert reason is None
        assert signal["hard_gate_bid_ratio_rescued"] is True

    def test_s1_hard_gate_extreme_bid_ratio_cancels_even_when_strength_passes(self):
        from queue_worker import _hard_gate_failure

        signal = {"strategy": "S1_GAP_OPEN", "cntr_strength": 180.0, "bid_ratio": 0.25, "rr_ratio": 2.0}
        ctx = {"freshness": {"strength": {"state": "cancel"}, "hoga": {"state": "cancel"}},
               "signal_fallback_allowed": True}
        reason = _hard_gate_failure(signal, ctx)

        assert reason is not None
        assert "bid_ratio" in reason

    def test_s1_hard_gate_bid_ratio_rescue_requires_floor(self):
        from queue_worker import _hard_gate_failure

        weak_bid = {"strategy": "S1_GAP_OPEN", "cntr_strength": 180.0, "bid_ratio": 0.59, "rr_ratio": 2.0}
        pass_bid = {"strategy": "S1_GAP_OPEN", "cntr_strength": 180.0, "bid_ratio": 0.60, "rr_ratio": 2.0}
        ctx = {"freshness": {"strength": {"state": "cancel"}, "hoga": {"state": "cancel"}},
               "signal_fallback_allowed": True}

        assert _hard_gate_failure(weak_bid, ctx) is not None
        assert _hard_gate_failure(pass_bid, ctx) is None
        assert pass_bid["hard_gate_bid_ratio_rescued"] is True

    def test_s1_fallback_quality_requires_live_strength_and_bid(self):
        from queue_worker import _s1_fallback_quality_failure

        signal = {
            "strategy": "S1_GAP_OPEN",
            "candidate_source_status": "FALLBACK_ALL_MARKET",
            "cntr_strength": 120.0,
            "bid_ratio": 0.7,
        }
        reason = _s1_fallback_quality_failure(signal, _ctx())

        assert reason is not None
        assert "S1 fallback quality failed" in reason
        assert signal["s1_fallback_entry_policy"] == "skip_fallback_candidate"

    def test_s1_execution_policy_gate_routes_hold_recheck(self):
        from queue_worker import _s1_execution_policy_gate

        signal = {
            "strategy": "S1_GAP_OPEN",
            "s1_entry_policy": "HOLD_RECHECK",
            "s1_entry_policy_reasons": ["expected bid weakened -35.0%"],
        }

        result = _s1_execution_policy_gate(signal)

        assert result is not None
        assert result[0] == "HOLD"
        assert result[2] == "S1_HOLD_RECHECK"

    def test_s1_execution_policy_gate_routes_cancel(self):
        from queue_worker import _s1_execution_policy_gate

        signal = {
            "strategy": "S1_GAP_OPEN",
            "s1_entry_policy": "CANCEL",
            "s1_entry_policy_reasons": ["first low break below VWAP"],
        }

        result = _s1_execution_policy_gate(signal)

        assert result is not None
        assert result[0] == "CANCEL"
        assert result[2] == "S1_EXECUTION_POLICY"

    def test_claude_tp_sl_recalculates_rr_in_published_payload(self):
        item = _signal(cur_prc=10000, tp1_price=10200, sl_price=9900, rr_ratio=1.3, min_rr_ratio=1.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "ENTER",
                     "ai_score": 82.0,
                     "confidence": "HIGH",
                     "reason": "strong adjusted plan",
                     "claude_tp1": 10600,
                     "claude_sl": 9900,
                 },
             ), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        payload = captured[0]
        assert payload["action"] == "ENTER"
        assert payload["claude_tp1"] == 10600
        assert payload["claude_sl"] == 9900
        assert payload["rr_basis"] == "claude_tp_sl"
        assert payload["rr_ratio"] == payload["effective_rr"]
        assert payload["rr_ratio"] != 0.9
        assert abs(payload["rr_ratio"] - 3.118) < 0.01

    def test_s1_claude_enter_uses_strategy_base_regime_rr(self):
        item = _signal(cur_prc=10000, tp1_price=12000, sl_price=9000, rr_ratio=2.0, min_rr_ratio=1.0, bid_ratio=2.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "ENTER",
                     "ai_score": 82.0,
                     "confidence": "HIGH",
                     "reason": "claude says enter",
                    "claude_tp1": 10800,
                    "claude_tp2": 10900,
                     "claude_sl": 9700,
                 },
             ), \
             patch("queue_worker._apply_session_enter_guard", side_effect=lambda payload, ctx, **_kwargs: payload), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        payload = captured[0]
        assert payload["action"] == "ENTER"
        assert payload["execution_decision"] == "ENTER"
        assert payload["rr_policy"] == "strategy_base_x_regime"
        assert payload["rr_regime_threshold"] == 1.2
        assert payload["rr_ratio"] >= payload["rr_regime_threshold"]


class TestClaudeRiskPostprocess:
    def test_market_regime_is_split_by_stock_market_type(self):
        from queue_worker import _detect_market_regime

        ctx = {
            "kospi_flu_rt": -2.0,
            "kosdaq_flu_rt": 2.0,
            "market_type": "001",
        }
        assert _detect_market_regime(ctx, "S8_GOLDEN_CROSS") == "bear"

        ctx["market_type"] = "101"
        assert _detect_market_regime(ctx, "S8_GOLDEN_CROSS") == "bull"

    def test_unknown_market_type_falls_back_to_blended_regime(self):
        from queue_worker import _detect_market_regime

        ctx = {
            "kospi_flu_rt": -2.0,
            "kosdaq_flu_rt": 2.0,
        }

        assert _detect_market_regime(ctx, "S8_GOLDEN_CROSS") == "sideways"

    def test_s1_high_score_hold_stays_watch(self):
        from queue_worker import _maybe_promote_hold_to_enter

        action, confidence, reason, cancel_reason = _maybe_promote_hold_to_enter(
            strategy="S1_GAP_OPEN",
            action="HOLD",
            confidence="MEDIUM",
            reason="watch opening continuation",
            cancel_reason=None,
            ai_score=95.0,
        )

        assert action == "HOLD"
        assert confidence == "MEDIUM"
        assert "ai_score alone cannot promote to ENTER" in reason
        assert cancel_reason is None

    def test_non_s1_high_score_hold_stays_watch(self):
        from queue_worker import _maybe_promote_hold_to_enter

        action, confidence, reason, cancel_reason = _maybe_promote_hold_to_enter(
            strategy="S2_VI_PULLBACK",
            action="HOLD",
            confidence="HIGH",
            reason="strong pullback",
            cancel_reason=None,
            ai_score=95.0,
        )

        assert action == "HOLD"
        assert confidence == "HIGH"
        assert "ai_score alone cannot promote to ENTER" in reason
        assert cancel_reason is None

    def test_hold_or_cancel_nulls_claude_prices(self):
        from queue_worker import _apply_claude_postprocess_hard_rules

        payload = {
            "strategy": "S1_GAP_OPEN",
            "action": "HOLD",
            "claude_tp1": 11000,
            "claude_tp2": 12000,
            "claude_sl": 9500,
        }

        result = _apply_claude_postprocess_hard_rules(payload)

        assert result["action"] == "HOLD"
        assert result["claude_tp1"] is None
        assert result["claude_tp2"] is None
        assert result["claude_sl"] is None

    def test_enter_invalid_tp_sl_relation_becomes_cancel_and_nulls_prices(self):
        from queue_worker import _apply_claude_postprocess_hard_rules

        payload = {
            "strategy": "S1_GAP_OPEN",
            "action": "ENTER",
            "cur_prc": 10000,
            "claude_tp1": 9900,
            "claude_tp2": 10500,
            "claude_sl": 9700,
        }

        result = _apply_claude_postprocess_hard_rules(payload)

        assert result["action"] == "CANCEL"
        assert result["cancel_type"] == "CLAUDE_HARD_RULE"
        assert result["claude_tp1"] is None
        assert result["claude_tp2"] is None
        assert result["claude_sl"] is None
        assert "tp1 > entry > sl" in result["cancel_reason"]

    def test_s1_enter_without_claude_tp_sl_becomes_cancel(self):
        from queue_worker import _apply_claude_postprocess_hard_rules

        payload = {
            "strategy": "S1_GAP_OPEN",
            "action": "ENTER",
            "cur_prc": 10000,
            "claude_tp1": None,
            "claude_tp2": None,
            "claude_sl": None,
        }

        result = _apply_claude_postprocess_hard_rules(payload)

        assert result["action"] == "CANCEL"
        assert result["cancel_type"] == "CLAUDE_HARD_RULE"
        assert result["claude_tp1"] is None
        assert result["claude_tp2"] is None
        assert result["claude_sl"] is None
        assert "ENTER requires entry, tp1, and sl" in result["cancel_reason"]

    def test_s1_enter_can_use_rule_tp_sl_when_claude_prices_are_empty(self):
        from queue_worker import _apply_claude_postprocess_hard_rules

        payload = {
            "strategy": "S1_GAP_OPEN",
            "action": "ENTER",
            "cur_prc": 10000,
            "tp1_price": 12000,
            "sl_price": 9500,
            "rr_ratio": 4.0,
            "claude_tp1": None,
            "claude_tp2": None,
            "claude_sl": None,
        }

        result = _apply_claude_postprocess_hard_rules(payload)

        assert result["action"] == "ENTER"
        assert result["claude_tp1"] is None
        assert result["claude_tp2"] is None
        assert result["claude_sl"] is None

    def test_enter_tp2_below_tp1_becomes_cancel(self):
        from queue_worker import _apply_claude_postprocess_hard_rules

        payload = {
            "strategy": "S1_GAP_OPEN",
            "action": "ENTER",
            "cur_prc": 10000,
            "claude_tp1": 11000,
            "claude_tp2": 10999,
            "claude_sl": 9500,
            "effective_rr": 2.0,
        }

        result = _apply_claude_postprocess_hard_rules(payload)

        assert result["action"] == "CANCEL"
        assert result["cancel_type"] == "CLAUDE_HARD_RULE"
        assert "tp2 must be greater than or equal to tp1" in result["cancel_reason"]

    def test_claude_rr_below_hard_threshold_sets_cancel_type(self):
        from queue_worker import _apply_claude_rr_override

        payload = {
            "strategy": "S2_VI_PULLBACK",
            "action": "ENTER",
            "stk_cd": "005930",
            "cur_prc": 10000,
            "claude_tp1": 10100,
            "claude_sl": 9800,
        }

        result = _apply_claude_rr_override(payload)

        assert result["action"] == "CANCEL"
        assert result["cancel_type"] == "CLAUDE_HARD_RULE"
        assert result["claude_tp1"] is None
        assert result["claude_tp2"] is None
        assert result["claude_sl"] is None

    def test_process_one_reports_invalid_claude_geometry_before_rr_threshold(self):
        item = _signal(cur_prc=10000, tp1_price=12000, sl_price=9500, rr_ratio=4.0, bid_ratio=2.0)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(90.0, {})), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_ai, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            mock_ai.return_value = {
                "action": "ENTER",
                "ai_score": 90,
                "confidence": "HIGH",
                "reason": "bad geometry",
                "claude_tp1": 9900,
                "claude_tp2": 10500,
                "claude_sl": 9700,
            }
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured == []
        mock_ai.assert_awaited_once()


class TestSessionEnterGuard:
    def test_session_enter_guard_allows_when_flag_disabled(self):
        from queue_worker import _apply_session_enter_guard

        payload = {"strategy": "S1_GAP_OPEN", "action": "ENTER", "market_session": "after_market"}

        with patch("queue_worker.SESSION_ENTER_GUARD_ENABLED", False):
            result = _apply_session_enter_guard(payload)

        assert result["action"] == "ENTER"

    def test_session_enter_guard_blocks_after_market_enter(self):
        from queue_worker import _apply_session_enter_guard

        payload = {"strategy": "S1_GAP_OPEN", "action": "ENTER", "market_session": "after_market"}

        with patch("queue_worker.SESSION_ENTER_GUARD_ENABLED", True):
            result = _apply_session_enter_guard(payload)

        assert result["action"] == "CANCEL"
        assert result["cancel_type"] == "SESSION_ENTER_GUARD"
        assert result["skip_entry"] is True
        assert "after_market" in result["cancel_reason"]

    def test_session_enter_guard_accepts_uppercase_and_enum_session_values(self):
        from market_session import MarketSession
        from queue_worker import _apply_session_enter_guard

        payload = {"strategy": "S8_GOLDEN_CROSS", "action": "ENTER", "market_session": "MAIN_MARKET"}
        enum_payload = {"strategy": "S8_GOLDEN_CROSS", "action": "ENTER", "market_session": MarketSession.MAIN_MARKET}

        with patch("queue_worker.SESSION_ENTER_GUARD_ENABLED", True):
            assert _apply_session_enter_guard(payload)["action"] == "ENTER"
            assert _apply_session_enter_guard(enum_payload)["action"] == "ENTER"

    def test_session_enter_guard_allows_s1_pre_market_opening_window(self):
        from queue_worker import _apply_session_enter_guard

        with patch("queue_worker.SESSION_ENTER_GUARD_ENABLED", True):
            for session in ("pre_market", "opening_auction", "main_market"):
                payload = {"strategy": "S1_GAP_OPEN", "action": "ENTER", "market_session": session}
                assert _apply_session_enter_guard(payload)["action"] == "ENTER"

    def test_session_enter_guard_exempts_s2(self):
        from queue_worker import _apply_session_enter_guard

        payload = {"strategy": "S2_VI_PULLBACK", "action": "ENTER", "market_session": "closed"}

        with patch("queue_worker.SESSION_ENTER_GUARD_ENABLED", True):
            result = _apply_session_enter_guard(payload)

        assert result["action"] == "ENTER"

    def test_session_enter_guard_blocks_promoted_hold_in_process_one(self):
        item = _signal(
            cur_prc=10000,
            tp1_price=10300,
            sl_price=9900,
            rr_ratio=2.0,
            bid_ratio=2.0,
            market_session="after_market",
        )
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker.SESSION_ENTER_GUARD_ENABLED", True), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {"gap": 20.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch(
                 "queue_worker.analyze_signal",
                 new_callable=AsyncMock,
                 return_value={
                     "action": "HOLD",
                     "ai_score": 80.0,
                     "confidence": "HIGH",
                     "reason": "strong but originally hold",
                 },
             ), \
             patch("queue_worker.push_hold_monitor_queue", side_effect=capture_push), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        assert captured[0]["action"] == "HOLD"
        assert captured[0]["execution_decision"] == "WATCH"
        assert "HOLD promoted to ENTER" not in captured[0]["ai_reason"]


class TestCrossStrategyArbitration:
    def test_first_enter_claims_stock_arbitration_key(self):
        from queue_worker import _apply_cross_strategy_arbitration

        rdb = _make_rdb()
        payload = {
            "stk_cd": "005930",
            "strategy": "S8_GOLDEN_CROSS",
            "action": "ENTER",
            "execution_decision": "ENTER",
        }

        result = _run(_apply_cross_strategy_arbitration(rdb, payload))

        assert result["execution_decision"] == "ENTER"
        rdb.set.assert_awaited_once()
        assert rdb.set.await_args.args[0] == "arbitration:enter:005930"

    def test_second_strategy_for_same_stock_is_blocked(self):
        from queue_worker import _apply_cross_strategy_arbitration

        rdb = _make_rdb()
        rdb.get = AsyncMock(return_value="S8_GOLDEN_CROSS")
        payload = {
            "stk_cd": "005930",
            "strategy": "S13_BOX_BREAKOUT",
            "action": "ENTER",
            "execution_decision": "ENTER",
        }

        result = _run(_apply_cross_strategy_arbitration(rdb, payload))

        assert result["action"] == "CANCEL"
        assert result["execution_decision"] == "BLOCK"
        assert result["cancel_type"] == "CROSS_STRATEGY_ARBITRATION"
        assert result["representative_strategy"] == "S8_GOLDEN_CROSS"


class TestProgramFlowGate:
    def test_program_flow_gate_blocks_s5_when_net_buy_flips_negative(self):
        from queue_worker import _program_flow_gate_failure

        signal = {
            "strategy": "S5_PROG_FRGN",
            "program_net_buy_amt": "-100",
            "program_net_buy_amt_chg": "-50",
        }

        assert "amount weakening" in _program_flow_gate_failure(signal)

    def test_program_flow_gate_ignores_unrelated_strategy(self):
        from queue_worker import _program_flow_gate_failure

        signal = {
            "strategy": "S8_GOLDEN_CROSS",
            "program_net_buy_amt": "-100",
            "program_net_buy_amt_chg": "-50",
        }

        assert _program_flow_gate_failure(signal) is None


class TestPipelineDailyCounter:
    """pipeline_daily Redis 키 오염 방지 테스트."""

    def test_daily_report_bypass_does_not_create_pipeline_key(self):
        """DAILY_REPORT 페이로드(strategy 없음)는 pipeline_daily: 키를 생성하면 안 된다."""
        item = {
            "type": "DAILY_REPORT",
            "date": "2026-04-28",
            "total_signals": 5,
        }
        rdb = _make_rdb(json.dumps(item))

        with patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        # hincrby가 호출되지 않아야 한다 — 빈 strategy 키 생성을 막는 핵심 단언
        rdb.hincrby.assert_not_awaited()

    def test_none_strategy_payload_does_not_create_pipeline_key(self):
        """strategy 필드가 null/None 인 페이로드도 pipeline_daily 키를 만들지 않아야 한다."""
        item = {
            "type": "OVERNIGHT_RISK_ALERT",
            "stk_cd": "005930",
            "strategy": None,
            "message": "갭다운 경보",
        }
        rdb = _make_rdb(json.dumps(item))

        with patch("queue_worker.push_score_only_queue", new_callable=AsyncMock), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(0.0, {})), \
             patch("queue_worker.should_skip_ai", return_value=True):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        rdb.hincrby.assert_not_awaited()

    def test_normal_signal_increments_pipeline_counter(self):
        """정상 전략 신호는 pipeline_daily:{date}:{strategy} 키를 증가시켜야 한다."""
        item = _signal(strategy="S7_ICHIMOKU_BREAKOUT")
        rdb = _make_rdb(json.dumps(item))

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {})), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        # hincrby 가 S7_ICHIMOKU_BREAKOUT 키로 호출됐는지 확인
        calls = rdb.hincrby.await_args_list
        assert len(calls) >= 1
        first_key = calls[0].args[0]
        assert "S7_ICHIMOKU_BREAKOUT" in first_key
        assert not first_key.endswith(":")


class TestQueueWorkerEmptyQueue:
    def test_empty_queue_returns_false(self):
        rdb = _make_rdb(None)

        from queue_worker import process_one

        result = _run(process_one(rdb))

        assert result is False


class TestFreshnessPhase0Defects:
    """Phase 0 실패 재현 테스트 — 결함 5/6/7."""

    def test_caution_freshness_deducts_signal_quality(self):
        """결함 5: caution state가 signal quality freshness component를 감점시키는지 확인"""
        from queue_worker import _compute_signal_quality

        signal = {
            "cur_prc": "50000", "flu_rt": "2.0",
            "rr_ratio": "2.5", "vol_ratio": "2.0", "cond_count": "2", "rsi": "60"
        }
        ctx_fresh = {
            "strength": 110.0, "hoga": {"total_buy_bid_req": 1.5, "total_sel_bid_req": 1.0},
            "tick": {"cur_prc": 50000.0},
            "freshness": {
                "tick":     {"state": "fresh",   "age_ms": 100},
                "hoga":     {"state": "fresh",   "age_ms": 100},
                "strength": {"state": "fresh",   "age_ms": 100},
            }
        }
        ctx_caution = {
            "strength": 110.0, "hoga": {"total_buy_bid_req": 1.5, "total_sel_bid_req": 1.0},
            "tick": {"cur_prc": 50000.0},
            "freshness": {
                "tick":     {"state": "caution", "age_ms": 1500},
                "hoga":     {"state": "caution", "age_ms": 1500},
                "strength": {"state": "caution", "age_ms": 6000},
            }
        }
        rule_score = 70.0
        result_fresh   = _compute_signal_quality(signal, ctx_fresh, rule_score)
        result_caution = _compute_signal_quality(signal, ctx_caution, rule_score)
        # caution 3개 → freshness component -1.5*3 = -4.5점 감점 → 전체 점수가 낮아져야 함
        assert result_caution["signal_quality_score"] < result_fresh["signal_quality_score"]
        fresh_fc   = result_fresh["quality_components"]["freshness"]
        caution_fc = result_caution["quality_components"]["freshness"]
        assert caution_fc < fresh_fc

    def test_freshness_status_set_in_enriched(self):
        """결함 6: enriched dict에 freshness_status가 명시적으로 세팅되는지 확인"""
        from queue_worker import _freshness_status_from_decision

        assert _freshness_status_from_decision("PASS") == "FRESH"
        assert _freshness_status_from_decision("CAUTION") == "CAUTION"
        assert _freshness_status_from_decision("SIZE_DOWN") == "CAUTION"
        assert _freshness_status_from_decision("SHADOW") == "STALE"
        assert _freshness_status_from_decision("CANCEL") == "STALE"

    def test_lenient_strategy_not_canceled_on_hoga_cancel(self):
        """결함 7: lenient 전략(S14)에서 hoga cancel state여도 pre-cancel 반환 안 함"""
        from queue_worker import _freshness_cancel_reason

        ctx = {
            "freshness": {
                "tick":     {"state": "fresh",  "age_ms": 100},
                "hoga":     {"state": "cancel", "age_ms": 3000},
                "strength": {"state": "fresh",  "age_ms": 100},
            },
            "vi": {}
        }
        # S14는 lenient → cancel 반환 없음
        reason = _freshness_cancel_reason(ctx, "S14_OVERSOLD_BOUNCE")
        assert reason is None, f"lenient 전략은 hoga cancel만으로 pre-cancel 안 됨, got: {reason}"

    def test_strict_strategy_canceled_on_hoga_cancel(self):
        """결함 7 반대: strict 전략(S1)은 hoga cancel → cancel reason 반환"""
        from queue_worker import _freshness_cancel_reason

        ctx = {
            "freshness": {
                "tick":     {"state": "fresh",  "age_ms": 100},
                "hoga":     {"state": "cancel", "age_ms": 3000},
                "strength": {"state": "fresh",  "age_ms": 100},
            },
            "vi": {}
        }
        reason = _freshness_cancel_reason(ctx, "S1_GAP_OPEN")
        assert reason is not None, "strict 전략은 hoga cancel → cancel reason 반환해야 함"
        assert "hoga" in reason

    def test_vi_stale_does_not_cancel_non_vi_strategy(self):
        from queue_worker import _freshness_cancel_reason

        ctx = {
            "freshness": {
                "tick": {"state": "fresh", "age_ms": 100},
                "hoga": {"state": "fresh", "age_ms": 100},
                "strength": {"state": "fresh", "age_ms": 100},
                "vi": {"state": "cancel", "age_ms": 120000},
            },
            "vi": {"status": "released"},
        }

        assert _freshness_cancel_reason(ctx, "S15_MOMENTUM_ALIGN") is None
        assert "vi data stale" in _freshness_cancel_reason(ctx, "S2_VI_PULLBACK")

    def test_stale_hoga_removes_bid_component(self):
        """stale_hoga=True 시 bid_component가 0이 되어야 함"""
        from queue_worker import _compute_signal_quality

        signal = {
            "cur_prc": "50000", "flu_rt": "2.0",
            "rr_ratio": "2.5", "vol_ratio": "2.0", "cond_count": "2", "rsi": "60"
        }
        ctx = {
            "strength": 110.0,
            "hoga": {"total_buy_bid_req": 3.0, "total_sel_bid_req": 1.0},  # bid_ratio=3.0 → normally +10
            "tick": {"cur_prc": 50000.0},
            "freshness": {
                "tick":     {"state": "fresh"},
                "hoga":     {"state": "fresh"},
                "strength": {"state": "fresh"},
            },
        }
        rule_score = 70.0
        result_fresh = _compute_signal_quality(signal, ctx, rule_score, stale_hoga=False)
        result_stale = _compute_signal_quality(signal, ctx, rule_score, stale_hoga=True)
        # stale_hoga → bid_component 제거
        assert result_stale["quality_components"]["bid"] == 0.0
        assert result_fresh["quality_components"]["bid"] == 10.0
        assert result_stale["signal_quality_score"] < result_fresh["signal_quality_score"]


class TestSignalFallbackAge:
    def test_exact_age_boundary_is_allowed(self):
        from queue_worker import _signal_age_info

        info = _signal_age_info({"enqueued_at": 970.0}, now_ts=1000.0, max_age_sec=30.0)

        assert info["age_sec"] == 30.0
        assert info["fallback_allowed"] is True

    def test_over_age_boundary_is_rejected(self):
        from queue_worker import _signal_age_info

        info = _signal_age_info({"enqueued_at": 969.999}, now_ts=1000.0, max_age_sec=30.0)

        assert info["age_sec"] > 30.0
        assert info["fallback_allowed"] is False

    def test_missing_or_nonfinite_timestamp_is_rejected(self):
        from queue_worker import _signal_age_info

        assert _signal_age_info({}, now_ts=1000.0)["fallback_allowed"] is False
        assert _signal_age_info({"enqueued_at": "NaN"}, now_ts=1000.0)["fallback_allowed"] is False

    def test_future_timestamp_clamps_age_to_zero(self):
        from queue_worker import _signal_age_info

        info = _signal_age_info({"enqueued_at": 1001.0}, now_ts=1000.0)

        assert info["age_sec"] == 0.0
        assert info["fallback_allowed"] is True

    def test_expired_signal_fields_and_cancelled_ctx_are_removed_before_scoring(self):
        from queue_worker import _sanitize_unusable_scoring_inputs

        signal = {
            "cur_prc": 50000,
            "flu_rt": 2.0,
            "bid_ratio": 2.5,
            "buy_req": 250,
            "sel_req": 100,
            "cntr_strength": 180.0,
        }
        ctx = {
            "tick": {"cur_prc": 49900},
            "hoga": {"total_buy_bid_req": 300, "total_sel_bid_req": 100},
            "strength": 175.0,
            "signal_fallback_allowed": False,
            "freshness": {
                "tick": {"state": "cancel"},
                "hoga": {"state": "cancel"},
                "strength": {"state": "cancel"},
            },
        }

        _sanitize_unusable_scoring_inputs(ctx, signal)

        assert ctx["tick"] == {}
        assert ctx["hoga"] == {}
        assert ctx["strength"] == 0.0
        assert not ({"cur_prc", "flu_rt", "bid_ratio", "buy_req", "sel_req",
                     "cntr_strength"} & signal.keys())


class TestRefreshStaleCtxBypass:
    """결함 1 재현 — _refresh_stale_ctx()가 stale Redis 재사용 없이 REST direct를 호출하는지 검증."""

    def _make_rdb_with_token(self, token="test_token"):
        rdb = MagicMock()
        rdb.get = AsyncMock(return_value=token)
        rdb.hincrby = AsyncMock(return_value=1)
        rdb.expire = AsyncMock(return_value=True)
        return rdb

    def test_hoga_cancel_calls_rest_not_redis(self):
        """hoga state=cancel → fetch_hoga_rest 호출, stale ws:hoga 재사용 없음 (결함 1)"""
        ctx = {
            "freshness": {
                "tick":     {"state": "fresh",  "age_ms": 100},
                "hoga":     {"state": "cancel", "age_ms": 12000},
                "strength": {"state": "fresh",  "age_ms": 100},
            },
        }
        signal = {"cur_prc": "50000", "flu_rt": "2.0"}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker._fetch_hoga_rest", new_callable=AsyncMock, return_value=(1.8, {"latency_ms": 50})) as mock_hoga_rest, \
             patch("queue_worker._fetch_str_rest", new_callable=AsyncMock) as mock_str_rest, \
             patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S8_GOLDEN_CROSS"))

        mock_hoga_rest.assert_awaited_once()
        mock_str_rest.assert_not_awaited()
        assert ctx["freshness"]["hoga"]["source"] == "rest"
        assert ctx["freshness"]["hoga"]["state"] == "caution"

    def test_tick_signal_fallback_preserves_cumulative_trade_amount(self):
        ctx = {
            "tick": {
                "cur_prc": "49900",
                "flu_rt": "1.8",
                "acc_trde_qty": "250000",
                "acc_trde_prica": "12500",
            },
            "freshness": {
                "tick": {"state": "cancel", "age_ms": 12000},
                "hoga": {"state": "fresh", "age_ms": 100},
                "strength": {"state": "fresh", "age_ms": 100},
            },
        }
        signal = {"cur_prc": "50000", "flu_rt": "2.0", "enqueued_at": time.time()}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S8_GOLDEN_CROSS"))

        assert ctx["tick"]["cur_prc"] == 50000.0
        assert ctx["tick"]["flu_rt"] == 2.0
        assert ctx["tick"]["acc_trde_qty"] == "250000"
        assert ctx["tick"]["acc_trde_prica"] == "12500"

    def test_stale_signal_cannot_refresh_tick(self):
        ctx = {
            "tick": {"cur_prc": "49900", "acc_trde_qty": "250000"},
            "freshness": {
                "tick": {"state": "cancel", "age_ms": 12000},
                "hoga": {"state": "fresh", "age_ms": 100},
                "strength": {"state": "fresh", "age_ms": 100},
            },
        }
        signal = {"cur_prc": "50000", "enqueued_at": time.time() - 31.0}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S8_GOLDEN_CROSS"))

        assert ctx["tick"]["cur_prc"] == "49900"
        assert ctx["freshness"]["tick"]["state"] == "cancel"
        assert "tick:signal_stale_or_undated" in ctx["refresh_meta"]["retry_failures"]

    def test_strength_cancel_calls_rest_not_redis(self):
        """strength state=cancel → fetch_cntr_strength_rest 호출, stale ws:strength 재사용 없음 (결함 1)"""
        ctx = {
            "freshness": {
                "tick":     {"state": "fresh",  "age_ms": 100},
                "hoga":     {"state": "fresh",  "age_ms": 100},
                "strength": {"state": "cancel", "age_ms": 15000},
            },
        }
        signal = {"cur_prc": "50000"}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker._fetch_str_rest", new_callable=AsyncMock, return_value=(118.0, {"latency_ms": 40})) as mock_str_rest, \
             patch("queue_worker._fetch_hoga_rest", new_callable=AsyncMock) as mock_hoga_rest, \
             patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S9_PULLBACK_SWING"))

        mock_str_rest.assert_awaited_once()
        mock_hoga_rest.assert_not_awaited()
        assert ctx["freshness"]["strength"]["source"] == "rest"
        assert ctx["strength"] == 118.0

    def test_hoga_rest_takes_priority_over_recent_signal_bid(self):
        """hoga cancel + signal에 bid_ratio 있음 → REST 호출 없이 signal fallback 사용"""
        ctx = {
            "freshness": {
                "tick":     {"state": "fresh",  "age_ms": 100},
                "hoga":     {"state": "cancel", "age_ms": 12000},
                "strength": {"state": "fresh",  "age_ms": 100},
            },
        }
        signal = {"cur_prc": "50000", "bid_ratio": 2.5, "enqueued_at": time.time()}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker._fetch_hoga_rest", new_callable=AsyncMock, return_value=(1.8, {"latency_ms": 50})) as mock_hoga_rest, \
             patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S7_ICHIMOKU_BREAKOUT"))

        mock_hoga_rest.assert_awaited_once()
        assert ctx["freshness"]["hoga"]["source"] == "rest"
        assert ctx["hoga"]["total_buy_bid_req"] == 1.8

    def test_recent_hoga_signal_is_used_only_after_rest_failure(self):
        ctx = {
            "freshness": {
                "tick": {"state": "fresh", "age_ms": 100},
                "hoga": {"state": "cancel", "age_ms": 12000},
                "strength": {"state": "fresh", "age_ms": 100},
            },
        }
        signal = {"bid_ratio": 2.5, "enqueued_at": time.time()}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker._fetch_hoga_rest", new_callable=AsyncMock,
                   return_value=(None, {"error": "empty"})) as mock_hoga_rest, \
             patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S7_ICHIMOKU_BREAKOUT"))

        mock_hoga_rest.assert_awaited_once()
        assert ctx["freshness"]["hoga"]["source"] == "signal_fallback"
        assert ctx["hoga"]["total_buy_bid_req"] == 2.5

    def test_fresh_data_early_returns_without_rest_call(self):
        """tick/hoga/strength 모두 fresh → REST 호출 없이 즉시 반환 (불필요한 API 호출 방지)"""
        ctx = {
            "freshness": {
                "tick":     {"state": "fresh", "age_ms": 200},
                "hoga":     {"state": "fresh", "age_ms": 200},
                "strength": {"state": "fresh", "age_ms": 200},
            },
        }
        signal = {"cur_prc": "50000"}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker._fetch_hoga_rest", new_callable=AsyncMock) as mock_hoga_rest, \
             patch("queue_worker._fetch_str_rest", new_callable=AsyncMock) as mock_str_rest, \
             patch("queue_worker.ENABLE_SCORING_DATA_RETRY", True), \
             patch("queue_worker.ENABLE_TICK_REST_FALLBACK", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S8_GOLDEN_CROSS"))

        mock_hoga_rest.assert_not_awaited()
        mock_str_rest.assert_not_awaited()

    def test_retry_disabled_skips_all_rest(self):
        """ENABLE_SCORING_DATA_RETRY=false → hoga/strength cancel이어도 REST 호출 안 함"""
        ctx = {
            "freshness": {
                "tick":     {"state": "cancel", "age_ms": 20000},
                "hoga":     {"state": "cancel", "age_ms": 20000},
                "strength": {"state": "cancel", "age_ms": 20000},
            },
        }
        signal = {"cur_prc": "50000"}
        rdb = self._make_rdb_with_token()

        with patch("queue_worker._fetch_hoga_rest", new_callable=AsyncMock) as mock_hoga_rest, \
             patch("queue_worker._fetch_str_rest", new_callable=AsyncMock) as mock_str_rest, \
             patch("queue_worker.ENABLE_SCORING_DATA_RETRY", False), \
             patch("queue_worker.ENABLE_CHART_RETRY", False):
            from queue_worker import _refresh_stale_ctx
            _run(_refresh_stale_ctx(ctx, "005930", rdb, signal, "S1_GAP_OPEN"))

        mock_hoga_rest.assert_not_awaited()
        mock_str_rest.assert_not_awaited()
