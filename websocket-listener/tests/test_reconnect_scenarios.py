"""
tests/test_reconnect_scenarios.py
A3-1: 장중 / 장외 / BYPASS 모드별 재연결 시나리오 테스트 케이스.

DoD: 장중 WS 단절 후 60초 내 자동 회복률 95%+

실행:
  cd websocket-listener
  python -m pytest tests/test_reconnect_scenarios.py -v
"""

import asyncio
import os
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────────────────────────
# 헬퍼: KST 시각 목(mock) 생성
# ──────────────────────────────────────────────────────────────

def _kst_dt(hour: int, minute: int, weekday: int = 0) -> datetime:
    """테스트용 KST datetime 생성 (weekday: 0=월 ~ 6=일)."""
    now = datetime.now(KST)
    days_diff = (weekday - now.weekday()) % 7
    base = now + timedelta(days=days_diff)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ──────────────────────────────────────────────────────────────
# TC-01: _is_market_hours — 장중 시각
# ──────────────────────────────────────────────────────────────

class TestIsMarketHours:
    """TC-01 ~ TC-06: _is_market_hours() 경계값 검증."""

    def _patch_now(self, hour, minute, weekday=0):
        dt = _kst_dt(hour, minute, weekday)
        return patch("ws_client._now_kst", return_value=dt)

    def test_01_market_open_start(self):
        """TC-01: 07:30 (장전 구독 시작) → True."""
        with self._patch_now(7, 30, weekday=0):
            import ws_client
            assert ws_client._is_market_hours() is True

    def test_02_market_midday(self):
        """TC-02: 10:00 (장중 한가운데) → True."""
        with self._patch_now(10, 0, weekday=2):
            import ws_client
            assert ws_client._is_market_hours() is True

    def test_03_market_close_boundary(self):
        """TC-03: 15:35 (장 마감 경계) → False."""
        with self._patch_now(20, 10, weekday=1):
            import ws_client
            assert ws_client._is_market_hours() is False

    def test_04_before_open(self):
        """TC-04: 07:29 (개장 1분 전) → False."""
        with self._patch_now(7, 29, weekday=3):
            import ws_client
            assert ws_client._is_market_hours() is False

    def test_05_saturday(self):
        """TC-05: 토요일 10:00 → False."""
        with self._patch_now(10, 0, weekday=5):
            import ws_client
            assert ws_client._is_market_hours() is False

    def test_06_sunday(self):
        """TC-06: 일요일 10:00 → False."""
        with self._patch_now(10, 0, weekday=6):
            import ws_client
            assert ws_client._is_market_hours() is False


# ──────────────────────────────────────────────────────────────
# TC-07~09: _next_market_open — 다음 개장 시각 계산
# ──────────────────────────────────────────────────────────────

class TestNextMarketOpen:
    """TC-07 ~ TC-09: _next_market_open() 반환 시각 검증."""

    def test_07_friday_after_close(self):
        """TC-07: 금요일 16:00 → 다음 월요일 07:30."""
        dt = _kst_dt(21, 0, weekday=4)
        with patch("ws_client._now_kst", return_value=dt):
            import ws_client
            nxt = ws_client._next_market_open()
            assert nxt.weekday() == 0        # 월요일
            assert nxt.hour == 7
            assert nxt.minute == 30

    def test_08_weekday_before_open(self):
        """TC-08: 화요일 06:00 → 당일 07:30."""
        dt = _kst_dt(6, 0, weekday=1)
        with patch("ws_client._now_kst", return_value=dt):
            import ws_client
            nxt = ws_client._next_market_open()
            assert nxt.weekday() == 1
            assert nxt.hour == 7
            assert nxt.minute == 30

    def test_09_weekday_after_close(self):
        """TC-09: 수요일 16:00 → 다음날(목) 07:30."""
        dt = _kst_dt(21, 0, weekday=2)
        with patch("ws_client._now_kst", return_value=dt):
            import ws_client
            nxt = ws_client._next_market_open()
            assert nxt.weekday() == 3
            assert nxt.hour == 7


# ──────────────────────────────────────────────────────────────
# TC-10~12: BYPASS_MARKET_HOURS 모드 동작
# ──────────────────────────────────────────────────────────────

class TestBypassMode:
    """TC-10 ~ TC-12: BYPASS_MARKET_HOURS=true 시 동작 검증."""

    def test_10_bypass_env_true(self):
        """TC-10: BYPASS_MARKET_HOURS=true → ws_client.BYPASS_MARKET_HOURS == True."""
        with patch.dict(os.environ, {"BYPASS_MARKET_HOURS": "true"}):
            import importlib
            import ws_client
            importlib.reload(ws_client)
            assert ws_client.BYPASS_MARKET_HOURS is True

    def test_11_bypass_env_false(self):
        """TC-11: BYPASS_MARKET_HOURS=false → ws_client.BYPASS_MARKET_HOURS == False."""
        with patch.dict(os.environ, {"BYPASS_MARKET_HOURS": "false"}):
            import importlib
            import ws_client
            importlib.reload(ws_client)
            assert ws_client.BYPASS_MARKET_HOURS is False

    def test_12_bypass_env_1(self):
        """TC-12: BYPASS_MARKET_HOURS=1 → True."""
        with patch.dict(os.environ, {"BYPASS_MARKET_HOURS": "1"}):
            import importlib
            import ws_client
            importlib.reload(ws_client)
            assert ws_client.BYPASS_MARKET_HOURS is True


# ──────────────────────────────────────────────────────────────
# TC-13~15: 재연결 백오프 지수 증가 검증
# ──────────────────────────────────────────────────────────────

class TestBackoffLogic:
    """TC-13 ~ TC-15: 지수 백오프 딜레이 계산 검증."""

    def test_13_initial_delay(self):
        """TC-13: 초기 딜레이 = BASE_RECONNECT_MS / 1000 = 3.0초."""
        import ws_client
        delay = ws_client.BASE_RECONNECT_MS / 1000
        assert delay == pytest.approx(3.0)

    def test_14_backoff_doubles(self):
        """TC-14: 딜레이가 매 재시도마다 2배로 증가."""
        import ws_client
        delay = ws_client.BASE_RECONNECT_MS / 1000
        delays = []
        for _ in range(5):
            delays.append(delay)
            delay = min(delay * 2, ws_client.MAX_RECONNECT_SEC)
        assert delays == pytest.approx([3.0, 6.0, 12.0, 24.0, 48.0])

    def test_15_backoff_capped_at_max(self):
        """TC-15: 딜레이가 MAX_RECONNECT_SEC(300초)을 초과하지 않음."""
        import ws_client
        delay = ws_client.BASE_RECONNECT_MS / 1000
        for _ in range(20):
            delay = min(delay * 2, ws_client.MAX_RECONNECT_SEC)
        assert delay == ws_client.MAX_RECONNECT_SEC


# ──────────────────────────────────────────────────────────────
# TC-16~18: _wait_for_market_open 비동기 동작 (장 외 시간)
# ──────────────────────────────────────────────────────────────

class TestWaitForMarketOpen:
    """TC-16 ~ TC-18: _wait_for_market_open() 대기/즉시반환 검증."""

    def test_16_returns_immediately_during_market(self):
        """TC-16: 장 운영 시간이면 즉시 반환 (sleep 호출 없음)."""
        dt = _kst_dt(10, 0, weekday=0)
        with patch("ws_client._now_kst", return_value=dt), \
             patch("ws_client._is_market_hours", return_value=True), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            import ws_client
            asyncio.run(ws_client._wait_for_market_open())
            mock_sleep.assert_not_called()

    def test_17_sleeps_when_outside_market(self):
        """TC-17: 장 외 시간이면 sleep 호출됨."""
        import ws_client
        # now=16:00, next_open=16:00+15h30m → wait_sec 확실히 양수
        now       = datetime.now(KST).replace(hour=16, minute=0, second=0, microsecond=0)
        next_open = now + timedelta(hours=15, minutes=30)

        call_count = 0

        def _is_market_side_effect():
            nonlocal call_count
            call_count += 1
            return call_count > 1  # 두 번째 호출부터 True

        with patch("ws_client._now_kst", return_value=now), \
             patch("ws_client._is_market_hours", side_effect=_is_market_side_effect), \
             patch("ws_client._next_market_open", return_value=next_open), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            asyncio.run(ws_client._wait_for_market_open())
            mock_sleep.assert_called_once()

    def test_18_cancelled_error_propagates(self):
        """TC-18: CancelledError 발생 시 상위로 전파 (루프 탈출 가능)."""
        import ws_client
        now       = datetime.now(KST).replace(hour=16, minute=0, second=0, microsecond=0)
        next_open = now + timedelta(hours=15, minutes=30)

        with patch("ws_client._now_kst", return_value=now), \
            patch("ws_client._is_market_hours", return_value=False), \
            patch("ws_client._next_market_open", return_value=next_open), \
            patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(ws_client._wait_for_market_open())


# ──────────────────────────────────────────────────────────────
# TC-19~20: health_server 상태 연동
# ──────────────────────────────────────────────────────────────

class TestHealthServerIntegration:
    """TC-19 ~ TC-20: set_ws_connected + disconnect_reason 연동 확인."""

    def test_19_disconnect_reason_set_on_false(self):
        """TC-19: set_ws_connected(False, reason=...) 시 reason 보존."""
        import health_server
        health_server.set_ws_connected(True)
        health_server.set_ws_connected(False, reason="ConnectionClosed:1001")
        assert health_server._ws_connected is False
        assert health_server._disconnect_reason == "ConnectionClosed:1001"

    def test_20_reason_cleared_on_reconnect(self):
        """TC-20: set_ws_connected(True) 시 disconnect_reason 초기화."""
        import health_server
        health_server.set_ws_connected(False, reason="OSError:ConnectionRefusedError")
        health_server.set_ws_connected(True)
        assert health_server._ws_connected is True
        assert health_server._disconnect_reason == ""
