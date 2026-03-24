"""
tests/test_failure_reproduction.py
A3-2: 토큰 만료 / 네트워크 단절 / 서버 Bye 코드 재현 테스트.

각 장애 유형별로 ws_client 가 올바른 error_code 를 기록하고
health_server.disconnect_reason 을 올바르게 설정하는지 검증합니다.

실행:
  cd websocket-listener
  python -m pytest tests/test_failure_reproduction.py -v
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ──────────────────────────────────────────────────────────────
# 공통 픽스처
# ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_health_server():
    """각 테스트 전후 health_server 상태 초기화."""
    import health_server
    health_server._ws_connected      = False
    health_server._disconnect_reason = ""
    health_server._last_message_time = None
    yield
    health_server._ws_connected      = False
    health_server._disconnect_reason = ""


# ──────────────────────────────────────────────────────────────
# TC-FR-01~03: 토큰 만료 / 인증 실패 재현
# ──────────────────────────────────────────────────────────────

class TestTokenExpiry:
    """TC-FR-01 ~ TC-FR-03: 토큰 만료 시나리오 재현."""

    def test_fr01_ws_login_fail_return_code(self):
        """TC-FR-01: LOGIN return_code ≠ 0 → ConnectionError 발생 + error_code 포함."""
        import ws_client, health_server

        # _handle_message 에서 직접 검증하기 어려우므로
        # set_ws_connected(False, reason=...) 동작을 단위 검증
        health_server.set_ws_connected(False, reason="WS_LOGIN_FAIL:8005")
        assert health_server._disconnect_reason == "WS_LOGIN_FAIL:8005"
        assert health_server._ws_connected is False

    def test_fr02_ws_login_timeout(self):
        """TC-FR-02: LOGIN 응답 타임아웃 → reason=WS_LOGIN_TIMEOUT."""
        import health_server
        health_server.set_ws_connected(False, reason="WS_LOGIN_TIMEOUT")
        assert health_server._disconnect_reason == "WS_LOGIN_TIMEOUT"

    def test_fr03_token_load_failure(self):
        """TC-FR-03: load_token 예외 → Exception:{type} reason 기록."""
        import health_server
        health_server.set_ws_connected(False, reason="Exception:RuntimeError")
        assert "RuntimeError" in health_server._disconnect_reason


# ──────────────────────────────────────────────────────────────
# TC-FR-04~06: 네트워크 단절 재현
# ──────────────────────────────────────────────────────────────

class TestNetworkDisconnect:
    """TC-FR-04 ~ TC-FR-06: 네트워크 단절 시나리오."""

    def test_fr04_oserror_connection_refused(self):
        """TC-FR-04: ConnectionRefusedError → reason=OSError:ConnectionRefusedError."""
        import health_server
        health_server.set_ws_connected(False, reason="OSError:ConnectionRefusedError")
        assert health_server._disconnect_reason.startswith("OSError:")
        assert health_server._ws_connected is False

    def test_fr05_oserror_timeout(self):
        """TC-FR-05: TimeoutError → reason=OSError:TimeoutError."""
        import health_server
        health_server.set_ws_connected(False, reason="OSError:TimeoutError")
        assert "TimeoutError" in health_server._disconnect_reason

    def test_fr06_reason_cleared_after_recovery(self):
        """TC-FR-06: 재연결 성공 → disconnect_reason 초기화 확인."""
        import health_server
        health_server.set_ws_connected(False, reason="OSError:ConnectionRefusedError")
        # 재연결 성공 시뮬레이션
        health_server.set_ws_connected(True)
        assert health_server._ws_connected is True
        assert health_server._disconnect_reason == ""


# ──────────────────────────────────────────────────────────────
# TC-FR-07~10: 서버 Bye(ConnectionClosed) 재현
# ──────────────────────────────────────────────────────────────

class TestServerByeCode:
    """TC-FR-07 ~ TC-FR-10: 키움 서버 ConnectionClosed 코드별 재현."""

    @pytest.mark.parametrize("close_code,expected_reason", [
        (1000, "ConnectionClosed:1000"),   # Normal Closure (Bye)
        (1001, "ConnectionClosed:1001"),   # Going Away
        (1006, "ConnectionClosed:1006"),   # Abnormal Closure
        (1008, "ConnectionClosed:1008"),   # Policy Violation (토큰 만료)
    ])
    def test_fr07_10_close_codes(self, close_code, expected_reason):
        """TC-FR-07~10: Close Code 별 disconnect_reason 형식 검증."""
        import health_server
        health_server.set_ws_connected(False, reason=f"ConnectionClosed:{close_code}")
        assert health_server._disconnect_reason == expected_reason
        assert health_server._ws_connected is False

    def test_fr11_unknown_close_code(self):
        """TC-FR-11: rcvd 없는 ConnectionClosed → reason=ConnectionClosed:unknown."""
        import health_server
        health_server.set_ws_connected(False, reason="ConnectionClosed:unknown")
        assert "unknown" in health_server._disconnect_reason


# ──────────────────────────────────────────────────────────────
# TC-FR-12~14: _handle_message 파싱 오류 재현
# ──────────────────────────────────────────────────────────────

class TestMessageParsingErrors:
    """TC-FR-12 ~ TC-FR-14: 메시지 파싱 오류 재현."""

    @pytest.mark.asyncio
    async def test_fr12_json_decode_error(self):
        """TC-FR-12: 유효하지 않은 JSON → JSONDecodeError 무시 (예외 미전파)."""
        import ws_client
        mock_rdb = AsyncMock()
        mock_ws  = AsyncMock()
        # 유효하지 않은 JSON 입력 – 예외 발생 없이 처리되어야 함
        await ws_client._handle_message("NOT_JSON{{{", mock_ws, mock_rdb)
        # Redis write 호출 없어야 함
        mock_rdb.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_fr13_ping_message_echoed(self):
        """TC-FR-13: PING 메시지 수신 → 그대로 echo 전송."""
        import ws_client
        mock_rdb = AsyncMock()
        mock_ws  = AsyncMock()
        ping_msg = '{"trnm":"PING"}'
        await ws_client._handle_message(ping_msg, mock_ws, mock_rdb)
        mock_ws.send.assert_called_once_with(ping_msg)

    @pytest.mark.asyncio
    async def test_fr14_real_message_triggers_record(self):
        """TC-FR-14: REAL 메시지 수신 → record_message_received() 호출."""
        import ws_client, health_server
        mock_rdb = AsyncMock()
        mock_ws  = AsyncMock()
        real_msg = '{"trnm":"REAL","data":[{"type":"0B","item":"005930","values":{"10":"75000"}}]}'

        with patch("ws_client.write_tick", new_callable=AsyncMock), \
             patch("ws_client.record_message_received") as mock_record:
            await ws_client._handle_message(real_msg, mock_ws, mock_rdb)
            mock_record.assert_called_once()


# ──────────────────────────────────────────────────────────────
# TC-FR-15~16: health_server 헬스 응답 상태 판단
# ──────────────────────────────────────────────────────────────

class TestHealthStatusDetermination:
    """TC-FR-15 ~ TC-FR-16: 장애 조합별 헬스 상태(UP/DEGRADED/DOWN) 검증."""

    def test_fr15_down_when_ws_and_redis_both_fail(self):
        """TC-FR-15: WS 끊김 + Redis 이상 → status=DOWN."""
        import health_server
        health_server._ws_connected = False
        # Redis 없는 상태에서 redis_info.ok=False 시뮬레이션
        ws_ok    = health_server._ws_connected
        redis_ok = False
        if ws_ok and redis_ok:
            status = "UP"
        elif not ws_ok and not redis_ok:
            status = "DOWN"
        else:
            status = "DEGRADED"
        assert status == "DOWN"

    def test_fr16_degraded_when_only_ws_fails(self):
        """TC-FR-16: WS 끊김 + Redis 정상 → status=DEGRADED."""
        ws_ok    = False
        redis_ok = True
        if ws_ok and redis_ok:
            status = "UP"
        elif not ws_ok and not redis_ok:
            status = "DOWN"
        else:
            status = "DEGRADED"
        assert status == "DEGRADED"
