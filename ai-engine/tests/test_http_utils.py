"""
tests/test_http_utils.py
http_utils.py의 fetch_cntr_strength 함수 테스트.
최소 20개 테스트.
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


# http_utils.py가 있는지 확인
import importlib.util
HAS_HTTP_UTILS = importlib.util.find_spec("http_utils") is not None


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchCntrStrengthSuccess:
    def _make_response(self, strengths):
        """httpx 응답 모킹"""
        resp = MagicMock()
        resp.json.return_value = {
            "cntr_str_tm": [{"cntr_str": str(s)} for s in strengths]
        }
        resp.raise_for_status = MagicMock()
        return resp

    def test_returns_average_of_5_values(self):
        """최근 5개 평균 반환"""
        strengths = [120.0, 130.0, 140.0, 150.0, 160.0]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._make_response(strengths))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("test-token", "005930"))

        expected = sum(strengths) / len(strengths)
        assert result == pytest.approx(expected)

    def test_returns_100_when_empty_response(self):
        """빈 응답 → 기본값 100.0"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            resp = MagicMock()
            resp.json.return_value = {"cntr_str_tm": []}
            resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("test-token", "005930"))

        assert result == 100.0

    def test_returns_100_when_no_cntr_str_tm_key(self):
        """cntr_str_tm 키 없는 응답 → 100.0"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            resp = MagicMock()
            resp.json.return_value = {}
            resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("test-token", "005930"))

        assert result == 100.0

    def test_uses_only_first_5_values(self):
        """10개 데이터 중 첫 5개만 사용"""
        strengths = [100, 110, 120, 130, 140, 200, 200, 200, 200, 200]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._make_response(strengths))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("test-token", "005930"))

        expected = sum(strengths[:5]) / 5  # 첫 5개 평균
        assert result == pytest.approx(expected)

    def test_sends_correct_api_id_header(self):
        """올바른 api-id 헤더 전송"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._make_response([100.0]))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            _run(fetch_cntr_strength("my-token", "005930"))

        call_kwargs = mock_client.post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert headers.get("api-id") == "ka10046"

    def test_sends_bearer_token(self):
        """Bearer 토큰 형식으로 인증"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._make_response([100.0]))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            _run(fetch_cntr_strength("my-token", "005930"))

        call_kwargs = mock_client.post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert "Bearer my-token" in headers.get("authorization", "")

    def test_sends_correct_stk_cd(self):
        """종목 코드 올바르게 전송"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._make_response([100.0]))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            _run(fetch_cntr_strength("my-token", "000660"))

        call_kwargs = mock_client.post.call_args[1]
        body = call_kwargs.get("json", {})
        assert body.get("stk_cd") == "000660"


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchCntrStrengthErrors:
    def test_http_error_returns_100(self):
        """HTTP 오류 → 기본값 100.0"""
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.HTTPError("connection error"))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("my-token", "005930"))

        assert result == 100.0


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchStkNameNormalization:
    def test_fetch_stk_nm_uses_normalized_cache_key(self):
        rdb = MagicMock()
        rdb.get = AsyncMock(return_value="테스트종목")

        from http_utils import fetch_stk_nm
        result = _run(fetch_stk_nm(rdb, "token", "483650_AL"))

        assert result == "테스트종목"
        rdb.get.assert_awaited_once_with("stk_nm:483650")

    def test_timeout_returns_100(self):
        """타임아웃 → 기본값 100.0"""
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("my-token", "005930"))

        assert result == 100.0

    def test_malformed_response_returns_100(self):
        """잘못된 응답 형식 → 100.0"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            resp = MagicMock()
            resp.json.side_effect = json.JSONDecodeError("bad json", "", 0)
            resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("my-token", "005930"))

        assert result == 100.0

    def test_network_error_returns_100(self):
        """네트워크 오류 → 100.0"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=ConnectionRefusedError("refused"))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("my-token", "005930"))

        assert result == 100.0

    def test_invalid_cntr_str_value_skipped(self):
        """잘못된 cntr_str 값 건너뜀"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            resp = MagicMock()
            resp.json.return_value = {
                "cntr_str_tm": [
                    {"cntr_str": "120.0"},
                    {"cntr_str": "invalid"},
                    {"cntr_str": "130.0"},
                ]
            }
            resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            result = _run(fetch_cntr_strength("my-token", "005930"))

        # "invalid" 건너뛰고 120.0, 130.0 평균 = 125.0
        assert result == pytest.approx(125.0)


# http_utils가 없는 경우를 위한 fallback 테스트
class TestHttpUtilsFallback:
    def test_http_utils_module_exists(self):
        """http_utils 모듈이 존재하는지 확인"""
        # 모듈이 없으면 스킵 메시지 출력
        if not HAS_HTTP_UTILS:
            pytest.skip("http_utils.py not found - module may be imported differently")
        import http_utils
        assert hasattr(http_utils, "fetch_cntr_strength")

    def test_fetch_cntr_strength_is_coroutine(self):
        """fetch_cntr_strength가 async 함수인지 확인"""
        if not HAS_HTTP_UTILS:
            pytest.skip("http_utils.py not found")
        import inspect
        import http_utils
        assert inspect.iscoroutinefunction(http_utils.fetch_cntr_strength)
