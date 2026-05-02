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


@pytest.mark.asyncio
async def test_build_intraday_s12_only_suppresses_other_candidate_refreshes(monkeypatch):
    import candidates_builder

    calls = []

    async def fake_builder(token, market, rdb):
        calls.append(market)

    async def fail_builder(*args, **kwargs):
        raise AssertionError("non-S12 builder should not run")

    async def fake_refresh(rdb):
        calls.append("refresh")

    async def fake_sleep(_seconds):
        return None

    rdb = MagicMock()
    rdb.exists = AsyncMock(return_value=False)

    monkeypatch.setattr(candidates_builder, "MARKETS", ["001", "101"])
    monkeypatch.setattr(candidates_builder, "_build_s12", fake_builder)
    for name in [
        "_build_s1",
        "_build_s2",
        "_build_s3",
        "_build_s4",
        "_build_s5",
        "_build_s6",
        "_build_s7",
        "_build_s8",
        "_build_s9",
        "_build_s10",
        "_build_s11",
        "_build_s13",
        "_build_s14",
        "_build_s15",
    ]:
        monkeypatch.setattr(candidates_builder, name, fail_builder)
    monkeypatch.setattr(candidates_builder, "_refresh_watchlist", fake_refresh)
    monkeypatch.setattr(candidates_builder.asyncio, "sleep", fake_sleep)

    await candidates_builder._build_intraday(
        "token",
        rdb,
        session=candidates_builder.SESSION_S12_ONLY,
    )

    assert calls == ["001", "101", "refresh"]
    rdb.exists.assert_not_awaited()


def test_local_candidate_builder_session_splits_s12_after_1450():
    from datetime import time

    import candidates_builder

    assert candidates_builder._local_candidate_builder_session(time(7, 25)) == candidates_builder.SESSION_PRE_MARKET
    assert candidates_builder._local_candidate_builder_session(time(8, 25)) == candidates_builder.SESSION_PRE_MARKET
    assert candidates_builder._local_candidate_builder_session(time(9, 4, 59)) == candidates_builder.SESSION_IDLE
    assert candidates_builder._local_candidate_builder_session(time(9, 5)) == candidates_builder.SESSION_INTRADAY
    assert candidates_builder._local_candidate_builder_session(time(14, 49, 59)) == candidates_builder.SESSION_INTRADAY
    assert candidates_builder._local_candidate_builder_session(time(14, 50)) == candidates_builder.SESSION_S12_ONLY
    assert candidates_builder._local_candidate_builder_session(time(14, 55)) == candidates_builder.SESSION_S12_ONLY
    assert candidates_builder._local_candidate_builder_session(time(14, 55, 1)) == candidates_builder.SESSION_IDLE


def test_external_candidate_builder_session_keeps_weekends_idle():
    from datetime import datetime, timezone, timedelta

    import candidates_builder

    saturday = datetime(2026, 5, 2, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    assert candidates_builder._candidate_builder_session(saturday) == candidates_builder.SESSION_IDLE
