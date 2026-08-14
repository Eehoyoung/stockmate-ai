import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _MockResponse:
    def __init__(self, items, cont_yn="N", next_key=""):
        self._items = items
        self.headers = {"cont-yn": cont_yn, "next-key": next_key}

    def json(self):
        return {"tdy_pred_cntr_qty": self._items}

    def raise_for_status(self):
        return None


class _MockClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._post)
        self.requests = []

    async def _post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "headers": headers or {}, "json": json or {}})
        if not self._responses:
            raise AssertionError("No mock response left")
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestFetchVolumeCompare:
    def test_normalizes_stock_code_before_ka10055_request(self):
        from strategy_3_inst_foreign import fetch_volume_compare

        client = _MockClient([
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+100"}]),
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+50"}]),
        ])

        with patch("strategy_3_inst_foreign.kiwoom_client", return_value=client), \
             patch("strategy_3_inst_foreign.validate_kiwoom_response", return_value=True), \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime, \
             patch("strategy_3_inst_foreign.asyncio.sleep", new=AsyncMock()):
            mock_datetime.now.return_value.strftime.return_value = "093856"
            ratio = _run(fetch_volume_compare("token", "0008Z0_AL"))

        assert ratio == pytest.approx(2.0)
        assert client.requests[0]["json"]["stk_cd"] == "0008Z0"
        assert client.requests[1]["json"]["stk_cd"] == "0008Z0"

    def test_breaks_when_next_key_repeats(self, caplog):
        from strategy_3_inst_foreign import fetch_volume_compare

        today_client = _MockClient([
            _MockResponse(
                [{"cntr_tm": "091000", "cntr_qty": "+100"}],
                cont_yn="Y",
                next_key="NK1",
            ),
            _MockResponse(
                [{"cntr_tm": "090959", "cntr_qty": "+50"}],
                cont_yn="Y",
                next_key="NK1",
            ),
        ])
        prev_client = _MockClient([
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+100"}]),
        ])
        clients = [today_client, prev_client]

        def _client_factory():
            if not clients:
                raise AssertionError("Unexpected kiwoom_client() call")
            return clients.pop(0)

        with patch("strategy_3_inst_foreign._KA10055_REQUIRE_COMPLETE", False), \
             patch("strategy_3_inst_foreign.kiwoom_client", side_effect=_client_factory), \
             patch("strategy_3_inst_foreign.validate_kiwoom_response", return_value=True), \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime, \
             patch("strategy_3_inst_foreign.asyncio.sleep", new=AsyncMock()):
            mock_datetime.now.return_value.strftime.return_value = "093856"
            with caplog.at_level("WARNING"):
                ratio = _run(fetch_volume_compare("token", "005930_AL"))

        assert ratio == pytest.approx(1.5)
        assert any("next-key loop detected" in record.message for record in caplog.records)
        assert len(today_client.requests) == 2

    def test_uses_cache_when_flag_enabled(self, monkeypatch):
        from strategy_3_inst_foreign import fetch_volume_compare

        rdb = MagicMock()
        rdb.get = AsyncMock(return_value="2.5")
        monkeypatch.setenv("S3_KA10055_CACHE_ENABLED", "1")

        with patch("strategy_3_inst_foreign.kiwoom_client") as mock_client, \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "093856"
            ratio = _run(fetch_volume_compare("token", "005930", rdb=rdb))

        assert ratio == pytest.approx(2.5)
        mock_client.assert_not_called()

    def test_run_stats_dedupes_warning_and_counts_summary(self, caplog):
        from strategy_3_inst_foreign import Ka10055RunStats

        stats = Ka10055RunStats()
        with caplog.at_level("INFO"):
            stats.warn("page_cap", ("005930", "1"), "warn %s", "once")
            stats.warn("page_cap", ("005930", "1"), "warn %s", "twice")
            stats.log_summary()

        messages = [record.message for record in caplog.records]
        assert messages.count("warn once") == 1
        assert not any(message == "warn twice" for message in messages)
        assert any("ka10055 summary page_cap=2" in message for message in messages)

    def test_page_cap_uses_partial_volume_by_default(self):
        from strategy_3_inst_foreign import fetch_volume_compare

        today_client = _MockClient([
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+100"}], cont_yn="Y", next_key="T1"),
            _MockResponse([{"cntr_tm": "091001", "cntr_qty": "+100"}], cont_yn="Y", next_key="T2"),
            _MockResponse([{"cntr_tm": "091002", "cntr_qty": "+100"}], cont_yn="Y", next_key="T3"),
        ])
        prev_client = _MockClient([
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+100"}]),
        ])
        clients = [today_client, prev_client]

        def _client_factory():
            return clients.pop(0)

        with patch("strategy_3_inst_foreign._KA10055_REQUIRE_COMPLETE", False), \
             patch("strategy_3_inst_foreign.kiwoom_client", side_effect=_client_factory), \
             patch("strategy_3_inst_foreign.validate_kiwoom_response", return_value=True), \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime, \
             patch("strategy_3_inst_foreign.asyncio.sleep", new=AsyncMock()):
            mock_datetime.now.return_value.strftime.return_value = "093856"
            ratio = _run(fetch_volume_compare("token", "005930"))

        assert ratio == pytest.approx(3.0)

    def test_uses_shared_cross_strategy_cache_and_skips_http(self):
        """S7/S8/S9가 먼저 채워둔 공유 ka10055 캐시가 있으면 HTTP 호출 없이 재사용해야 한다."""
        from strategy_3_inst_foreign import fetch_volume_compare

        rdb = MagicMock()
        rdb.get = AsyncMock(return_value=json.dumps({
            "summary": {"same_time_volume_ratio": 2.2},
            "meta": {"source": "redis", "api_id": "ka10055", "complete": True},
        }))

        with patch("strategy_3_inst_foreign.kiwoom_client") as mock_client, \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "093856"
            ratio = _run(fetch_volume_compare("token", "005930", rdb=rdb))

        assert ratio == pytest.approx(2.2)
        mock_client.assert_not_called()

    def test_complete_fetch_populates_shared_cross_strategy_cache(self):
        """양쪽(today/prev) 모두 완전 수집된 경우에만 공유 캐시에 기록해야 한다."""
        from strategy_3_inst_foreign import fetch_volume_compare

        rdb = MagicMock()
        rdb.get = AsyncMock(return_value=None)  # 공유 캐시 미스, S3 전용 버킷 캐시 미스
        rdb.set = AsyncMock(return_value=True)

        today_client = _MockClient([
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+300"}]),
        ])
        prev_client = _MockClient([
            _MockResponse([{"cntr_tm": "091000", "cntr_qty": "+100"}]),
        ])
        clients = [today_client, prev_client]

        def _client_factory():
            return clients.pop(0)

        with patch("strategy_3_inst_foreign.kiwoom_client", side_effect=_client_factory), \
             patch("strategy_3_inst_foreign.validate_kiwoom_response", return_value=True), \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime, \
             patch("strategy_3_inst_foreign.asyncio.sleep", new=AsyncMock()):
            mock_datetime.now.return_value.strftime.return_value = "093856"
            ratio = _run(fetch_volume_compare("token", "005930", rdb=rdb))

        assert ratio == pytest.approx(3.0)
        shared_cache_writes = [
            call for call in rdb.set.await_args_list
            if call.args and call.args[0] == "kiwoom:ka10055:same_time:005930"
        ]
        assert len(shared_cache_writes) == 1
        written_payload = json.loads(shared_cache_writes[0].args[1])
        assert written_payload["summary"]["same_time_volume_ratio"] == pytest.approx(3.0)
