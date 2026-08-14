"""STRICT_REST_ENTER_GUARD 나이 기반 판정 테스트.

기존 가드는 출처가 REST라는 사실만으로 ENTER를 차단해, 요청 즉시 받아와
실제로는 신선한(0.1초 수준) 데이터까지 버렸다. 이제 나이로 판단한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _payload(sources):
    return {"action": "ENTER", "market_data_sources": sources}


def test_fresh_rest_only_is_allowed():
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "rest", "strength": "rest"})
    ctx = {"freshness": {
        "tick": {"age_ms": 120},
        "strength": {"age_ms": 300},
    }}
    assert _rest_only_enter_stale_reason(payload, ctx) is None


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
    """chart_* 뿐이라 실시간 나이를 검증할 수 없으면 차단을 유지한다."""
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"chart_daily": "rest"})
    reason = _rest_only_enter_stale_reason(payload, {"freshness": {}})
    assert reason == "no_verifiable_realtime_age"


def test_mixed_sources_are_not_subject_to_rest_guard():
    """WS(redis)가 하나라도 있으면 이 가드 대상이 아니다."""
    from queue_worker import _rest_only_enter_stale_reason

    payload = _payload({"tick": "redis", "strength": "rest"})
    ctx = {"freshness": {"tick": {"age_ms": 99999}}}
    assert _rest_only_enter_stale_reason(payload, ctx) is None


def test_signal_fallback_does_not_get_the_relaxed_path():
    """큐 페이로드 재사용(signal_fallback)은 'rest'가 아니므로 완화 대상이 아니다."""
    from queue_worker import _rest_only_enter_stale_reason, _is_rest_only_sources

    sources = {"tick": "signal_fallback"}
    assert _is_rest_only_sources(sources) is False
    assert _rest_only_enter_stale_reason(_payload(sources), {"freshness": {}}) is None


def test_empty_sources_not_treated_as_rest_only():
    from queue_worker import _is_rest_only_sources

    assert _is_rest_only_sources({}) is False
    assert _is_rest_only_sources(None) is False


def test_boundary_age_at_threshold_is_allowed():
    from queue_worker import _rest_only_enter_stale_reason, REST_ENTER_MAX_AGE_MS

    payload = _payload({"tick": "rest"})
    ctx = {"freshness": {"tick": {"age_ms": REST_ENTER_MAX_AGE_MS}}}
    assert _rest_only_enter_stale_reason(payload, ctx) is None

    ctx_over = {"freshness": {"tick": {"age_ms": REST_ENTER_MAX_AGE_MS + 1}}}
    assert _rest_only_enter_stale_reason(payload, ctx_over) is not None
