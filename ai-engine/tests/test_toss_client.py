import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import toss_client


def _run(coro):
    return asyncio.run(coro)


class _FakeRdb:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value


class TestTossEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("TOSS_ENABLED", raising=False)
        assert toss_client.toss_enabled() is False

    def test_enabled_when_true(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "true")
        assert toss_client.toss_enabled() is True

    def test_enabled_accepts_common_truthy_values(self, monkeypatch):
        for val in ("1", "yes", "on", "True"):
            monkeypatch.setenv("TOSS_ENABLED", val)
            assert toss_client.toss_enabled() is True


class TestDisabledShortCircuits:
    """토스 미설정 상태에서는 네트워크 호출 없이 즉시 빈 값/None을 반환해야 한다."""

    def test_fetch_market_ranking_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "false")
        result = _run(toss_client.fetch_market_ranking(_FakeRdb()))
        assert result == []

    def test_fetch_short_selling_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "false")
        result = _run(toss_client.fetch_short_selling(_FakeRdb(), "005930"))
        assert result is None

    def test_fetch_stock_risk_context_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "false")
        result = _run(toss_client.fetch_stock_risk_context(_FakeRdb(), "005930"))
        assert result == {}

    def test_fetch_short_selling_returns_none_without_token(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "true")
        # rdb has no "toss:token" key -> _get_toss_token returns None
        result = _run(toss_client.fetch_short_selling(_FakeRdb(), "005930"))
        assert result is None

    def test_fetch_short_selling_invalid_stock_code_returns_none(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "true")
        result = _run(toss_client.fetch_short_selling(_FakeRdb({"toss:token": "tok"}), ""))
        assert result is None

    def test_fetch_stock_warnings_returns_empty_list_when_disabled(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "false")
        result = _run(toss_client.fetch_stock_warnings(_FakeRdb(), "005930"))
        assert result == []

    def test_fetch_stock_warnings_returns_empty_list_without_token(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "true")
        result = _run(toss_client.fetch_stock_warnings(_FakeRdb(), "005930"))
        assert result == []


class TestFetchStockWarnings:
    def test_returns_cached_value_without_network_call(self, monkeypatch):
        monkeypatch.setenv("TOSS_ENABLED", "true")
        import json as _json
        cached = [{"warningType": "OVERHEATED", "exchange": "KRX", "startDate": "2026-08-01", "endDate": None}]
        rdb = _FakeRdb({"toss:token": "tok", "toss:warnings:005930": _json.dumps(cached)})
        result = _run(toss_client.fetch_stock_warnings(rdb, "005930"))
        assert result == cached

    def test_warning_type_classification_sets_are_disjoint(self):
        assert not (toss_client.WARNING_SEVERE_TYPES & toss_client.WARNING_CAUTION_TYPES)
        assert "INVESTMENT_WARNING" in toss_client.WARNING_SEVERE_TYPES
        assert "VI_STATIC" in toss_client.WARNING_CAUTION_TYPES


class TestTokenRead:
    def test_reads_shared_token_from_redis(self):
        rdb = _FakeRdb({"toss:token": "abc123"})
        token = _run(toss_client._get_toss_token(rdb))
        assert token == "abc123"

    def test_returns_none_when_rdb_missing(self):
        token = _run(toss_client._get_toss_token(None))
        assert token is None

    def test_returns_none_when_key_absent(self):
        rdb = _FakeRdb({})
        token = _run(toss_client._get_toss_token(rdb))
        assert token is None
