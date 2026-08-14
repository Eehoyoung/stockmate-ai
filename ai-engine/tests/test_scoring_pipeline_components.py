import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_execution_decision_maps_legacy_actions():
    from scoring_pipeline.execution_decision import (
        apply_execution_decision,
        execution_decision_from_action,
    )

    assert execution_decision_from_action("ENTER") == "ENTER"
    assert execution_decision_from_action("HOLD") == "WATCH"
    assert execution_decision_from_action("CANCEL") == "BLOCK"

    payload = apply_execution_decision({}, "WATCH", reason="wait")
    assert payload["action"] == "HOLD"
    assert payload["execution_decision"] == "WATCH"
    assert payload["skip_entry"] is True
    assert payload["execution_reason"] == "wait"


def test_session_enter_guard_blocks_after_market_enter():
    from scoring_pipeline.execution_decision import apply_session_enter_guard

    payload = {"strategy": "S1_GAP_OPEN", "action": "ENTER", "market_session": "after_market"}

    result = apply_session_enter_guard(
        payload,
        enabled=True,
        enter_sessions={"S1_GAP_OPEN": {"pre_market", "opening_auction", "main_market"}},
        blocklist={"after_market"},
        exempt_types=set(),
    )

    assert result["action"] == "CANCEL"
    assert result["cancel_type"] == "SESSION_ENTER_GUARD"
    assert result["skip_entry"] is True


def test_data_quality_and_freshness_decisions():
    from scoring_pipeline.data_quality import (
        compute_data_quality,
        compute_freshness_decision,
        freshness_status_from_decision,
    )

    freshness = {"tick": {"state": "cancel"}, "hoga": {"state": "ok"}}

    assert compute_freshness_decision(
        freshness,
        "S10_NEW_HIGH",
        strict_cancel_gate={"S10_NEW_HIGH"},
    ) == "CANCEL"
    assert freshness_status_from_decision("SIZE_DOWN") == "CAUTION"

    quality = compute_data_quality(["cur_prc", "hoga"], "CAUTION", {"fallback_used": True})
    assert quality["data_quality_score"] == 55.0
    assert quality["data_quality_decision"] == "SIZE_DOWN"
    assert quality["fallback_used"] is True


def test_risk_decision_keeps_hold_as_watch():
    from scoring_pipeline.risk_decision import keep_hold_as_watch, rr_quality_bucket

    action, confidence, reason, cancel_reason = keep_hold_as_watch(
        action="HOLD",
        confidence="",
        reason="wait pullback",
        cancel_reason=None,
        ai_score=91,
    )

    assert action == "HOLD"
    assert confidence == "MEDIUM"
    assert cancel_reason is None
    assert "ai_score alone cannot promote to ENTER" in reason
    assert rr_quality_bucket(0.7, hard_cancel_threshold=0.8, caution_threshold=1.2) == "hard_cancel"


def test_status_decision_routes_low_rule_score_to_watch_when_quality_is_usable():
    from scoring_pipeline.status_decision import select_pre_ai_decision

    result = select_pre_ai_decision(
        skip_ai=True,
        rescue_reason=None,
        rule_score_value=42.0,
        threshold=60.0,
        quality_score=50.0,
        watch_min_quality=45.0,
        rr_prefilter_reason=None,
        s8_zone_gate_reason=None,
        s1_fallback_quality_reason=None,
        s1_execution_policy=None,
        hard_gate_reason=None,
        program_flow_reason=None,
        stale_reason=None,
        strategy="S9_PULLBACK_SWING",
    )

    assert result["terminal"] is True
    assert result["action"] == "HOLD"
    assert result["decision_stage"] == "WATCH_RULE_THRESHOLD"
    assert result["metrics"] == ["watch_rule_threshold"]


def test_status_decision_routes_rr_prefilter_to_watch_before_ai():
    from scoring_pipeline.status_decision import select_pre_ai_decision

    result = select_pre_ai_decision(
        skip_ai=False,
        rescue_reason="rescued",
        rule_score_value=58.0,
        threshold=60.0,
        quality_score=80.0,
        watch_min_quality=45.0,
        rr_prefilter_reason="R:R 1.00 below 1.50(neutral)",
        s8_zone_gate_reason=None,
        s1_fallback_quality_reason=None,
        s1_execution_policy=None,
        hard_gate_reason=None,
        program_flow_reason=None,
        stale_reason=None,
        strategy="S8_GOLDEN_CROSS",
        current_s8_zone_status="existing",
    )

    assert result["terminal"] is True
    assert result["action"] == "HOLD"
    assert result["cancel_type"] == "S8_WAIT_PULLBACK"
    assert result["signal_updates"]["rule_threshold_rescued"] is True
    assert result["signal_updates"]["s8_zone_status"] == "existing"
    assert result["metrics"] == ["rule_threshold_rescue", "watch_rr"]


def test_status_decision_allows_ai_when_no_pre_ai_gate_blocks():
    from scoring_pipeline.status_decision import select_pre_ai_decision

    result = select_pre_ai_decision(
        skip_ai=False,
        rescue_reason=None,
        rule_score_value=75.0,
        threshold=60.0,
        quality_score=90.0,
        watch_min_quality=45.0,
        rr_prefilter_reason=None,
        s8_zone_gate_reason=None,
        s1_fallback_quality_reason=None,
        s1_execution_policy=None,
        hard_gate_reason=None,
        program_flow_reason=None,
        stale_reason=None,
        strategy="S10_NEW_HIGH",
    )

    assert result["terminal"] is False
    assert result["metrics"] == ["rule_pass"]


def test_ai_decision_success_normalizes_hold_policy():
    from scoring_pipeline.ai_decision import evaluate_ai_decision

    async def check_limit(_rdb):
        return True

    async def analyze(_signal, _ctx, _rule_score, rdb=None):
        return {"action": "HOLD", "ai_score": 90, "confidence": "", "reason": "wait"}

    def hold_policy(**kwargs):
        return "HOLD", kwargs["confidence"] or "MEDIUM", kwargs["reason"] + " retained", kwargs["cancel_reason"]

    result = asyncio.run(evaluate_ai_decision(
        signal={"strategy": "S9_PULLBACK_SWING"},
        ctx={},
        rule_score_value=70.0,
        rdb=object(),
        check_daily_limit_fn=check_limit,
        analyze_signal_fn=analyze,
        normalize_score_fn=float,
        hold_policy_fn=hold_policy,
    ))

    assert result["action"] == "HOLD"
    assert result["confidence"] == "MEDIUM"
    assert result["ai_score"] == 90.0
    assert result["metrics"] == ["cancel_ai"]


def test_ai_decision_daily_limit_returns_cancel_without_analyze():
    from scoring_pipeline.ai_decision import evaluate_ai_decision

    async def check_limit(_rdb):
        return False

    async def analyze(_signal, _ctx, _rule_score, rdb=None):
        raise AssertionError("analyze should not be called")

    result = asyncio.run(evaluate_ai_decision(
        signal={"strategy": "S9_PULLBACK_SWING"},
        ctx={},
        rule_score_value=70.0,
        rdb=object(),
        check_daily_limit_fn=check_limit,
        analyze_signal_fn=analyze,
        normalize_score_fn=float,
        hold_policy_fn=lambda **kwargs: ("ENTER", "HIGH", "", None),
    ))

    assert result["action"] == "CANCEL"
    assert result["cancel_type"] == "AI_DAILY_LIMIT"
    assert result["metrics"] == ["cancel_ai_limit"]


def test_ai_decision_hold_recheck_limit_retains_monitor_without_analyze():
    from scoring_pipeline.ai_decision import evaluate_ai_decision

    async def check_limit(_rdb):
        return False

    async def analyze(_signal, _ctx, _rule_score, rdb=None):
        raise AssertionError("analyze should not be called")

    result = asyncio.run(evaluate_ai_decision(
        signal={"strategy": "S11_FRGN_CONT", "hold_monitor_recheck": True},
        ctx={},
        rule_score_value=80.0,
        rdb=object(),
        check_daily_limit_fn=check_limit,
        analyze_signal_fn=analyze,
        normalize_score_fn=float,
        hold_policy_fn=lambda **kwargs: ("ENTER", "HIGH", "", None),
    ))

    assert result["action"] == "HOLD"
    assert result["cancel_type"] is None
    assert result["metrics"] == ["hold_recheck_ai_limit"]


def test_ai_decision_failure_returns_unavailable_cancel():
    from scoring_pipeline.ai_decision import evaluate_ai_decision

    async def check_limit(_rdb):
        return True

    async def analyze(_signal, _ctx, _rule_score, rdb=None):
        raise RuntimeError("boom")

    result = asyncio.run(evaluate_ai_decision(
        signal={"strategy": "S9_PULLBACK_SWING"},
        ctx={},
        rule_score_value=70.0,
        rdb=object(),
        check_daily_limit_fn=check_limit,
        analyze_signal_fn=analyze,
        normalize_score_fn=float,
        hold_policy_fn=lambda **kwargs: ("ENTER", "HIGH", "", None),
    ))

    assert result["action"] == "CANCEL"
    assert result["cancel_type"] == "AI_UNAVAILABLE"
    assert result["metrics"] == ["cancel_ai_unavailable"]
    assert isinstance(result["error"], RuntimeError)


def test_publisher_routes_watch_to_hold_monitor_queue():
    from scoring_pipeline.publisher import route_execution_payload

    calls = []

    async def push_hold(rdb, payload):
        calls.append(("hold", rdb, payload))

    async def push_score(rdb, payload):
        calls.append(("score", rdb, payload))

    async def incr(rdb, strategy, field):
        calls.append(("metric", rdb, strategy, field))

    result = asyncio.run(route_execution_payload(
        rdb="redis",
        payload={"execution_decision": "WATCH"},
        strategy="S9_PULLBACK_SWING",
        stk_cd="005930",
        execution_decision="WATCH",
        display_reason="wait",
        push_hold_monitor_queue_fn=push_hold,
        push_score_only_queue_fn=push_score,
        incr_pipeline_fn=incr,
    ))

    assert result == "WATCH"
    assert calls == [
        ("hold", "redis", {"execution_decision": "WATCH"}),
        ("metric", "redis", "S9_PULLBACK_SWING", "hold_monitor"),
        ("score", "redis", {"execution_decision": "WATCH", "type": "HOLD_WATCH", "hold_reason": "wait"}),
    ]


def test_publisher_requeues_watch_recheck_without_duplicate_notice():
    from scoring_pipeline.publisher import route_execution_payload

    calls = []
    payload = {"execution_decision": "WATCH", "hold_monitor_recheck": True}

    async def push_hold(rdb, queued_payload):
        calls.append(("hold", rdb, queued_payload))

    async def push_score(rdb, queued_payload):
        calls.append(("score", rdb, queued_payload))

    async def incr(rdb, strategy, metric):
        calls.append(("metric", rdb, strategy, metric))

    result = asyncio.run(route_execution_payload(
        rdb="redis",
        payload=payload,
        execution_decision="WATCH",
        strategy="S11_FRGN_CONT",
        stk_cd="101670",
        display_reason="wait",
        push_hold_monitor_queue_fn=push_hold,
        push_score_only_queue_fn=push_score,
        incr_pipeline_fn=incr,
    ))

    assert result == "WATCH"
    assert calls == [
        ("hold", "redis", payload),
        ("metric", "redis", "S11_FRGN_CONT", "hold_monitor"),
    ]


def test_publisher_routes_enter_to_score_queue():
    from scoring_pipeline.publisher import route_execution_payload

    calls = []

    async def push_hold(_rdb, _payload):
        raise AssertionError("hold monitor should not be used")

    async def push_score(rdb, payload):
        calls.append(("score", rdb, payload))

    async def incr(_rdb, _strategy, _field):
        raise AssertionError("enter publish metric is handled by queue_worker")

    result = asyncio.run(route_execution_payload(
        rdb="redis",
        payload={"execution_decision": "ENTER"},
        strategy="S1_GAP_OPEN",
        stk_cd="005930",
        execution_decision="ENTER",
        display_reason="go",
        push_hold_monitor_queue_fn=push_hold,
        push_score_only_queue_fn=push_score,
        incr_pipeline_fn=incr,
    ))

    assert result == "ENTER"
    assert calls == [("score", "redis", {"execution_decision": "ENTER"})]


def test_publisher_keeps_block_internal():
    from scoring_pipeline.publisher import route_execution_payload

    async def fail_push(_rdb, _payload):
        raise AssertionError("blocked payload should not be queued")

    async def fail_incr(_rdb, _strategy, _field):
        raise AssertionError("blocked payload should not increment queue metrics")

    result = asyncio.run(route_execution_payload(
        rdb="redis",
        payload={"execution_decision": "BLOCK"},
        strategy="S1_GAP_OPEN",
        stk_cd="005930",
        execution_decision="BLOCK",
        display_reason="blocked",
        push_hold_monitor_queue_fn=fail_push,
        push_score_only_queue_fn=fail_push,
        incr_pipeline_fn=fail_incr,
    ))

    assert result == "BLOCK"


def test_status_metrics_record_freshness_and_execution_decisions():
    from datetime import datetime, timezone

    from scoring_pipeline.status_metrics import (
        record_execution_decision_metric,
        record_freshness_decision_metric,
    )

    class FakeRedis:
        def __init__(self):
            self.calls = []

        async def hincrby(self, key, field, amount):
            self.calls.append(("hincrby", key, field, amount))

        async def incr(self, key):
            self.calls.append(("incr", key))

        async def expire(self, key, ttl):
            self.calls.append(("expire", key, ttl))

    rdb = FakeRedis()
    freshness_key = asyncio.run(record_freshness_decision_metric(
        rdb,
        strategy="S10_NEW_HIGH",
        decision="CANCEL",
        ttl_sec=172800,
        now_fn=lambda: datetime(2026, 7, 4, tzinfo=timezone.utc),
    ))
    decision_key = asyncio.run(record_execution_decision_metric(
        rdb,
        strategy="S10_NEW_HIGH",
        decision="BLOCK",
        ttl_sec=600,
    ))

    assert freshness_key == "status:freshness_decision:2026-07-04:S10_NEW_HIGH"
    assert decision_key == "status:decisions_10m:S10_NEW_HIGH:BLOCK"
    assert rdb.calls == [
        ("hincrby", "status:freshness_decision:2026-07-04:S10_NEW_HIGH", "CANCEL", 1),
        ("expire", "status:freshness_decision:2026-07-04:S10_NEW_HIGH", 172800),
        ("incr", "status:decisions_10m:S10_NEW_HIGH:BLOCK"),
        ("expire", "status:decisions_10m:S10_NEW_HIGH:BLOCK", 600),
    ]


def test_status_metrics_are_best_effort():
    from scoring_pipeline.status_metrics import record_execution_decision_metric

    class FailingRedis:
        async def incr(self, _key):
            raise RuntimeError("redis down")

    result = asyncio.run(record_execution_decision_metric(
        FailingRedis(),
        strategy="S10_NEW_HIGH",
        decision="BLOCK",
        ttl_sec=600,
    ))

    assert result is None


def test_market_data_observability_normalizes_source_age_cache_and_budget():
    from scoring_pipeline.status_metrics import build_market_data_observability

    snapshot = build_market_data_observability({
        "freshness": {
            "tick": {"state": "fresh", "age_ms": 120},
            "hoga": {"state": "caution", "age_ms": 45.5, "source": "rest"},
            "strength": {"state": "cancel", "age_ms": 12000},
            "vi": {"state": "missing", "age_ms": None},
        },
        "refresh_meta": {
            "market_data_sources": {"hoga": "rest"},
            "data_refresh_attempted": {"hoga": "cancel", "strength": "cancel"},
            "retry_failures": ["strength:rest_no_data", "hold_monitor_rest_budget_exhausted"],
        },
    })

    assert snapshot["schema_version"] == 1
    assert snapshot["fields"]["tick"] == {"state": "fresh", "source": "redis", "age_ms": 120}
    assert snapshot["fields"]["hoga"] == {"state": "caution", "source": "rest", "age_ms": 45.5}
    assert snapshot["fields"]["vi"]["source"] == "missing"
    assert snapshot["cache_fields"] == ["tick", "strength"]
    assert snapshot["rest"]["fallback_used"] is True
    assert snapshot["rest"]["fallback_fields"] == ["hoga"]
    assert snapshot["rest"]["attempted_fields"] == ["hoga", "strength"]
    assert snapshot["rest"]["failure_classes"] == ["budget_exhausted", "rest_no_data"]
    assert snapshot["rest"]["budget_state"] == "exhausted"


def test_market_data_observability_records_low_cardinality_daily_counters():
    from datetime import datetime, timezone

    from scoring_pipeline.status_metrics import record_market_data_observability_metric

    class FakeRedis:
        def __init__(self):
            self.calls = []

        async def hincrby(self, key, field, amount):
            self.calls.append(("hincrby", key, field, amount))

        async def expire(self, key, ttl):
            self.calls.append(("expire", key, ttl))

    snapshot = {
        "fields": {
            "tick": {"state": "fresh", "source": "redis"},
            "hoga": {"state": "caution", "source": "rest"},
        },
        "cache_fields": ["tick"],
        "rest": {
            "fallback_used": True,
            "budget_state": "exhausted",
            "failure_classes": ["budget_exhausted", "rest_no_data"],
        },
    }
    rdb = FakeRedis()

    key = asyncio.run(record_market_data_observability_metric(
        rdb,
        strategy="S1_GAP_OPEN",
        snapshot=snapshot,
        ttl_sec=172800,
        now_fn=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
    ))

    assert key == "status:market_data_observability:2026-07-19:S1_GAP_OPEN"
    fields = [call[2] for call in rdb.calls if call[0] == "hincrby"]
    assert fields == [
        "tick.state.fresh",
        "tick.source.redis",
        "hoga.state.caution",
        "hoga.source.rest",
        "rest.fallback_used.true",
        "rest.budget.exhausted",
        "cache.used.true",
        "rest.failure.budget_exhausted",
        "rest.failure.rest_no_data",
    ]
    assert rdb.calls[-1] == ("expire", key, 172800)


def test_failure_handler_builds_and_publishes_processing_error():
    from scoring_pipeline.failure_handler import handle_processing_failure

    class FakeRedis:
        def __init__(self):
            self.calls = []

        async def lpush(self, key, payload):
            self.calls.append(("lpush", key, payload))

        async def expire(self, key, ttl):
            self.calls.append(("expire", key, ttl))

    pushed = []

    async def push_score(rdb, payload):
        pushed.append((rdb, payload))

    def normalize(payload):
        payload["normalized"] = True

    rdb = FakeRedis()
    payload = asyncio.run(handle_processing_failure(
        rdb=rdb,
        item={"stk_cd": "005930", "strategy": "S8_GOLDEN_CROSS"},
        strategy="S8_GOLDEN_CROSS",
        stk_cd="005930",
        error=RuntimeError("boom"),
        normalize_signal_prices_fn=normalize,
        push_score_only_queue_fn=push_score,
        now_fn=lambda: 123.0,
    ))

    assert payload["action"] == "FAILED"
    assert payload["type"] == "PROCESSING_ERROR"
    assert payload["execution_decision"] == "BLOCK"
    assert payload["normalized"] is True
    assert payload["error_ts"] == 123.0
    assert rdb.calls[0][0:2] == ("lpush", "error_queue")
    assert rdb.calls[1] == ("expire", "error_queue", 86400)
    assert pushed == [(rdb, payload)]


def test_persistence_payload_helpers_resolve_shadow_and_market_fields():
    from scoring_pipeline.persistence_payloads import (
        build_cancel_shadow_detail,
        resolve_market_flu_rt,
        resolve_shadow_prices,
    )

    def fv(value, default=0.0):
        if value is None:
            return default
        return float(value)

    market_flu = resolve_market_flu_rt(
        {"market_type": "101"},
        {"kospi_flu_rt": 0.5, "kosdaq_flu_rt": 1.2},
        normalize_market_type_fn=lambda value: value,
    )
    prices = resolve_shadow_prices(
        {"entry_price": "100", "claude_tp1": "112", "tp2_price": "120", "claude_sl": "95"},
        fv_fn=fv,
    )
    detail = build_cancel_shadow_detail(
        {
            "decision_stage": "WATCH_RR",
            "rule_threshold_rescued": 1,
            "rr_ratio": "1.4",
            "effective_rr": None,
        },
        cancel_type="RR",
        cancel_reason="wait",
        fv_fn=fv,
    )

    assert market_flu == 1.2
    assert prices == {"entry_price": 100.0, "tp1_price": 112.0, "tp2_price": 120.0, "sl_price": 95.0}
    assert detail["cancel_type"] == "RR"
    assert detail["decision_stage"] == "WATCH_RR"
    assert detail["rule_threshold_rescued"] is True
    assert detail["rr_ratio"] == 1.4
    assert detail["effective_rr"] is None
