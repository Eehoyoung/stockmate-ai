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
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# http_utils.py가 있는지 확인
import importlib.util
HAS_HTTP_UTILS = importlib.util.find_spec("http_utils") is not None


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
def test_classify_kiwoom_return_code():
    from http_utils import classify_kiwoom_return_code, kiwoom_error_meta

    assert classify_kiwoom_return_code("0") == "ok"
    assert classify_kiwoom_return_code("1700") == "rate_limit"
    assert classify_kiwoom_return_code("8005") == "auth"
    assert classify_kiwoom_return_code("8050") == "auth"
    assert classify_kiwoom_return_code("8103") == "auth"
    assert classify_kiwoom_return_code("9999") == "business_error"
    meta = kiwoom_error_meta({"return_code": "1700", "return_msg": "too many"}, "ka10001")
    assert meta["error_type"] == "rate_limit"


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
def test_global_rate_limiter_wait_timeout_fails_closed():
    import http_utils

    limiter = http_utils._KiwoomRateLimiter(real_rate=1000.0)
    limiter._global_wait_ms = 0
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=False)
    limiter._redis_client = lambda: fake_redis

    with pytest.raises(http_utils.KiwoomReservationUnavailable, match="deadline"):
        _run(limiter._acquire_global())


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
def test_rate_limiter_paces_per_tr_independently(monkeypatch):
    """키움 공지(2026-06-12): REST는 TR당 초당 5건이며 TR끼리는 서로 경합하지 않는다.

    서로 다른 api_id(TR)는 상대방의 페이싱 대기에 영향받지 않고, 같은 api_id는
    설정된 간격만큼 페이싱되어야 한다.
    """
    import http_utils
    import time as _time

    # .env가 KIWOOM_REST_RATE_PER_TR을 명시적으로 설정해두므로, 이 테스트가
    # 의도하는 생성자 오버라이드(real_rate=1.0)가 os.getenv에 가려지지 않도록
    # 환경변수를 비운다(운영 코드는 env 우선이 맞고, 이건 테스트 격리 문제).
    monkeypatch.delenv("KIWOOM_REST_RATE_PER_TR", raising=False)
    monkeypatch.delenv("KIWOOM_REST_RATE_HEAVY_TR", raising=False)

    # 느린 TR(1req/s)을 하나 만들어 로컬 페이싱 큐를 채워둔다.
    limiter = http_utils._KiwoomRateLimiter(real_rate=1.0)
    limiter._global_enabled = False  # Redis 코디네이션은 이 테스트의 관심사가 아님
    # _metric()이 실제 Redis로 연결을 시도해 테스트 환경에서 타임아웃으로
    # 지연되지 않도록 목으로 대체한다(기존 rate limiter 테스트와 동일한 방식).
    fake_redis = MagicMock()
    fake_redis.hincrby = AsyncMock(return_value=0)
    fake_redis.expire = AsyncMock(return_value=True)
    limiter._redis_client = lambda: fake_redis

    async def scenario():
        await limiter.acquire("ka10029")  # 첫 호출은 즉시 통과, ka10029 페이싱 타이머 시작

        started = _time.monotonic()
        await limiter.acquire("ka10063")  # 무관한 TR -> ka10029 대기와 경합하지 않아야 함
        other_tr_wait = _time.monotonic() - started

        started = _time.monotonic()
        await limiter.acquire("ka10029")  # 같은 TR -> 최소 간격(1초)만큼 대기해야 함
        same_tr_wait = _time.monotonic() - started
        return other_tr_wait, same_tr_wait

    other_tr_wait, same_tr_wait = _run(scenario())
    assert other_tr_wait < 0.2
    assert same_tr_wait >= 0.9


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
def test_rate_limiter_heavy_tr_uses_longer_interval_than_light_tr(monkeypatch):
    """2026-08-05 재설계: 차트/대량조회/페이지네이션 TR(heavy)은 일반 TR(light)보다
    더 보수적인 간격을 사용해야 한다."""
    import http_utils

    # .env의 KIWOOM_REST_RATE_PER_TR/HEAVY_TR이 생성자 오버라이드를 가리지 않도록 격리.
    monkeypatch.delenv("KIWOOM_REST_RATE_PER_TR", raising=False)
    monkeypatch.delenv("KIWOOM_REST_RATE_HEAVY_TR", raising=False)

    limiter = http_utils._KiwoomRateLimiter(real_rate=5.0, real_rate_heavy=2.0)
    limiter._global_enabled = False
    fake_redis = MagicMock()
    fake_redis.hincrby = AsyncMock(return_value=0)
    fake_redis.expire = AsyncMock(return_value=True)
    limiter._redis_client = lambda: fake_redis

    assert limiter._is_heavy("ka10055") is True
    assert limiter._is_heavy("ka10029") is False
    assert limiter._local_interval("ka10055") == pytest.approx(0.5)
    assert limiter._local_interval("ka10029") == pytest.approx(0.2)


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
def test_rate_limiter_heavy_tr_ids_env_override(monkeypatch):
    """KIWOOM_HEAVY_TR_IDS 환경변수로 heavy TR 목록을 덮어쓸 수 있어야 한다."""
    import http_utils

    monkeypatch.setenv("KIWOOM_HEAVY_TR_IDS", "ka99999")
    limiter = http_utils._KiwoomRateLimiter(real_rate=5.0, real_rate_heavy=2.0)

    assert limiter._is_heavy("ka99999") is True
    # ka10055는 기본 heavy 목록에 있지만, env로 목록을 완전히 덮어썼으므로 light가 된다.
    assert limiter._is_heavy("ka10055") is False


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestKiwoomPostGenericRetryBackoff:
    """kiwoom_post()의 일반(비-429) HTTP 오류 재시도는 0.5s→1s→2s 지수 백오프를 적용해야 한다."""

    def test_generic_http_error_retries_with_increasing_backoff(self):
        import http_utils

        request = httpx.Request("POST", "https://example.com")
        error_resp = httpx.Response(500, request=request)
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()

        call_count = {"n": 0}

        async def fake_post(url, headers=None, json=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise httpx.HTTPStatusError("server error", request=request, response=error_resp)
            return ok_resp

        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=fake_post)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(http_utils, "kiwoom_client", return_value=fake_client), \
             patch("asyncio.sleep", new=fake_sleep):
            resp = _run(http_utils.kiwoom_post(
                "https://example.com", {}, {}, "ka10001", max_retries=2,
            ))

        assert resp is ok_resp
        assert sleep_calls == [0.5, 1.0]

    def test_generic_http_error_exhausts_retries_and_returns_none(self):
        import http_utils

        request = httpx.Request("POST", "https://example.com")
        error_resp = httpx.Response(500, request=request)

        async def fake_post(url, headers=None, json=None):
            raise httpx.HTTPStatusError("server error", request=request, response=error_resp)

        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=fake_post)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(http_utils, "kiwoom_client", return_value=fake_client), \
             patch("asyncio.sleep", new=fake_sleep):
            resp = _run(http_utils.kiwoom_post(
                "https://example.com", {}, {}, "ka10001", max_retries=2,
            ))

        assert resp is None
        assert sleep_calls == [0.5, 1.0]


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestFetchSameTimeVolumeRatioCached:
    """S3/S7/S8/S9가 공유하는 ka10055 캐시 래퍼 회귀 테스트 (2026-08-05 추가)."""

    def test_cache_hit_skips_rest_fetch(self):
        import http_utils

        rdb = MagicMock()
        cached_payload = json.dumps({
            "summary": {"same_time_volume_ratio": 1.9},
            "meta": {"source": "redis", "api_id": "ka10055", "complete": True},
        })
        rdb.get = AsyncMock(return_value=cached_payload)

        with patch.object(http_utils, "fetch_same_time_volume_ratio", new=AsyncMock()) as fetch_mock:
            summary, meta = _run(http_utils.fetch_same_time_volume_ratio_cached("token", "005930", rdb=rdb))

        fetch_mock.assert_not_called()
        assert summary["same_time_volume_ratio"] == 1.9
        assert meta["source"] == "redis"

    def test_cache_miss_fetches_and_writes_cache_only_when_complete(self):
        import http_utils

        rdb = MagicMock()
        rdb.get = AsyncMock(return_value=None)
        rdb.set = AsyncMock(return_value=True)

        fetch_mock = AsyncMock(return_value=(
            {"same_time_volume_ratio": 2.1},
            {"source": "rest", "api_id": "ka10055", "complete": True},
        ))
        with patch.object(http_utils, "fetch_same_time_volume_ratio", new=fetch_mock):
            summary, meta = _run(http_utils.fetch_same_time_volume_ratio_cached("token", "005930", rdb=rdb))

        fetch_mock.assert_awaited_once()
        rdb.set.assert_awaited_once()
        assert summary["same_time_volume_ratio"] == 2.1
        assert meta["complete"] is True

    def test_incomplete_fetch_is_not_cached(self):
        import http_utils

        rdb = MagicMock()
        rdb.get = AsyncMock(return_value=None)
        rdb.set = AsyncMock(return_value=True)

        fetch_mock = AsyncMock(return_value=(
            {"same_time_volume_ratio": 0.0},
            {"source": "rest", "api_id": "ka10055", "complete": False},
        ))
        with patch.object(http_utils, "fetch_same_time_volume_ratio", new=fetch_mock):
            _run(http_utils.fetch_same_time_volume_ratio_cached("token", "005930", rdb=rdb))

        rdb.set.assert_not_called()


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

def _make_httpx_response(payload: dict, headers: dict | None = None) -> MagicMock:
    """httpx.Response를 흉내내는 MagicMock 생성 (kiwoom_post 반환값용)"""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    resp.headers = headers or {"cont-yn": "N", "next-key": ""}
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


@pytest.mark.skipif(not HAS_HTTP_UTILS, reason="http_utils.py not found")
class TestKiwoomSupplyAndProfileHelpers:
    @pytest.mark.asyncio
    async def test_fetch_daily_cntr_strength_uses_ka10047(self):
        import http_utils
        from http_utils import fetch_daily_cntr_strength

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "cntr_str_daly": [
                    {"cntr_str": "130"},
                    {"cntr_str": "120"},
                    {"cntr_str": "110"},
                ],
            })
            summary, meta = await fetch_daily_cntr_strength("token", "A005930", days=3)

        assert meta["api_id"] == "ka10047"
        assert summary["latest"] == 130.0
        assert summary["avg_5"] == pytest.approx(120.0)
        args = mock_post.await_args.args
        assert args[3] == "ka10047"
        assert args[2] == {"stk_cd": "005930"}

    @pytest.mark.asyncio
    async def test_fetch_investor_flow_summary_uses_ka10061(self):
        import http_utils
        from http_utils import fetch_investor_flow_summary

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "stk_invsr_orgn_tot": [
                    {"frgnr_invsr": "10", "orgn": "20", "ind_invsr": "-30"}
                ],
            })
            summary, meta = await fetch_investor_flow_summary("token", "005930")

        assert meta["api_id"] == "ka10061"
        assert summary["smart_money"] == 30.0
        assert mock_post.await_args.args[2]["stk_cd"] == "005930"
        assert mock_post.await_args.args[2]["amt_qty_tp"] == "1"

    @pytest.mark.asyncio
    async def test_fetch_investor_flow_daily_uses_ka10059(self):
        import http_utils
        from http_utils import fetch_investor_flow_daily

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "stk_invsr_orgn": [{"dt": "20260701", "frgnr_invsr": "5"}],
            })
            records, meta = await fetch_investor_flow_daily("token", "A005930", dt="20260701")

        assert meta["api_id"] == "ka10059"
        assert records[0]["frgnr_invsr"] == "5"
        body = mock_post.await_args.args[2]
        assert body["dt"] == "20260701"
        assert body["stk_cd"] == "005930"
        assert body["trde_tp"] == "0"

    @pytest.mark.asyncio
    async def test_fetch_investor_flow_summary_cached_uses_redis_hit(self):
        import http_utils
        from http_utils import fetch_investor_flow_summary_cached

        rdb = MagicMock()
        rdb.get = AsyncMock(return_value=json.dumps({
            "summary": {"smart_money": 42},
            "meta": {"api_id": "ka10061", "error": None},
        }))
        rdb.set = AsyncMock()
        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            summary, meta = await fetch_investor_flow_summary_cached("token", "005930", rdb=rdb)

        assert summary["smart_money"] == 42
        assert meta["source"] == "redis"
        mock_post.assert_not_called()
        rdb.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_volume_profile_derives_support_and_resistance(self):
        import http_utils
        from http_utils import fetch_volume_profile

        http_utils._VOLUME_PROFILE_MARKET_CACHE.clear()

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "prps_cnctr": [
                    {"stk_cd": "005930", "cur_prc": "1000", "pric_strt": "900", "pric_end": "950", "prps_rt": "+60.00"},
                    {"stk_cd": "005930", "cur_prc": "1000", "pric_strt": "1100", "pric_end": "1150", "prps_rt": "+55.00"},
                    {"stk_cd": "000660", "cur_prc": "2000", "pric_strt": "1900", "pric_end": "1950", "prps_rt": "+99.00"},
                ],
            })
            profile, meta = await fetch_volume_profile("token", "005930")

        assert meta["api_id"] == "ka10025"
        assert meta["target_verified"] is True
        assert profile["support"]["high"] == 950.0
        assert profile["resistance"]["low"] == 1100.0

    @pytest.mark.asyncio
    async def test_fetch_volume_profile_skips_unverified_target(self):
        import http_utils
        from http_utils import fetch_volume_profile

        http_utils._VOLUME_PROFILE_MARKET_CACHE.clear()

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "prps_cnctr": [
                    {"cur_prc": "1000", "pric_strt": "900", "pric_end": "950", "prps_rt": "+60.00"},
                ],
            })
            profile, meta = await fetch_volume_profile("token", "005930")

        assert meta["target_verified"] is False
        assert "target not verified" in meta["error"]
        assert profile["target_verified"] is False

    @pytest.mark.asyncio
    async def test_fetch_volume_profile_reuses_market_response_for_multiple_stocks(self):
        import http_utils
        from http_utils import fetch_volume_profile

        http_utils._VOLUME_PROFILE_MARKET_CACHE.clear()
        payload = {
            "return_code": "0",
            "prps_cnctr": [
                {"stk_cd": "005930", "cur_prc": "1000", "pric_strt": "900", "pric_end": "950", "prps_rt": "+60.00"},
                {"stk_cd": "000660", "cur_prc": "2000", "pric_strt": "1900", "pric_end": "1950", "prps_rt": "+55.00"},
            ],
        }
        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response(payload)
            first, first_meta = await fetch_volume_profile("token", "005930", market="001")
            second, second_meta = await fetch_volume_profile("token", "000660", market="001")

        assert first["target_verified"] is True
        assert second["target_verified"] is True
        assert first_meta["source"] == "rest"
        assert second_meta["source"] == "memory"
        assert mock_post.await_count == 1

    @pytest.mark.asyncio
    async def test_fetch_program_snapshot_reads_0w_hash(self):
        from http_utils import fetch_program_snapshot, program_drop_reason

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={
            "program_net_buy_amt": "-100",
            "program_net_buy_amt_chg": "-50",
            "program_net_buy_qty": "0",
            "program_net_buy_qty_chg": "-10",
        })
        snapshot = await fetch_program_snapshot(rdb, "A005930")

        assert snapshot["program_net_buy_amt"] == -100.0
        assert "amount weakening" in program_drop_reason(snapshot)

    @pytest.mark.asyncio
    async def test_fetch_same_time_volume_ratio_parses_ka10055(self):
        import http_utils
        from http_utils import fetch_same_time_volume_ratio

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                _make_httpx_response({"return_code": "0", "tdy_pred_cntr_qty": [{"cntr_tm": "091000", "cntr_qty": "+300"}]}),
                _make_httpx_response({"return_code": "0", "tdy_pred_cntr_qty": [{"cntr_tm": "091000", "cntr_qty": "+100"}]}),
            ]
            summary, meta = await fetch_same_time_volume_ratio("token", "005930")

        assert meta["api_id"] == "ka10055"
        assert summary["same_time_volume_ratio"] == 3.0
        assert meta["complete"] is True

    @pytest.mark.asyncio
    async def test_fetch_same_time_volume_ratio_follows_continuation_pages(self):
        import http_utils
        from http_utils import fetch_same_time_volume_ratio

        responses = [
            _make_httpx_response(
                {"return_code": "0", "tdy_pred_cntr_qty": [{"cntr_tm": "091000", "cntr_qty": "+300"}]},
                {"cont-yn": "Y", "next-key": "today-2"},
            ),
            _make_httpx_response(
                {"return_code": "0", "tdy_pred_cntr_qty": [{"cntr_tm": "090500", "cntr_qty": "+200"}]},
            ),
            _make_httpx_response(
                {"return_code": "0", "tdy_pred_cntr_qty": [{"cntr_tm": "091000", "cntr_qty": "+100"}]},
                {"cont-yn": "Y", "next-key": "prev-2"},
            ),
            _make_httpx_response(
                {"return_code": "0", "tdy_pred_cntr_qty": [{"cntr_tm": "090500", "cntr_qty": "+100"}]},
            ),
        ]
        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = responses
            summary, meta = await fetch_same_time_volume_ratio("token", "005930")

        assert summary["today_qty"] == 500
        assert summary["prev_same_time_qty"] == 200
        assert summary["same_time_volume_ratio"] == 2.5
        assert meta["complete"] is True
        assert meta["today_pages"] == 2
        assert meta["prev_pages"] == 2
        assert mock_post.await_args_list[1].args[1]["next-key"] == "today-2"

    @pytest.mark.asyncio
    async def test_fetch_program_time_trend_parses_ka90008(self):
        import http_utils
        from http_utils import fetch_program_time_trend

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({
                "return_code": "0",
                "stk_tm_prm_trde_trnsn": [
                    {"prm_netprps_amt": "+1000"},
                    {"prm_netprps_amt": "-500"},
                    {"prm_netprps_amt": "+250"},
                ],
            })
            summary, meta = await fetch_program_time_trend("token", "005930")

        assert meta["api_id"] == "ka90008"
        assert summary["latest_net_buy_amt"] == 1000.0
        assert summary["positive_count"] == 2

    def test_summarize_intraday_investor_flow_derives_slope_and_positive_reversal(self):
        from http_utils import summarize_intraday_investor_flow

        summary = summarize_intraday_investor_flow([
            {"tm": "101000", "frgnr_invsr": "+80", "orgn": "+20"},
            {"tm": "100000", "frgnr_invsr": "+20", "orgn": "+10"},
            {"tm": "095000", "frgnr_invsr": "+30", "orgn": "+20"},
        ])

        assert summary["latest_combined"] == 100.0
        assert summary["combined_slope"] == 25.0
        assert summary["latest_delta"] == 70.0
        assert summary["previous_delta"] == -20.0
        assert summary["recent_reversal"] is True
        assert summary["recent_reversal_direction"] == "positive"

    @pytest.mark.asyncio
    async def test_fetch_intraday_investor_flow_is_soft_when_api_empty(self):
        import http_utils
        from http_utils import fetch_intraday_investor_flow

        with patch.object(http_utils, "kiwoom_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response({"return_code": "0", "opmr_invsr_trde_chart": []})
            summary, meta = await fetch_intraday_investor_flow("token", "005930", market="001")

        assert summary == {}
        assert meta["api_id"] == "ka10064"
        assert meta["error"] == "empty records"
        assert mock_post.await_args.args[2]["mrkt_tp"] == "001"
