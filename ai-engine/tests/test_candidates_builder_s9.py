import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_build_s9_uses_s8_source_filter_but_writes_s9_pool(monkeypatch):
    import candidates_builder

    items = [
        {"stk_cd": "A005930", "flu_rt": "0.5"},
        {"stk_cd": "000660", "flu_rt": "8.0"},
        {"stk_cd": "035420", "flu_rt": "8.1"},
        {"stk_cd": "", "flu_rt": "1.0"},
    ]
    calls = {}

    async def fake_fetch(token, market, sort_tp="1"):
        calls["fetch"] = (token, market, sort_tp)
        return items

    async def fake_lpush(rdb, key, codes, ttl):
        calls["lpush"] = (key, codes, ttl)

    monkeypatch.setattr(candidates_builder, "_fetch_ka10027", fake_fetch)
    monkeypatch.setattr(candidates_builder, "_lpush_with_ttl", fake_lpush)

    await candidates_builder._build_s9("token", "001", object())

    assert calls["fetch"] == ("token", "001", "1")
    assert calls["lpush"] == ("candidates:s9:001", ["005930", "000660"], 1800)
