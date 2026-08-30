import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _async_value(value):
    return value


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
    monkeypatch.setattr(candidates_builder, "_filter_individual_stocks", lambda _rdb, codes: _async_value(codes))

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
    monkeypatch.setattr(candidates_builder, "_filter_individual_stocks", lambda _rdb, codes: _async_value(codes))

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


@pytest.mark.asyncio
async def test_build_intraday_does_not_rebuild_expired_opening_s1_pool(monkeypatch):
    import candidates_builder

    calls = []

    async def fake_builder(token, market, rdb):
        calls.append(market)

    async def fail_s1(*args, **kwargs):
        raise AssertionError("S1 must not be rebuilt after its opening scan window")

    async def fake_refresh(rdb):
        calls.append("refresh")

    async def fake_sleep(_seconds):
        return None

    rdb = MagicMock()
    rdb.exists = AsyncMock(return_value=False)

    monkeypatch.setattr(candidates_builder, "MARKETS", ["001", "101"])
    monkeypatch.setattr(candidates_builder, "_build_s1", fail_s1)
    for name in [
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
        "_build_s12",
        "_build_s13",
        "_build_s14",
        "_build_s15",
    ]:
        monkeypatch.setattr(candidates_builder, name, fake_builder)
    monkeypatch.setattr(candidates_builder, "_refresh_watchlist", fake_refresh)
    monkeypatch.setattr(candidates_builder.asyncio, "sleep", fake_sleep)

    await candidates_builder._build_intraday(
        "token",
        rdb,
        session=candidates_builder.SESSION_INTRADAY,
    )

    assert calls[-1] == "refresh"
    rdb.exists.assert_not_awaited()


def test_local_candidate_builder_session_splits_s12_after_1450():
    from datetime import time

    import candidates_builder

    assert candidates_builder._local_candidate_builder_session(time(7, 25)) == candidates_builder.SESSION_PRE_MARKET
    assert candidates_builder._local_candidate_builder_session(time(8, 25)) == candidates_builder.SESSION_PRE_MARKET
    assert candidates_builder._local_candidate_builder_session(time(8, 25, 1)) == candidates_builder.SESSION_OPENING_RECOVERY
    assert candidates_builder._local_candidate_builder_session(time(9, 4, 59)) == candidates_builder.SESSION_OPENING_RECOVERY
    assert candidates_builder._local_candidate_builder_session(time(9, 5)) == candidates_builder.SESSION_INTRADAY
    assert candidates_builder._local_candidate_builder_session(time(14, 29, 59)) == candidates_builder.SESSION_INTRADAY
    assert candidates_builder._local_candidate_builder_session(time(14, 30)) == candidates_builder.SESSION_S12_ONLY
    assert candidates_builder._local_candidate_builder_session(time(15, 10)) == candidates_builder.SESSION_S12_ONLY
    assert candidates_builder._local_candidate_builder_session(time(15, 10, 1)) == candidates_builder.SESSION_IDLE


def test_external_candidate_builder_session_keeps_weekends_idle():
    from datetime import datetime, timezone, timedelta

    import candidates_builder

    saturday = datetime(2026, 5, 2, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    assert candidates_builder._candidate_builder_session(saturday) == candidates_builder.SESSION_IDLE


@pytest.mark.asyncio
async def test_filter_individual_stocks_removes_etf_etn(monkeypatch):
    """ETF/ETN 종목명 키워드가 포함된 종목은 필터링되어야 한다."""
    import candidates_builder

    codes = ["005930", "069500", "233740", "035720"]
    # stock:code_map: 005930=삼성전자, 069500=KODEX 200 ETF, 233740=KODEX 레버리지, 035720=카카오
    name_map = {
        "005930": "삼성전자",
        "069500": "KODEX 200 ETF",
        "233740": "KODEX 레버리지",
        "035720": "카카오",
    }

    pipe_mock = AsyncMock()
    pipe_mock.hget = MagicMock(return_value=None)
    pipe_mock.execute = AsyncMock(return_value=[name_map.get(c) for c in codes])

    rdb = MagicMock()
    rdb.pipeline = MagicMock(return_value=pipe_mock)

    result = await candidates_builder._filter_individual_stocks(rdb, codes)

    assert "005930" in result   # 삼성전자 — 유지
    assert "035720" in result   # 카카오 — 유지
    assert "069500" not in result  # ETF 키워드 → 제거
    assert "233740" not in result  # 레버리지 키워드 → 제거


@pytest.mark.asyncio
async def test_filter_individual_stocks_removes_brand_prefix_without_blocking_companies():
    import candidates_builder

    codes = ["069500", "0208N0", "138930", "024110", "005930"]
    names = ["KODEX 200", "IBK 코스피액티브", "BNK금융지주", "IBK기업은행", "삼성전자"]
    pipe_mock = AsyncMock()
    pipe_mock.hget = MagicMock(return_value=None)
    pipe_mock.execute = AsyncMock(return_value=names)
    rdb = MagicMock()
    rdb.pipeline = MagicMock(return_value=pipe_mock)

    result = await candidates_builder._filter_individual_stocks(rdb, codes)

    assert result == ["138930", "024110", "005930"]


@pytest.mark.asyncio
async def test_filter_individual_stocks_blocks_on_redis_error():
    """Redis 오류로 이름을 검증할 수 없으면 후보를 차단해야 한다."""
    import candidates_builder

    codes = ["005930", "069500"]

    rdb = MagicMock()
    rdb.pipeline = MagicMock(side_effect=Exception("redis down"))

    result = await candidates_builder._filter_individual_stocks(rdb, codes)

    assert result == []


@pytest.mark.asyncio
async def test_filter_individual_stocks_blocks_none_names():
    """stock:code_map에 이름이 없는 종목은 상품 여부를 확인할 수 없어 차단한다."""
    import candidates_builder

    codes = ["000001", "000002"]

    pipe_mock = AsyncMock()
    pipe_mock.hget = MagicMock(return_value=None)
    pipe_mock.execute = AsyncMock(return_value=[None, None])  # 이름 미조회

    rdb = MagicMock()
    rdb.pipeline = MagicMock(return_value=pipe_mock)

    result = await candidates_builder._filter_individual_stocks(rdb, codes)

    assert result == []


@pytest.mark.asyncio
async def test_refresh_watchlist_includes_s16_pool(monkeypatch):
    """s16 후보 풀도 watchlist에 통합되어야 한다.

    range(1, 16) 하드코딩 탓에 s16이 통째로 빠져 있었고, 그 결과 S16 종목은
    websocket-listener의 실시간 구독 대상에서 영구 제외됐다 (2026-08-10 수정).
    """
    import candidates_builder

    monkeypatch.setattr(candidates_builder, "MARKETS", ["001"])
    monkeypatch.setattr(candidates_builder, "ENABLE_WATCHLIST_ZSET", False)

    async def fake_lrange(key, start, end):
        return {
            "candidates:s16:001": ["016160"],
            "candidates:s1:001": ["000100"],
        }.get(key, [])

    added = {}

    def fake_sadd(key, *codes):
        added.setdefault(key, set()).update(codes)

    pipe = MagicMock()
    pipe.delete = MagicMock()
    pipe.sadd = MagicMock(side_effect=fake_sadd)
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock()

    rdb = MagicMock()
    rdb.lrange = AsyncMock(side_effect=fake_lrange)
    rdb.pipeline = MagicMock(return_value=pipe)

    await candidates_builder._refresh_watchlist(rdb)

    assert "016160" in added["candidates:watchlist"], "s16 후보가 watchlist에 누락됨"
    assert "000100" in added["candidates:watchlist"]
