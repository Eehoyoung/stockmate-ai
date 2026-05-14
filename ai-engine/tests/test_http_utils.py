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

    def test_ka10046_body_uses_only_stock_code(self):
        """Kiwoom ka10046 요청 바디는 stk_cd만 전송"""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._make_response([100.0]))
            mock_client_cls.return_value = mock_client

            from http_utils import fetch_cntr_strength
            _run(fetch_cntr_strength("my-token", "005930"))

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs.get("json") == {"stk_cd": "005930"}

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


# ---------------------------------------------------------------------------
# fetch_hoga_rest 테스트
# ---------------------------------------------------------------------------

def _make_httpx_response(payload: dict) -> MagicMock:
    """httpx.Response를 흉내내는 MagicMock 생성 (kiwoom_post 반환값용)"""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchHogaRest:
    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_uses_kiwoom_post_not_client(self):
        """fetch_hoga_rest는 kiwoom_client 직접 호출이 아닌 kiwoom_post를 사용해야 함"""
        import http_utils
        from http_utils import fetch_hoga_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "output1": [{"total_buy_bid_req": "200", "total_sel_bid_req": "100"}],
            })
            result, meta = await fetch_hoga_rest("token", "005930")

        assert result == pytest.approx(2.0)
        assert meta["source"] == "rest"
        assert meta["api_id"] == "ka10004"
        assert meta["error"] is None
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_no_rdb_param(self):
        """fetch_hoga_rest는 rdb 파라미터가 없어야 함 (Redis 우회 확인)"""
        import inspect
        from http_utils import fetch_hoga_rest

        sig = inspect.signature(fetch_hoga_rest)
        assert "rdb" not in sig.parameters

    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_returns_none_on_failure(self):
        """REST 실패 시 None + error meta 반환"""
        import http_utils
        from http_utils import fetch_hoga_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response(
                {"return_code": "9", "return_msg": "error"}
            )
            result, meta = await fetch_hoga_rest("token", "005930")

        assert result is None
        assert meta["error"] is not None

    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_none_when_kiwoom_post_returns_none(self):
        """kiwoom_post가 None 반환하면 None + error meta"""
        import http_utils
        from http_utils import fetch_hoga_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = None
            result, meta = await fetch_hoga_rest("token", "005930")

        assert result is None
        assert meta["error"] is not None

    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_none_when_ask_is_zero(self):
        """매도 잔량 0 → None 반환"""
        import http_utils
        from http_utils import fetch_hoga_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "output1": [{"total_buy_bid_req": "100", "total_sel_bid_req": "0"}],
            })
            result, meta = await fetch_hoga_rest("token", "005930")

        assert result is None
        assert meta["error"] is not None

    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_top_level_fields(self):
        """output1 없이 최상위 tot_buy_req / tot_sel_req 필드도 파싱"""
        import http_utils
        from http_utils import fetch_hoga_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "tot_buy_req": "300",
                "tot_sel_req": "100",
            })
            result, meta = await fetch_hoga_rest("token", "005930")

        assert result == pytest.approx(3.0)
        assert meta["error"] is None

    @pytest.mark.asyncio
    async def test_fetch_hoga_rest_meta_latency_present(self):
        """meta에 latency_ms 필드가 있어야 함"""
        import http_utils
        from http_utils import fetch_hoga_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "output1": [{"total_buy_bid_req": "150", "total_sel_bid_req": "100"}],
            })
            _, meta = await fetch_hoga_rest("token", "005930")

        assert "latency_ms" in meta
        assert isinstance(meta["latency_ms"], int)


# ---------------------------------------------------------------------------
# fetch_cntr_strength_rest 테스트
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchCntrStrengthRest:
    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_uses_kiwoom_post(self):
        """fetch_cntr_strength_rest는 kiwoom_post를 사용해야 함"""
        import http_utils
        from http_utils import fetch_cntr_strength_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "output1": [
                    {"cntr_str": "120.5"},
                    {"cntr_str": "115.0"},
                    {"cntr_str": "110.0"},
                ],
            })
            result, meta = await fetch_cntr_strength_rest("token", "005930")

        assert result is not None
        assert result == pytest.approx((120.5 + 115.0 + 110.0) / 3, rel=0.01)
        assert meta["source"] == "rest"
        assert meta["api_id"] == "ka10046"
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_no_rdb_param(self):
        """fetch_cntr_strength_rest는 rdb 파라미터 없어야 함"""
        import inspect
        from http_utils import fetch_cntr_strength_rest

        sig = inspect.signature(fetch_cntr_strength_rest)
        assert "rdb" not in sig.parameters

    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_returns_none_on_api_error(self):
        """API 오류 → None + error meta"""
        import http_utils
        from http_utils import fetch_cntr_strength_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response(
                {"return_code": "-1", "return_msg": "인증 오류"}
            )
            result, meta = await fetch_cntr_strength_rest("token", "005930")

        assert result is None
        assert meta["error"] is not None

    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_returns_none_when_kiwoom_post_none(self):
        """kiwoom_post None 반환 → None + error"""
        import http_utils
        from http_utils import fetch_cntr_strength_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = None
            result, meta = await fetch_cntr_strength_rest("token", "005930")

        assert result is None
        assert meta["error"] is not None

    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_count_param(self):
        """count 파라미터로 최근 N개만 평균 계산"""
        import http_utils
        from http_utils import fetch_cntr_strength_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "output1": [
                    {"cntr_str": "100.0"},
                    {"cntr_str": "200.0"},
                    {"cntr_str": "300.0"},
                    {"cntr_str": "999.0"},  # count=3이면 포함되지 않아야 함
                ],
            })
            result, meta = await fetch_cntr_strength_rest("token", "005930", count=3)

        assert result == pytest.approx((100.0 + 200.0 + 300.0) / 3, rel=0.01)

    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_cntr_str_tm_field(self):
        """output1 없이 cntr_str_tm 필드로도 파싱 가능"""
        import http_utils
        from http_utils import fetch_cntr_strength_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "cntr_str_tm": [
                    {"cntr_str": "110.0"},
                    {"cntr_str": "120.0"},
                ],
            })
            result, meta = await fetch_cntr_strength_rest("token", "005930")

        assert result == pytest.approx(115.0, rel=0.01)
        assert meta["error"] is None

    @pytest.mark.asyncio
    async def test_fetch_cntr_strength_rest_meta_fields_complete(self):
        """meta에 source, api_id, retry_count, latency_ms, error 모두 포함"""
        import http_utils
        from http_utils import fetch_cntr_strength_rest

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "output1": [{"cntr_str": "105.0"}],
            })
            _, meta = await fetch_cntr_strength_rest("token", "005930")

        for field in ("source", "api_id", "retry_count", "latency_ms", "error"):
            assert field in meta, f"meta에 {field} 필드 없음"
        assert meta["source"] == "rest"
        assert meta["api_id"] == "ka10046"


# ---------------------------------------------------------------------------
# fetch_tick_snapshot 테스트
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchTickSnapshot:
    @pytest.mark.asyncio
    async def test_fetch_tick_snapshot_returns_cur_prc(self):
        """정상 응답 시 cur_prc, flu_rt를 반환"""
        from http_utils import fetch_tick_snapshot
        import http_utils

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "return_code": "0",
                "cur_prc": "50000",
                "flu_rt": "2.5",
                "stk_nm": "삼성전자",
            }
            mock_post.return_value = mock_resp
            tick, meta = await fetch_tick_snapshot("token", "005930")

        assert tick.get("cur_prc") == "50000"
        assert tick.get("flu_rt") == "2.5"
        assert meta["api_id"] == "ka10001"
        assert meta["error"] is None

    @pytest.mark.asyncio
    async def test_fetch_tick_snapshot_stk_info_fallback(self):
        """stk_info 서브배열에서 cur_prc 추출"""
        from http_utils import fetch_tick_snapshot
        import http_utils

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "return_code": "0",
                "stk_info": [{"cur_prc": "45000", "flu_rt": "-1.2"}],
            }
            mock_post.return_value = mock_resp
            tick, meta = await fetch_tick_snapshot("token", "005930")

        assert tick.get("cur_prc") == "45000"
        assert tick.get("flu_rt") == "-1.2"
        assert meta["error"] is None

    @pytest.mark.asyncio
    async def test_fetch_tick_snapshot_failure_returns_empty_dict(self):
        """REST 실패 시 빈 dict 반환"""
        from http_utils import fetch_tick_snapshot
        import http_utils

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = None  # kiwoom_post가 None 반환
            tick, meta = await fetch_tick_snapshot("token", "005930")

        assert tick == {}
        assert meta["error"] is not None

    @pytest.mark.asyncio
    async def test_fetch_tick_snapshot_no_rdb_param(self):
        """rdb 파라미터 없어야 함"""
        import inspect
        from http_utils import fetch_tick_snapshot
        sig = inspect.signature(fetch_tick_snapshot)
        assert "rdb" not in sig.parameters

    @pytest.mark.asyncio
    async def test_fetch_tick_snapshot_uses_kiwoom_post(self):
        """kiwoom_client 직접 사용 금지, kiwoom_post 경유"""
        from http_utils import fetch_tick_snapshot
        import http_utils

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"return_code": "0", "cur_prc": "50000", "flu_rt": "1.0"}
            mock_post.return_value = mock_resp
            await fetch_tick_snapshot("token", "005930")

        mock_post.assert_called_once()
