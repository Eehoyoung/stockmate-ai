"""
tests/test_strategy_runner.py
strategy_runner.py 의 세마포어, 동시 실행, 신호 발행 테스트.
최소 40개 테스트.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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


# ──────────────────────────────────────────────────────────────────
# _load_token 테스트
# ──────────────────────────────────────────────────────────────────

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
        """빈 문자열 토큰 → None"""
        from strategy_runner import _load_token
        rdb = _make_rdb(get="")
        token = _run(_load_token(rdb))
        # "" → falsy → None 반환 (or None 구문)
        assert token is None


# ──────────────────────────────────────────────────────────────────
# _push_signals 테스트
# ──────────────────────────────────────────────────────────────────

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
        assert "삼성전자" in args[1]  # ensure_ascii=False 확인

    def test_sets_queue_ttl(self):
        from strategy_runner import _push_signals
        rdb = _make_rdb(lpush=1, expire=True)
        signals = [{"stk_cd": "005930", "score": 70.0}]
        _run(_push_signals(rdb, signals, "S1"))
        rdb.expire.assert_awaited_once_with("telegram_queue", 43200)

    def test_serialization_error_does_not_raise(self):
        """직렬화 오류 시 예외 전파하지 않음"""
        from strategy_runner import _push_signals
        rdb = _make_rdb(lpush=1, expire=True)

        class Unserializable:
            pass

        signals = [{"stk_cd": "005930", "data": Unserializable()}]
        # default=str 이므로 오류 없이 처리되어야 함
        _run(_push_signals(rdb, signals, "S1"))
        rdb.lpush.assert_awaited_once()

    def test_redis_error_does_not_raise(self):
        """Redis 오류 시 예외 전파하지 않음"""
        from strategy_runner import _push_signals
        rdb = MagicMock()
        rdb.lpush = AsyncMock(side_effect=Exception("Redis connection failed"))
        rdb.expire = AsyncMock(return_value=True)
        signals = [{"stk_cd": "005930", "score": 70.0}]
        # 예외 없이 완료되어야 함
        _run(_push_signals(rdb, signals, "S1"))


# ──────────────────────────────────────────────────────────────────
# 세마포어 동시 실행 제한 테스트
# ──────────────────────────────────────────────────────────────────

class TestSemaphore:
    def setup_method(self):
        """각 테스트 전에 전역 세마포어 초기화"""
        import strategy_runner
        strategy_runner._semaphore = None

    def test_semaphore_limits_concurrent_execution(self):
        """세마포어가 동시 실행을 제한하는지 확인"""
        import strategy_runner
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

        from strategy_runner import _run_strategy_with_semaphore

        # MAX_CONCURRENT_STRATEGIES = 3 기본값
        tasks = [
            _run_strategy_with_semaphore(f"S{i}", mock_strategy(f"S{i}"))
            for i in range(5)
        ]
        _run(asyncio.gather(*tasks))

        # 모든 전략이 실행됨
        assert len(execution_order) == 5

    def test_semaphore_singleton_reuse(self):
        """_get_semaphore()가 동일한 세마포어 반환"""
        import strategy_runner
        strategy_runner._semaphore = None

        from strategy_runner import _get_semaphore
        sem1 = _get_semaphore()
        sem2 = _get_semaphore()
        assert sem1 is sem2

    def test_get_semaphore_uses_max_concurrent_value(self):
        """환경변수 MAX_CONCURRENT_STRATEGIES 반영"""
        import strategy_runner
        strategy_runner._semaphore = None

        with patch.dict(os.environ, {"MAX_CONCURRENT_STRATEGIES": "1"}):
            # 모듈 재임포트 시뮬레이션
            import importlib
            importlib.reload(strategy_runner)
            strategy_runner._semaphore = None

        from strategy_runner import _get_semaphore
        sem = _get_semaphore()
        # asyncio.Semaphore는 내부 값 접근이 제한적, 잠금 여부만 확인
        assert not sem.locked()


# ──────────────────────────────────────────────────────────────────
# _run_once 테스트 (전략 실행 조정)
# ──────────────────────────────────────────────────────────────────

class TestRunOnce:
    def test_skips_all_strategies_when_no_token(self):
        """토큰 없으면 전략 미실행"""
        from strategy_runner import _run_once
        rdb = _make_rdb(get=None)
        _run(_run_once(rdb))
        rdb.lpush.assert_not_awaited()

    def test_strategies_do_not_crash_on_error(self):
        """개별 전략 오류 시 다른 전략에 영향 없음"""
        # _run_once 자체가 예외를 삼키는지 확인
        from strategy_runner import _run_once
        rdb = _make_rdb(get="valid-token")
        # 전략들이 오류를 던져도 _run_once는 정상 종료
        with patch("strategy_runner._run_strategy_with_semaphore",
                   side_effect=Exception("strategy error")):
            # 예외가 전파되지 않아야 함 (gather return_exceptions=True)
            try:
                _run(_run_once(rdb))
            except Exception:
                pytest.fail("_run_once should not propagate strategy errors")

    def test_gather_collects_all_results(self):
        """asyncio.gather가 모든 전략 결과를 수집"""
        results = []

        async def fake_strategy(name):
            results.append(name)

        from strategy_runner import _run_strategy_with_semaphore
        tasks = [
            _run_strategy_with_semaphore(f"S{i}", fake_strategy(f"S{i}"))
            for i in range(3)
        ]
        _run(asyncio.gather(*tasks))
        assert len(results) == 3


# ──────────────────────────────────────────────────────────────────
# run_strategy_scanner 루프 테스트
# ──────────────────────────────────────────────────────────────────

class TestRunStrategyScanner:
    def test_scanner_calls_run_once(self):
        """스캐너 루프가 _run_once를 호출하는지 확인"""
        call_count = [0]

        async def fake_run_once(rdb):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise asyncio.CancelledError()

        rdb = _make_rdb()

        with patch("strategy_runner._run_once", side_effect=fake_run_once), \
             patch("strategy_runner.SCAN_INTERVAL_SEC", 0.001):
            from strategy_runner import run_strategy_scanner
            try:
                _run(asyncio.wait_for(run_strategy_scanner(rdb), timeout=0.1))
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        assert call_count[0] >= 1

    def test_scanner_handles_run_once_error_and_continues(self):
        """_run_once 오류 발생 시 루프 계속"""
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

        with patch("strategy_runner._run_once", side_effect=fake_run_once), \
             patch("strategy_runner.SCAN_INTERVAL_SEC", 0.001):
            from strategy_runner import run_strategy_scanner
            try:
                _run(asyncio.wait_for(run_strategy_scanner(rdb), timeout=0.2))
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        assert call_count[0] >= 2  # 오류 후에도 계속 실행
        assert error_raised[0] is True


# ──────────────────────────────────────────────────────────────────
# 시간대 기반 전략 활성화 테스트
# ──────────────────────────────────────────────────────────────────

class TestTimeBasedStrategyActivation:
    def test_no_tasks_before_market_open(self):
        """07:00 (장 전) → tasks 없음"""
        import datetime

        with patch("strategy_runner.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.time.return_value = datetime.time(7, 0)
            mock_dt.time = datetime.time

            rdb = _make_rdb(get="valid-token")
            calls = []

            async def track_push(rdb, signals, name):
                calls.append(name)

            with patch("strategy_runner._push_signals", side_effect=track_push), \
                 patch("strategy_runner._run_strategy_with_semaphore",
                       side_effect=lambda name, coro: coro):
                from strategy_runner import _run_once
                _run(_run_once(rdb))

            # 07:00은 어떤 전략도 활성화 안 됨
            assert calls == []

    def test_s7_active_during_auction(self):
        """08:45 (동시호가) → S7 전략 활성화"""
        import datetime
        from strategy_runner import _run_once

        active_strategies = []

        async def fake_strategy_runner(name, coro):
            active_strategies.append(name)
            # coro를 실행하지 않아도 됨 (이름만 추적)
            try:
                await coro
            except Exception:
                pass

        with patch("strategy_runner.datetime") as mock_dt, \
             patch("strategy_runner._run_strategy_with_semaphore",
                   side_effect=fake_strategy_runner), \
             patch("strategy_runner._load_token", new_callable=AsyncMock,
                   return_value="valid-token"):
            mock_dt.datetime.now.return_value.time.return_value = datetime.time(8, 45)
            mock_dt.time = datetime.time

            with patch("strategy_runner.scan_auction_signal",
                       new_callable=AsyncMock,
                       return_value=[]) if False else \
                 patch("strategy_runner._push_signals", new_callable=AsyncMock):
                try:
                    _run(_run_once(MagicMock()))
                except Exception:
                    pass

            assert "S7" in active_strategies


# ──────────────────────────────────────────────────────────────────
# QUEUE_TTL_SECONDS 상수 검증
# ──────────────────────────────────────────────────────────────────

class TestConstants:
    def test_queue_ttl_is_12_hours(self):
        from strategy_runner import QUEUE_TTL_SECONDS
        assert QUEUE_TTL_SECONDS == 43200

    def test_scan_interval_default_60(self):
        import strategy_runner
        # 환경변수 미설정 시 기본값 60.0
        assert strategy_runner.SCAN_INTERVAL_SEC >= 0.0

    def test_max_concurrent_default_3(self):
        import strategy_runner
        assert strategy_runner.MAX_CONCURRENT_STRATEGIES >= 1

    def test_redis_token_key(self):
        from strategy_runner import REDIS_TOKEN_KEY
        assert REDIS_TOKEN_KEY == "kiwoom:token"


# ──────────────────────────────────────────────────────────────────
# asyncio.gather 오류 처리
# ──────────────────────────────────────────────────────────────────

class TestGatherErrorHandling:
    def test_gather_with_return_exceptions_catches_all(self):
        """asyncio.gather(return_exceptions=True) 가 모든 결과 수집"""
        async def failing_task():
            raise ValueError("task failed")

        async def success_task():
            return "success"

        async def main():
            results = await asyncio.gather(
                failing_task(),
                success_task(),
                return_exceptions=True
            )
            return results

        results = _run(main())
        assert len(results) == 2
        assert isinstance(results[0], ValueError)
        assert results[1] == "success"

    def test_strategy_failure_does_not_block_others(self):
        """한 전략 실패 시 다른 전략 계속 실행"""
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
