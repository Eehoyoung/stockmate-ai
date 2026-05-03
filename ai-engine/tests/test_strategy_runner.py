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
    }
    defaults.update(overrides)
    for method, return_value in defaults.items():
        setattr(rdb, method, AsyncMock(return_value=return_value))
    return rdb


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

    def test_empty_signals_no_push(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        _run(_push_signals(rdb, [], "S1_GAP_OPEN"))
        rdb.lpush.assert_not_awaited()

    def test_signal_serialized_as_json(self):
        from strategy_runner import _push_signals

        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "score": 75.0, "stk_nm": "삼성전자"}]
        _run(_push_signals(rdb, signals, "S1"))
        args = rdb.lpush.call_args[0]
        parsed = json.loads(args[1])
        assert parsed["stk_cd"] == "005930"
        assert "삼성전자" in args[1]

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
        signals = [{"stk_cd": "005930", "score": 70.0}]
        _run(_push_signals(rdb, signals, "S1"))


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


class TestRunOnce:
    def test_session_filter_flag_off_allows_existing_flow(self, monkeypatch):
        import strategy_runner

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", False)
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(side_effect=AssertionError("should not be called")))

        assert strategy_runner._session_filter_allows_run() is True

    def test_session_filter_skips_closed_session(self, monkeypatch):
        import datetime
        import strategy_runner
        from market_session import MarketSession

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_DRY_RUN", False)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(return_value=MarketSession.CLOSED))
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(return_value=False))

        assert strategy_runner._session_filter_allows_run(datetime.datetime(2026, 5, 4, 7, 0)) is False

    def test_session_filter_allows_trading_active_sessions_when_enabled(self, monkeypatch):
        import datetime
        import strategy_runner
        from market_session import MarketSession

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_DRY_RUN", False)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(return_value=MarketSession.OPENING_AUCTION))
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(return_value=True))

        assert strategy_runner._session_filter_allows_run(datetime.datetime(2026, 5, 4, 8, 55)) is True

    def test_session_filter_dry_run_allows_closed_session(self, monkeypatch):
        import datetime
        import strategy_runner
        from market_session import MarketSession

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_DRY_RUN", True)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(return_value=MarketSession.CLOSED))
        monkeypatch.setattr(strategy_runner, "is_trading_active", MagicMock(return_value=False))

        assert strategy_runner._session_filter_allows_run(datetime.datetime(2026, 5, 4, 7, 0)) is True

    def test_session_filter_fail_open_allows_on_error(self, monkeypatch):
        import datetime
        import strategy_runner

        monkeypatch.setattr(strategy_runner, "ENABLE_STRATEGY_SESSION_FILTER", True)
        monkeypatch.setattr(strategy_runner, "STRATEGY_SESSION_FAIL_OPEN", True)
        monkeypatch.setattr(strategy_runner, "current_session", MagicMock(side_effect=RuntimeError("boom")))

        assert strategy_runner._session_filter_allows_run(datetime.datetime(2026, 5, 4, 7, 0)) is True

    def test_skips_all_strategies_when_no_token(self, caplog):
        import datetime
        from strategy_runner import _run_once

        rdb = _make_rdb(get=None)
        with patch("strategy_runner._current_kst_time", return_value=datetime.time(10, 15)):
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

        entries = _active_schedule_entries(datetime.time(10, 15))
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
            ("S10", (10, 0), (14, 0), (14, 1)),
            ("S11", (10, 0), (14, 30), (14, 31)),
            ("S13", (10, 0), (14, 0), (14, 1)),
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
    def test_scan_s1_runs_even_when_candidate_pool_empty(self):
        from strategy_runner import _scan_s1

        rdb = _make_rdb(lrange=[])

        with patch("strategy_1_gap_opening.scan_gap_opening", new_callable=AsyncMock, return_value=[]) as scan_mock, patch(
            "strategy_runner._push_signals", new_callable=AsyncMock
        ):
            _run(_scan_s1(rdb, "valid-token"))

        scan_mock.assert_awaited_once()
        args = scan_mock.await_args.args
        assert args[0] == "valid-token"
        assert args[1] == []
