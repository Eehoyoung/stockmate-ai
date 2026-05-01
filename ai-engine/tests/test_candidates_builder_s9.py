import os
import sys
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_build_s3_writes_status_meta_and_pipeline_when_enabled(monkeypatch):
    import candidates_builder

    async def fake_fetch(token, market, orgn_tp):
        if orgn_tp == "9000":
            return {"005930", "000660"}
        return {"005930", "035420"}

    async def fake_lpush(rdb, key, codes, ttl):
        rdb.saved = (key, codes, ttl)

    rdb = MagicMock()
    rdb.hset = AsyncMock(return_value=True)
    rdb.expire = AsyncMock(return_value=True)
    rdb.hincrby = AsyncMock(return_value=1)

    monkeypatch.setattr(candidates_builder, "ENABLE_CANDIDATES_META", True)
    monkeypatch.setattr(candidates_builder, "ENABLE_S3S5_LATENCY_STATUS", True)
    monkeypatch.setattr(candidates_builder, "_fetch_ka10065_set", fake_fetch)
    monkeypatch.setattr(candidates_builder, "_lpush_with_ttl", fake_lpush)

    await candidates_builder._build_s3("token", "001", rdb)

    assert rdb.saved == ("candidates:s3:001", ["005930"], 1200)
    hset_keys = [call.args[0] for call in rdb.hset.await_args_list]
    assert "candidates_meta:s3:001" in hset_keys
    assert "status:candidates_builder:S3:001" in hset_keys
    assert any(call.args[1] == "candidate_build_ok" for call in rdb.hincrby.await_args_list)
