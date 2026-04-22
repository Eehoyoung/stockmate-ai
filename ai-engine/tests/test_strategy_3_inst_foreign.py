import asyncio
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

        with patch("strategy_3_inst_foreign.kiwoom_client", side_effect=_client_factory), \
             patch("strategy_3_inst_foreign.validate_kiwoom_response", return_value=True), \
             patch("strategy_3_inst_foreign.datetime") as mock_datetime, \
             patch("strategy_3_inst_foreign.asyncio.sleep", new=AsyncMock()):
            mock_datetime.now.return_value.strftime.return_value = "093856"
            with caplog.at_level("WARNING"):
                ratio = _run(fetch_volume_compare("token", "005930_AL"))

        assert ratio == pytest.approx(1.5)
        assert any("next-key loop detected" in record.message for record in caplog.records)
        assert len(today_client.requests) == 2
