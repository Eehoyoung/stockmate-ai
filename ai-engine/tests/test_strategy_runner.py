"""
tests/test_strategy_runner.py
strategy_runner.py 의 세마포어, 동시 실행, 신호 발행 테스트.
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_rdb(**overrides):
    rdb = MagicMock()
    defaults = {
        "get": None,
        "lpush": 1,
        "expire": True,
        "lrange": [],
        "set": True,
    }
    defaults.update(overrides)
    for method, return_value in defaults.items():
        setattr(rdb, method, AsyncMock(return_value=return_value))
    return rdb


class TestStrategyTimeoutOverrides:
    def test_s8_s9_get_longer_timeout_than_default(self):
        from strategy_runner import _strategy_timeout_sec, _DEFAULT_STRATEGY_TIMEOUT_SEC

        assert _strategy_timeout_sec("S8") == 500
        assert _strategy_timeout_sec("S9") == 450
        assert _strategy_timeout_sec("S8") > _DEFAULT_STRATEGY_TIMEOUT_SEC
        assert _strategy_timeout_sec("S9") > _DEFAULT_STRATEGY_TIMEOUT_SEC

    def test_strategies_without_override_use_default(self):
        from strategy_runner import _strategy_timeout_sec, _DEFAULT_STRATEGY_TIMEOUT_SEC

        assert _strategy_timeout_sec("S4") == _DEFAULT_STRATEGY_TIMEOUT_SEC
        assert _strategy_timeout_sec("S7") == _DEFAULT_STRATEGY_TIMEOUT_SEC
        assert _strategy_timeout_sec("S13") == _DEFAULT_STRATEGY_TIMEOUT_SEC


class TestLoadToken:
    def test_returns_token_when_present(self):
        from strategy_runner import _load_token

        rdb = _make_rdb(get="test-token-12345")
        token = _run(_load_token(rdb))
        assert token == "test-token-12345"

    def test_returns_none_when_absent(self):
        from strategy_runner import _load_token

        rdb = _make_rdb(get=None)
        token = _run(_load_token(rdb))
        assert token is None

    def test_returns_none_for_empty_string(self):
        from strategy_runner import _load_token

        rdb = _make_rdb(get="")
        token = _run(_load_token(rdb))
        assert token is None


class TestPushSignals:
    def test_pushes_each_signal(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [
            {"stk_cd": "005930", "strategy": "S1_GAP_OPEN", "score": 75.0},
            {"stk_cd": "000660", "strategy": "S1_GAP_OPEN", "score": 72.0},
        ]
        _run(_push_signals(rdb, signals, "S1_GAP_OPEN"))
        assert rdb.lpush.call_count == 2

    def test_pushes_to_telegram_queue(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S1", "score": 70.0}]
        _run(_push_signals(rdb, signals, "S1"))
        args = rdb.lpush.call_args[0]
        assert args[0] == "telegram_queue"
        payload = json.loads(args[1])
        assert isinstance(payload["enqueued_at"], float)
        assert payload["stk_cd"] == "005930"

    def test_known_setup_adds_family_lineage_without_replacing_strategy(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S9_PULLBACK_SWING", "score": 70.0}]
        with patch.dict(os.environ, {"ENABLE_STRATEGY_FAMILY_LINEAGE": "true"}):
            _run(_push_signals(rdb, signals, "S9_PULLBACK_SWING"))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["strategy"] == "S9_PULLBACK_SWING"
        assert payload["strategy_family"] == "G04"
        assert payload["strategy_family_name"] == "TREND_PHASE"
        assert payload["primary_setup_id"] == "S9_PULLBACK_SWING"
        assert payload["matched_setup_ids"] == ["S9_PULLBACK_SWING"]
        assert payload["family_policy_version"] == "family_v1_2026_08_16"
        assert payload["setup_version"] == "s9_pullback_swing_family_v1"
        assert payload["rule_score_version"] == "family_score_v1_2026_08_16"
        assert payload["prompt_version"] == "family_prompt_v1_2026_08_16"
        assert payload["confirmed_by_family_ids"] == []

    @pytest.mark.parametrize("setup_id", [
        "S1_GAP_OPEN", "S2_VI_PULLBACK", "S3_INST_FRGN", "S4_BIG_CANDLE",
        "S5_PROG_FRGN", "S6_THEME_LAGGARD", "S7_ICHIMOKU_BREAKOUT",
        "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S10_NEW_HIGH",
        "S11_FRGN_CONT", "S12_CLOSING", "S13_BOX_BREAKOUT",
        "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN", "S16_ACCUMULATION_SHADOW",
    ])
    def test_all_16_setup_queue_payloads_keep_setup_and_complete_version_lineage(self, setup_id):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        with patch.dict(os.environ, {"ENABLE_STRATEGY_FAMILY_LINEAGE": "true"}):
            _run(_push_signals(rdb, [{"stk_cd": "005930", "strategy": setup_id}], setup_id))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["strategy"] == setup_id
        assert payload["primary_setup_id"] == setup_id
        assert payload["matched_setup_ids"] == [setup_id]
        assert payload["strategy_family"].startswith("G0")
        assert payload["setup_version"]
        assert payload["rule_score_version"]
        assert payload["prompt_version"]

    def test_family_lineage_kill_switch_defaults_off(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S9_PULLBACK_SWING", "score": 70.0}]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENABLE_STRATEGY_FAMILY_LINEAGE", None)
            _run(_push_signals(rdb, signals, "S9_PULLBACK_SWING"))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["strategy"] == "S9_PULLBACK_SWING"
        assert "strategy_family" not in payload

    def test_preserves_upstream_enqueued_at(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S1", "score": 70.0, "enqueued_at": 123.0}]
        _run(_push_signals(rdb, signals, "S1"))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["enqueued_at"] == 123.0

    def test_empty_signals_no_push(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        _run(_push_signals(rdb, [], "S1_GAP_OPEN"))
        rdb.lpush.assert_not_awaited()

    def test_discards_result_when_token_rotated_during_scan(self):
        from strategy_runner import _push_signals, _run_with_token_context

        rdb = _make_rdb(get="new-token", lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S11_FRGN_CONT", "score": 80.0}]

        published = _run(
            _run_with_token_context(
                _push_signals(rdb, signals, "S11_FRGN_CONT"),
                "old-token",
            )
        )

        assert published == 0
        rdb.lpush.assert_not_awaited()

    def test_publishes_result_when_token_generation_is_current(self):
        from strategy_runner import _push_signals, _run_with_token_context

        rdb = _make_rdb(get="current-token", lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S11_FRGN_CONT", "score": 80.0}]

        published = _run(
            _run_with_token_context(
                _push_signals(rdb, signals, "S11_FRGN_CONT"),
                "current-token",
            )
        )

        assert published == 1
        rdb.lpush.assert_awaited_once()

    def test_signal_serialized_as_json(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "score": 75.0, "stk_nm": "삼성전자"}]
        _run(_push_signals(rdb, signals, "S1"))
        args = rdb.lpush.call_args[0]
        parsed = json.loads(args[1])
        assert parsed["stk_cd"] == "005930"
        assert "삼성전자" in args[1]

    def test_runner_normalizes_emitted_score_and_preserves_raw(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S12_CLOSING", "score": 15.0}]
        _run(_push_signals(rdb, signals, "S12_CLOSING"))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["score"] == 50.0
        assert payload["runner_score"] == 50.0
        assert payload["runner_score_raw"] == 15.0
        assert payload["score_scale"] == "0_100"

    def test_runner_clamps_normalized_score_to_100(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S12_CLOSING", "score": 90.0}]
        _run(_push_signals(rdb, signals, "S12_CLOSING"))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["score"] == 100.0
        assert payload["runner_score_raw"] == 90.0

    def test_runner_preserves_s16_normalized_score(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "strategy": "S16_ACCUMULATION_SHADOW", "score": 82.0}]
        _run(_push_signals(rdb, signals, "S16_ACCUMULATION_SHADOW"))

        payload = json.loads(rdb.lpush.call_args[0][1])
        assert payload["score"] == 82.0
        assert payload["runner_score"] == 82.0
        assert payload["runner_score_raw"] == 82.0

    def test_sets_queue_ttl(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "score": 70.0}]
        _run(_push_signals(rdb, signals, "S1"))
        rdb.expire.assert_awaited_once_with("telegram_queue", 43200)

    def test_serialization_error_does_not_raise(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)

        class Unserializable:
            pass

        signals = [{"stk_cd": "005930", "data": Unserializable()}]
        _run(_push_signals(rdb, signals, "S1"))
        rdb.lpush.assert_awaited_once()

    def test_redis_error_does_not_raise(self):
        from strategy_runner import _push_signals

        rdb = MagicMock()
        rdb.lpush = AsyncMock(side_effect=Exception("Redis connection failed"))
        rdb.expire = AsyncMock(return_value=True)
        rdb.set = AsyncMock(return_value=True)
        signals = [{"stk_cd": "005930", "score": 70.0}]
        _run(_push_signals(rdb, signals, "S1"))

    def test_duplicate_within_dedup_ttl_skips_publish(self):
        """dedup 키가 이미 존재하면(SET NX 실패) 같은 종목·전략을 재발행하지 않는다."""
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True, set=None)
        signals = [{"stk_cd": "044780", "strategy": "S1_GAP_OPEN", "score": 74.0}]
        published = _run(_push_signals(rdb, signals, "S1_GAP_OPEN"))

        assert published == 0
        rdb.lpush.assert_not_awaited()

    def test_dedup_check_persistent_failure_skips_publish_this_cycle(self):
        """dedup SET NX 호출이 재시도까지 계속 실패하면 발행을 보류한다(fail-closed).

        2026-07-30 044780(S1_GAP_OPEN)이 30분 dedup TTL 내(13분 간격)에 두 번 발행된
        사고의 회귀 테스트: 예전에는 dedup 확인 예외가 나면 무조건 통과(fail-open)시켜
        중복 발행으로 이어졌다.
        """
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        rdb.set = AsyncMock(side_effect=Exception("redis timeout"))
        signals = [{"stk_cd": "044780", "strategy": "S1_GAP_OPEN", "score": 74.0}]
        published = _run(_push_signals(rdb, signals, "S1_GAP_OPEN"))

        assert published == 0
        assert rdb.set.await_count == 2
        rdb.lpush.assert_not_awaited()

    def test_dedup_check_transient_failure_recovers_on_retry(self):
        """dedup 확인이 첫 시도만 실패하고 재시도에서 성공하면 정상 발행된다."""
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        rdb.set = AsyncMock(side_effect=[Exception("transient"), True])
        signals = [{"stk_cd": "044780", "strategy": "S1_GAP_OPEN", "score": 74.0}]
        published = _run(_push_signals(rdb, signals, "S1_GAP_OPEN"))

        assert published == 1
        rdb.lpush.assert_awaited_once()


class TestSemaphore:
    def setup_method(self):
        import strategy_runner

        strategy_runner._semaphore = None

    def test_semaphore_limits_concurrent_execution(self):
        import strategy_runner
        from strategy_runner import _run_strategy_with_semaphore

        strategy_runner._semaphore = None
        execution_order = []
        running_count = [0]
        max_concurrent = [0]

        async def mock_strategy(name):
            running_count[0] += 1
            max_concurrent[0] = max(max_concurrent[0], running_count[0])
            await asyncio.sleep(0.01)
            execution_order.append(name)
            running_count[0] -= 1

        tasks = [
            _run_strategy_with_semaphore(f"S{i}", mock_strategy(f"S{i}"))
            for i in range(5)
        ]
        _run(asyncio.gather(*tasks))

        assert len(execution_order) == 5
        assert max_concurrent[0] <= strategy_runner.MAX_CONCURRENT_STRATEGIES

    def test_semaphore_singleton_reuse(self):
        import strategy_runner
        from strategy_runner import _get_semaphore

        strategy_runner._semaphore = None
        sem1 = _get_semaphore()
        sem2 = _get_semaphore()
        assert sem1 is sem2

    def test_get_semaphore_uses_max_concurrent_value(self):
        import importlib
        import strategy_runner

        strategy_runner._semaphore = None
        with patch.dict(os.environ, {"MAX_CONCURRENT_STRATEGIES": "1"}):
            importlib.reload(strategy_runner)
            strategy_runner._semaphore = None

        sem = strategy_runner._get_semaphore()
        assert not sem.locked()

    def test_schedule_includes_s16_accumulation_shadow(self):
        import strategy_runner

        tags = [entry[0] for entry in strategy_runner._SCHEDULE]
        assert "S16" in tags

    def test_slow_strategy_records_status_and_pipeline_when_enabled(self, monkeypatch):
        import strategy_runner
        from strategy_runner import _run_strategy_with_semaphore

        strategy_runner._semaphore = None
        rdb = MagicMock()
        rdb.hset = AsyncMock(return_value=True)
        rdb.expire = AsyncMock(return_value=True)
        rdb.hincrby = AsyncMock(return_value=1)

        async def success():
            return "ok"

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_LATENCY_METRICS", True)
        monkeypatch.setattr(strategy_runner, "_SLOW_STRATEGY_WARN_SEC", 0.0)

        result = _run(_run_strategy_with_semaphore("S3", success(), rdb=rdb))

        assert result == "ok"
        rdb.hset.assert_awaited()
        assert rdb.hset.await_args.args[0] == "status:strategy_latency:S3"
        assert any(call.args[1] == "slow" for call in rdb.hincrby.await_args_list)

    def test_strategy_run_records_exactly_one_terminal_state(self):
        import strategy_runner

        strategy_runner._semaphore = None
        rdb = MagicMock()
        rdb.hset = AsyncMock(return_value=True)
        rdb.expire = AsyncMock(return_value=True)
        rdb.hincrby = AsyncMock(return_value=1)

        _run(strategy_runner._run_strategy_with_semaphore("S8", asyncio.sleep(0), rdb=rdb))

        run_calls = [c for c in rdb.hset.await_args_list if c.args[0] == "status:strategy_run:S8"]
        assert len(run_calls) == 1
        assert run_calls[0].kwargs["mapping"]["state"] == "SUCCESS_NO_MATCH"
        assert run_calls[0].kwargs["mapping"]["scan_run_id"]


class TestRunOnce:
    def test_session_filter_flag_off_allows_existing_flow(self, monkeypatch):
        import strategy_runner

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", False)
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(side_effect=AssertionError("should not be called")))

        assert _run(strategy_runner._session_filter_allows_run(None)) is True

    def test_session_filter_skips_closed_session(self, monkeypatch):
        import datetime
        import strategy_runner
        from market_session import MarketSession

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_DRY_RUN", False)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(return_value=MarketSession.CLOSED))
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(return_value=False))

        assert _run(strategy_runner._session_filter_allows_run(None, datetime.datetime(2026, 5, 4, 7, 0))) is False

    def test_session_filter_allows_trading_active_sessions_when_enabled(self, monkeypatch):
        import datetime
        import strategy_runner
        from market_session import MarketSession

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_DRY_RUN", False)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(return_value=MarketSession.OPENING_AUCTION))
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(return_value=True))

        assert _run(strategy_runner._session_filter_allows_run(None, datetime.datetime(2026, 5, 4, 8, 55))) is True

    def test_session_filter_dry_run_allows_closed_session(self, monkeypatch):
        import datetime
        import strategy_runner
        from market_session import MarketSession

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_DRY_RUN", True)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(return_value=MarketSession.CLOSED))
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(return_value=False))

        assert _run(strategy_runner._session_filter_allows_run(None, datetime.datetime(2026, 5, 4, 7, 0))) is True

    def test_session_filter_fail_open_allows_on_error(self, monkeypatch):
        import datetime
        import strategy_runner

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_FAIL_OPEN", True)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(side_effect=RuntimeError("boom")))

        assert _run(strategy_runner._session_filter_allows_run(None, datetime.datetime(2026, 5, 4, 7, 0))) is True

    def test_session_filter_fail_closed_blocks_on_error(self, monkeypatch):
        import datetime
        import strategy_runner

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_FAIL_OPEN", False)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(side_effect=RuntimeError("boom")))

        assert _run(strategy_runner._session_filter_allows_run(None, datetime.datetime(2026, 5, 4, 7, 0))) is False

    def test_skips_all_strategies_when_no_token(self, caplog):
        import datetime
        from strategy_runner import _run_once

        rdb = _make_rdb(get=None)

        async def _allow(*_args, **_kwargs):
            return True

        with patch("strategy_runner._current_kst_time", return_value=datetime.time(10, 15)), \
             patch("strategy_runner._session_filter_allows_run", side_effect=_allow):
            with caplog.at_level("WARNING"):
                _run(_run_once(rdb))

        rdb.lpush.assert_not_awaited()
        assert any("token" in record.message.lower() for record in caplog.records)

    def test_strategies_do_not_crash_on_error(self):
        from strategy_runner import _run_once

        rdb = _make_rdb(get="valid-token")
        with patch("strategy_runner._run_strategy_with_semaphore", side_effect=Exception("strategy error")):
            try:
                _run(_run_once(rdb))
            except Exception:
                pytest.fail("_run_once should not propagate strategy errors")

    def test_gather_collects_all_results(self):
        from strategy_runner import _run_strategy_with_semaphore

        results = []

        async def fake_strategy(name):
            results.append(name)

        tasks = [
            _run_strategy_with_semaphore(f"S{i}", fake_strategy(f"S{i}"))
            for i in range(3)
        ]
        _run(asyncio.gather(*tasks))
        assert len(results) == 3


class TestRunStrategyScanner:
    def test_scanner_calls_run_once(self):
        call_count = [0]

        async def fake_run_once(rdb):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise asyncio.CancelledError()

        rdb = _make_rdb()

        with patch("strategy_runner._run_once", side_effect=fake_run_once), patch("strategy_runner.SCAN_INTERVAL_SEC", 0.001):
            from strategy_runner import run_strategy_scanner

            try:
                _run(asyncio.wait_for(run_strategy_scanner(rdb), timeout=0.1))
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        assert call_count[0] >= 1

    def test_scanner_handles_run_once_error_and_continues(self):
        call_count = [0]
        error_raised = [False]

        async def fake_run_once(rdb):
            call_count[0] += 1
            if call_count[0] == 1:
                error_raised[0] = True
                raise Exception("scan error")
            if call_count[0] >= 2:
                raise asyncio.CancelledError()

        rdb = _make_rdb()

        with patch("strategy_runner._run_once", side_effect=fake_run_once), patch("strategy_runner.SCAN_INTERVAL_SEC", 0.001):
            from strategy_runner import run_strategy_scanner

            try:
                _run(asyncio.wait_for(run_strategy_scanner(rdb), timeout=0.2))
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        assert call_count[0] >= 2
        assert error_raised[0] is True


class TestTimeBasedStrategyActivation:
    @staticmethod
    def _active_tags_at(hour, minute):
        import datetime
        from strategy_runner import _active_schedule_entries

        return {tag for tag, _, _, _ in _active_schedule_entries(datetime.time(hour, minute))}

    def test_no_tasks_before_market_open(self):
        import datetime
        from strategy_runner import _run_once

        rdb = _make_rdb(get="valid-token")
        calls = []

        async def track_push(rdb, signals, name):
            calls.append(name)

        with patch("strategy_runner._current_kst_time", return_value=datetime.time(7, 0)), patch(
            "strategy_runner._push_signals", side_effect=track_push
        ), patch("strategy_runner._run_strategy_with_semaphore", side_effect=lambda name, coro, rdb=None: coro):
            _run(_run_once(rdb))

        assert calls == []

    def test_s7_active_during_intraday_window(self):
        import datetime
        from strategy_runner import _active_schedule_entries

        entries = _active_schedule_entries(datetime.time(11, 0))
        tags = [tag for tag, _, _, _ in entries]
        assert "S7" in tags

    def test_s2_not_scheduled_in_strategy_runner(self):
        assert "S2" not in self._active_tags_at(9, 0)
        assert "S2" not in self._active_tags_at(10, 0)
        assert "S2" not in self._active_tags_at(14, 50)

    @pytest.mark.parametrize(
        ("strategy", "start", "end", "after_end"),
        [
            ("S4", (10, 0), (14, 30), (14, 31)),
            ("S10", (10, 30), (14, 30), (14, 31)),
            ("S11", (10, 45), (14, 0), (14, 1)),
            ("S13", (11, 15), (14, 30), (14, 31)),
        ],
    )
    def test_final_schedule_boundaries(self, strategy, start, end, after_end):
        assert strategy not in self._active_tags_at(9, 59)
        assert strategy in self._active_tags_at(*start)
        assert strategy in self._active_tags_at(*end)
        assert strategy not in self._active_tags_at(*after_end)


class TestConstants:
    def test_queue_ttl_is_12_hours(self):
        from strategy_runner import QUEUE_TTL_SECONDS

        assert QUEUE_TTL_SECONDS == 43200

    def test_scan_interval_default_is_non_negative(self):
        import strategy_runner

        assert strategy_runner.SCAN_INTERVAL_SEC >= 0.0

    def test_max_concurrent_default_is_positive(self):
        import strategy_runner

        assert strategy_runner.MAX_CONCURRENT_STRATEGIES >= 1

    def test_redis_token_key(self):
        from strategy_runner import REDIS_TOKEN_KEY

        assert REDIS_TOKEN_KEY == "kiwoom:token"


class TestStrategyExecutionOwnership:
    @pytest.mark.parametrize(
        ("configured_owner", "expected"),
        [("PYTHON", True), ("JAVA", False), ("INVALID", False), ("", False)],
    )
    def test_python_owner_check_fails_closed(self, configured_owner, expected):
        import strategy_runner

        with patch.object(strategy_runner, "STRATEGY_EXECUTION_OWNER", configured_owner):
            assert strategy_runner._python_owns_strategy_execution() is expected

    def test_java_owner_skips_before_token_or_strategy_work(self):
        import strategy_runner

        rdb = _make_rdb()
        with patch.object(strategy_runner, "STRATEGY_EXECUTION_OWNER", "JAVA"), \
             patch("strategy_runner._load_token", new_callable=AsyncMock) as token_mock, \
             patch("strategy_runner._active_schedule_entries") as schedule_mock:
            _run(strategy_runner._run_once(rdb))

        token_mock.assert_not_awaited()
        schedule_mock.assert_not_called()


class TestGatherErrorHandling:
    def test_gather_with_return_exceptions_catches_all(self):
        async def failing_task():
            raise ValueError("task failed")

        async def success_task():
            return "success"

        async def main():
            return await asyncio.gather(failing_task(), success_task(), return_exceptions=True)

        results = _run(main())
        assert len(results) == 2
        assert isinstance(results[0], ValueError)
        assert results[1] == "success"

    def test_strategy_failure_does_not_block_others(self):
        from strategy_runner import _run_strategy_with_semaphore

        completed = []

        async def failing_coro():
            raise RuntimeError("전략 실패")

        async def success_coro(name):
            completed.append(name)

        async def main():
            tasks = [
                _run_strategy_with_semaphore("S1", failing_coro()),
                _run_strategy_with_semaphore("S2", success_coro("S2")),
                _run_strategy_with_semaphore("S3", success_coro("S3")),
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        _run(main())
        assert "S2" in completed
        assert "S3" in completed


class TestS1Fallback:
    def test_scan_s1_skips_when_candidate_pool_empty(self):
        from strategy_runner import _scan_s1

        rdb = _make_rdb(lrange=[])

        # 900 (09:00) → S1_SCAN_START_HHMM(850)과 S1_SCAN_END_HHMM(903) 사이 – 시간 윈도우 통과
        with patch("strategy_1_gap_opening.scan_gap_opening", new_callable=AsyncMock, return_value=[]) as scan_mock, \
             patch("strategy_runner._push_signals", new_callable=AsyncMock) as push_mock, \
             patch("strategy_runner._incr_pipeline_daily", new_callable=AsyncMock) as metric_mock, \
             patch("strategy_runner._kst_hhmm", return_value=900):
            _run(_scan_s1(rdb, "valid-token"))

        scan_mock.assert_not_awaited()
        push_mock.assert_not_awaited()
        metric_mock.assert_awaited_once_with(rdb, "S1_GAP_OPEN", "skip_empty_pool")


class TestS2NonLivePublishing:
    def test_scan_s2_rejects_non_live_signal(self):
        from strategy_runner import _scan_s2

        item = {"stk_cd": "005930", "watch_until": 9999999999999}
        rdb = _make_rdb()
        rdb.rpop = AsyncMock(side_effect=[json.dumps(item), None])

        with patch(
            "strategy_2_vi_pullback.check_vi_pullback",
            new_callable=AsyncMock,
            return_value={"stk_cd": "005930", "strategy": "S2_VI_PULLBACK", "signal_mode": "SHADOW"},
        ), patch("strategy_runner._push_signals", new_callable=AsyncMock) as push_mock:
            _run(_scan_s2(rdb, "valid-token"))

        push_mock.assert_awaited_once()
        published = push_mock.await_args.args[1]
        assert published == []


class TestManualScan:
    """대시보드 '전략 수동 실행' 패널이 호출하는 run_manual_scan() — Java에 대응 엔드포인트가
    없는 S8/S9/S11/S13~S16 전용 진입점."""

    def test_unsupported_code_returns_error_without_touching_redis(self):
        from strategy_runner import run_manual_scan

        rdb = _make_rdb()
        result = _run(run_manual_scan(rdb, "s1"))

        assert "error" in result
        rdb.get.assert_not_awaited()

    def test_missing_token_short_circuits_with_zero_published(self):
        from strategy_runner import run_manual_scan

        rdb = _make_rdb(get=None)
        result = _run(run_manual_scan(rdb, "s8"))

        assert result["strategy"] == "S8_GOLDEN_CROSS"
        assert result["published"] == 0
        assert "error" in result

    def test_dispatches_to_matching_scan_function_and_returns_count(self):
        import strategy_runner
        from strategy_runner import run_manual_scan

        rdb = _make_rdb(get="valid-token")
        mock_fn = AsyncMock(return_value=3)
        with patch.dict(
            strategy_runner.MANUAL_RUN_STRATEGIES,
            {"s16": ("S16_ACCUMULATION_SHADOW", mock_fn)},
        ):
            result = _run(run_manual_scan(rdb, "S16"))

        mock_fn.assert_awaited_once_with(rdb, "valid-token")
        assert result == {"strategy": "S16_ACCUMULATION_SHADOW", "published": 3}
