import asyncio
import json
import os
import sys
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
    rdb.hincrby = AsyncMock(return_value=1)
    rdb.lrange = AsyncMock(return_value=[])
    rdb.get = AsyncMock(return_value=None)
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
    return {"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}, "ws_online": False}


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
        item = _signal()
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
             ), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        assert captured[0]["rule_score"] == 75.0
        assert captured[0]["ai_score"] == 81.0
        assert captured[0]["action"] == "ENTER"

    def test_legacy_float_rule_score_is_tolerated(self):
        item = _signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=75.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["rule_score"] == 75.0
        assert captured[0]["action"] == "CANCEL"

    def test_signal_cntr_strength_is_used_for_market_ctx_and_payload(self):
        item = _signal(cntr_strength=257.2)
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
             patch("queue_worker.analyze_signal", side_effect=fake_analyze), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert seen_ctx["strength"] == 257.2
        assert captured[0]["cntr_strength"] == 257.2
        assert "257.2" in captured[0]["ai_reason"]

    def test_high_score_hold_is_promoted_to_enter(self):
        item = _signal(cur_prc=10000, tp1_price=10300, sl_price=9900, rr_ratio=2.0, bid_ratio=2.0)
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
                     "action": "HOLD",
                     "ai_score": 80.0,
                     "confidence": "HIGH",
                     "reason": "strong but originally hold",
                 },
             ), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        assert captured[0]["action"] == "ENTER"
        assert captured[0]["ai_score"] == 80.0
        assert captured[0]["cancel_reason"] is None
        assert "HOLD promoted to ENTER" in captured[0]["ai_reason"]


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
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["action"] == "CANCEL"
        assert captured[0]["cancel_reason"] == "AI analysis unavailable"
        assert captured[1]["signal_grade"] == "RULE_ONLY"
        assert captured[1]["type"] == "RULE_ONLY_SIGNAL"

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
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["action"] == "CANCEL"
        assert captured[0]["cancel_reason"] == "AI daily limit reached"
        assert captured[1]["signal_grade"] == "RULE_ONLY"
        assert captured[1]["type"] == "RULE_ONLY_SIGNAL"
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
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["action"] == "CANCEL"
        assert captured[0]["cancel_reason"] == "weak follow-through"
        assert captured[1]["type"] == "RULE_ONLY_SIGNAL"
        assert captured[1]["signal_grade"] == "RULE_ONLY"
        assert captured[1]["cur_prc"] == 18880
        assert captured[1]["tp1_price"] == 20050
        assert captured[1]["sl_price"] == 17480

    def test_s4_hard_gate_failure_cancels_before_ai(self):
        item = _signal(strategy="S4_BIG_CANDLE", cntr_strength=124.9, bid_ratio=1.39)
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(80.0, {"body": 30.0})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock) as mock_limit, \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["action"] == "CANCEL"
        assert "Hard gate failed" in captured[0]["ai_reason"]
        mock_limit.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_rr_prefilter_below_080_cancels_before_ai(self):
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
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert captured[0]["action"] == "CANCEL"
        assert "below 0.80" in captured[0]["cancel_reason"]
        assert "below 0.80" in captured[0]["ai_reason"]
        mock_limit.assert_not_awaited()
        mock_analyze.assert_not_awaited()

    def test_borderline_rr_calls_ai_with_quality_metadata(self):
        item = _signal(cur_prc=10000, tp1_price=10300, sl_price=9900, rr_ratio=0.9, vol_ratio=1.5)
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
        assert captured_signal["rr_quality_bucket"] == "caution"
        assert "signal_quality_score" in captured_signal
        assert captured_signal["performance_ev_status"] == "insufficient_data"

    def test_claude_tp_sl_recalculates_rr_in_published_payload(self):
        item = _signal(cur_prc=10000, tp1_price=10200, sl_price=9900, rr_ratio=0.9, min_rr_ratio=1.0)
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

    def test_s1_claude_enter_is_final_cancel_when_effective_rr_below_hard_rule(self):
        item = _signal(cur_prc=10000, tp1_price=12000, sl_price=9000, rr_ratio=2.0, min_rr_ratio=1.0, bid_ratio=2.0)
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
                     "reason": "claude says enter",
                     "claude_tp1": 10500,
                     "claude_tp2": 10600,
                     "claude_sl": 9700,
                 },
             ), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        payload = captured[0]
        assert payload["action"] == "CANCEL"
        assert payload["cancel_type"] == "CLAUDE_HARD_RULE"
        assert payload["claude_tp1"] is None
        assert payload["claude_tp2"] is None
        assert payload["claude_sl"] is None
        assert "S1 effective R:R" in payload["cancel_reason"]


class TestClaudeRiskPostprocess:
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
