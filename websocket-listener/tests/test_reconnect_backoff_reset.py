"""
tests/test_reconnect_backoff_reset.py

회귀 테스트 (2026-08-12 장중 인시던트): 키움 WS 연결은 정상 close frame 없이
ConnectionClosed 예외로 끊기는 경우가 대부분이다. run_ws_loop() 의 지수 백오프
카운터 리셋이 "정상 종료(예외 없이 async with 블록을 빠져나온 경우)" 경로에만
있으면, 연결이 아무리 오래 유지되었어도 리셋되지 않아 재연결 지연이 하루 종일
300초 상한까지 누적된 채 풀리지 않는다.

이 테스트는 실제 이벤트 루프로 run_ws_loop() 을 두 차례 반복시키면서, 매번
ConnectionClosed 로 연결이 끊기게 만들고, MIN_CONNECTED_SEC 을 0으로 낮춰
"충분히 오래 유지됨" 조건을 항상 만족시킨다. 리셋 로직이 예외 경로에서도
동작한다면 두 번째 재연결 지연도 기저값(BASE_RECONNECT_MS)이어야 한다.
수정 전 코드는 리셋 코드가 예외 경로에서 아예 도달 불가능한 위치에 있었으므로
두 번째 지연이 2배(6.0초)로 누적됐을 것이다.

실행:
  cd websocket-listener
  python -m pytest tests/test_reconnect_backoff_reset.py -v
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from websockets.exceptions import ConnectionClosed

import ws_client


class _StopLoop(Exception):
    """run_ws_loop 의 무한 루프를 원하는 지점에서 끊기 위한 테스트 전용 예외."""


class _FakeWSConnection:
    """websockets.connect(...) 가 반환하는 async context manager를 흉내낸다."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, payload):
        return None

    async def recv(self):
        return json.dumps({"return_code": "0"})


class TestReconnectBackoffResetsAfterConnectionClosed:
    def test_delay_resets_to_base_on_every_connectionclosed_episode(self, monkeypatch):
        sleep_calls: list[float] = []

        async def _fake_sleep(delay, *args, **kwargs):
            sleep_calls.append(delay)
            if len(sleep_calls) >= 2:
                raise _StopLoop()

        rdb = MagicMock()

        # "충분히 오래 유지됨" 판정 기준을 0으로 낮춰, 실제 경과 시간(테스트에서는
        # 수 밀리초)과 무관하게 리셋 조건이 항상 성립하도록 만든다. 이렇게 하면
        # 이 테스트는 정확한 시간값이 아니라 "리셋 코드가 예외 경로에서 실행되는가"
        # 라는 구조적 사실만 검증한다.
        monkeypatch.setattr(ws_client, "MIN_CONNECTED_SEC", 0)

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
        monkeypatch.setattr(ws_client.websockets, "connect", MagicMock(return_value=_FakeWSConnection()))

        monkeypatch.setattr(ws_client, "_bypass_market_hours", AsyncMock(return_value=True))
        monkeypatch.setattr(ws_client, "load_token", AsyncMock(return_value="tok"))
        monkeypatch.setattr(ws_client, "_reset_local_subscription_sets", AsyncMock())
        monkeypatch.setattr(ws_client, "_subscribe_by_phase", AsyncMock())
        monkeypatch.setattr(ws_client, "_get_ranked_candidates", AsyncMock(return_value=([], [])))
        monkeypatch.setattr(ws_client, "write_heartbeat", AsyncMock())
        monkeypatch.setattr(ws_client, "_watchlist_poller", AsyncMock())
        monkeypatch.setattr(ws_client, "_heartbeat_writer", AsyncMock())
        monkeypatch.setattr(ws_client, "_phase_watcher", AsyncMock())
        monkeypatch.setattr(ws_client, "_silence_watchdog", AsyncMock())
        monkeypatch.setattr(ws_client, "_ack_timeout_watcher", AsyncMock())
        monkeypatch.setattr(
            ws_client, "_run_message_loop",
            AsyncMock(side_effect=ConnectionClosed(None, None)),
        )

        with pytest.raises(_StopLoop):
            asyncio.run(ws_client.run_ws_loop(rdb))

        # 연결 #1(최초 시도) 후 재연결 지연 = 기저값 3.0초 (처음이므로 당연).
        # 연결 #2도 ConnectionClosed 로 끊겼지만, 리셋 로직이 예외 경로에서도
        # 동작해야 다시 3.0초 — 수정 전이었다면 6.0초(누적 백오프)가 됐을 것.
        assert sleep_calls == pytest.approx([3.0, 3.0])
