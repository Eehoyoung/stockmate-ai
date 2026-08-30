"""필수 실시간 시장데이터 ENTER fail-closed 테스트."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _payload(sources):
    return {"action": "ENTER", "market_data_sources": sources}


def test_fresh_rest_only_is_blocked():
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "rest", "strength": "rest"})
    ctx = {"freshness": {
        "tick": {"age_ms": 120},
        "strength": {"age_ms": 300},
    }}
    reason = _rest_only_enter_stale_reason(payload, ctx)
    assert "tick:source=rest" in reason
    assert "hoga:source=missing" in reason


def test_stale_rest_is_blocked_with_reason():
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "rest"})
    ctx = {"freshness": {"tick": {"age_ms": 9000}}}
    reason = _rest_only_enter_stale_reason(payload, ctx)
    assert reason is not None
    assert "tick" in reason and "9000ms" in reason


def test_unknown_age_is_blocked():
    """나이를 알 수 없으면 완화하지 않고 종전대로 차단한다."""
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "rest"})
    assert _rest_only_enter_stale_reason(payload, {"freshness": {}}) is not None


def test_no_verifiable_realtime_kind_is_blocked():
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"chart_daily": "rest"})
    reason = _rest_only_enter_stale_reason(payload, {"freshness": {}})
    assert "tick:source=missing" in reason


def test_mixed_sources_are_blocked_when_required_kind_uses_rest():
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "redis", "hoga": "kiwoom_ws", "strength": "rest"})
    ctx = {"freshness": {
        "tick": {"age_ms": 100, "state": "fresh"},
        "hoga": {"age_ms": 100, "state": "fresh"},
        "strength": {"age_ms": 100, "state": "fresh"},
    }}
    assert "strength:source=rest" in _rest_only_enter_stale_reason(payload, ctx)


def test_signal_fallback_is_blocked():
    from queue_worker import _rest_only_enter_stale_reason, _is_rest_only_sources

    sources = {"tick": "signal_fallback"}
    assert _is_rest_only_sources(sources) is False
    assert "tick:source=signal_fallback" in _rest_only_enter_stale_reason(
        _payload(sources), {"freshness": {}}
    )


def test_empty_sources_not_treated_as_rest_only():
    from queue_worker import _is_rest_only_sources

    assert _is_rest_only_sources({}) is False
    assert _is_rest_only_sources(None) is False


def test_fresh_ws_at_boundary_is_allowed():
    from queue_worker import _rest_only_enter_stale_reason, REST_ENTER_MAX_AGE_MS

    payload = _payload({"tick": "redis", "hoga": "kiwoom_ws", "strength": "redis"})
    ctx = {"freshness": {
        kind: {"age_ms": REST_ENTER_MAX_AGE_MS, "state": "fresh"}
        for kind in ("tick", "hoga", "strength")
    }}
    assert _rest_only_enter_stale_reason(payload, ctx) is None

    ctx_over = {"freshness": {
        kind: {
            "age_ms": REST_ENTER_MAX_AGE_MS + (1 if kind == "tick" else 0),
            "state": "fresh",
        }
        for kind in ("tick", "hoga", "strength")
    }}
    assert _rest_only_enter_stale_reason(payload, ctx_over) is not None


def test_caution_ws_is_blocked_even_when_age_is_small():
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "redis", "hoga": "redis", "strength": "redis"})
    ctx = {"freshness": {
        "tick": {"age_ms": 38, "state": "fresh"},
        "hoga": {"age_ms": 349, "state": "caution"},
        "strength": {"age_ms": 120, "state": "fresh"},
    }}
    assert "hoga:state=caution" in _rest_only_enter_stale_reason(payload, ctx)
