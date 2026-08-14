import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ranking_item(symbol, change_rate, trading_amount="50000000000", trading_volume="1000000"):
    return {
        "symbol": symbol,
        "price": {"lastPrice": "10000", "basePrice": "9500", "changeRate": str(change_rate)},
        "tradingAmount": trading_amount,
        "tradingVolume": trading_volume,
    }


class _FakeRdb:
    def __init__(self, market_map: dict):
        self.market_map = market_map

    async def get(self, key):
        for prefix in ("stock:market:", "stock:market_type:"):
            if key.startswith(prefix):
                return self.market_map.get(key[len(prefix):])
        return None


@pytest.mark.asyncio
async def test_supplement_filters_by_flu_rt_band_and_market(monkeypatch):
    import candidates_builder

    items = [
        _ranking_item("005930", 0.10),   # +10% in-band, KOSPI
        _ranking_item("000660", 0.02),   # +2% out of band (needs >=3%)
        _ranking_item("035420", 0.05),   # +5% in-band, but KOSDAQ -> excluded when requesting 001
        _ranking_item("999999", 0.06),   # in-band but market unresolved -> excluded
    ]

    async def fake_get_items(rdb):
        return items

    monkeypatch.setattr(candidates_builder, "TOSS_RANKING_SUPPLEMENT_ENABLED", True)
    monkeypatch.setattr(candidates_builder, "_toss_enabled", lambda: True)
    monkeypatch.setattr(candidates_builder, "_get_toss_ranking_items", fake_get_items)

    rdb = _FakeRdb({"005930": "001", "035420": "101"})
    result = await candidates_builder._toss_ranking_supplement(rdb, "001", 3.0, 20.0, 10)

    codes = [r["stk_cd"] for r in result]
    assert codes == ["005930"]
    assert result[0]["flu_rt"] == pytest.approx(10.0)
    assert result[0]["source"] == "toss_ranking"


@pytest.mark.asyncio
async def test_supplement_respects_limit(monkeypatch):
    import candidates_builder

    items = [_ranking_item(f"{i:06d}", 0.05) for i in range(5)]

    async def fake_get_items(rdb):
        return items

    monkeypatch.setattr(candidates_builder, "TOSS_RANKING_SUPPLEMENT_ENABLED", True)
    monkeypatch.setattr(candidates_builder, "_toss_enabled", lambda: True)
    monkeypatch.setattr(candidates_builder, "_get_toss_ranking_items", fake_get_items)

    rdb = _FakeRdb({f"{i:06d}": "001" for i in range(5)})
    result = await candidates_builder._toss_ranking_supplement(rdb, "001", 3.0, 8.0, 2)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_supplement_disabled_flag_returns_empty(monkeypatch):
    import candidates_builder

    monkeypatch.setattr(candidates_builder, "TOSS_RANKING_SUPPLEMENT_ENABLED", False)
    monkeypatch.setattr(candidates_builder, "_toss_enabled", lambda: True)
    result = await candidates_builder._toss_ranking_supplement(_FakeRdb({}), "001", 3.0, 8.0, 10)
    assert result == []


@pytest.mark.asyncio
async def test_supplement_toss_disabled_returns_empty(monkeypatch):
    import candidates_builder

    monkeypatch.setattr(candidates_builder, "TOSS_RANKING_SUPPLEMENT_ENABLED", True)
    monkeypatch.setattr(candidates_builder, "_toss_enabled", lambda: False)
    result = await candidates_builder._toss_ranking_supplement(_FakeRdb({}), "001", 3.0, 8.0, 10)
    assert result == []


@pytest.mark.asyncio
async def test_build_s4_merges_toss_supplement_into_final_pool(monkeypatch):
    """토스 랭킹으로만 발견된 종목이 Kiwoom raw_items 없이도 최종 후보풀에서 살아남는지 —
    _persist_candidate_quality_batch가 raw_items를 기준으로 순회하므로 toss 후보도
    raw_items에 함께 들어가야 한다."""
    import candidates_builder

    async def fake_fetch_ka10023(token, market):
        return [{"stk_cd": "005930", "sdnin_rt": "60", "flu_rt": "5.0", "trde_amt": "20000000"}]

    async def fake_toss_supplement(rdb, market, lo, hi, limit):
        return [{"stk_cd": "035720", "flu_rt": 6.0, "trde_amt": 6_000_000.0, "trde_qty": 100000, "source": "toss_ranking"}]

    async def fake_lpush(rdb, key, codes, ttl):
        rdb.saved = (key, codes, ttl)

    async def fake_strength(rdb, stk_cd, count=1):
        return {"data": None}

    rdb = MagicMock()
    rdb.hset = AsyncMock(return_value=True)
    rdb.expire = AsyncMock(return_value=True)
    pipe = MagicMock()
    pipe._queued_codes = []
    pipe.hget = MagicMock(side_effect=lambda key, code: pipe._queued_codes.append(code))

    async def fake_execute():
        names = [None] * len(pipe._queued_codes)
        pipe._queued_codes = []
        return names

    pipe.execute = AsyncMock(side_effect=fake_execute)
    rdb.pipeline = MagicMock(return_value=pipe)

    monkeypatch.setattr(candidates_builder, "_fetch_ka10023", fake_fetch_ka10023)
    monkeypatch.setattr(candidates_builder, "_toss_ranking_supplement", fake_toss_supplement)
    monkeypatch.setattr(candidates_builder, "_lpush_with_ttl", fake_lpush)
    monkeypatch.setattr(candidates_builder, "get_strength_with_status", fake_strength)
    monkeypatch.setattr(candidates_builder, "ENABLE_CANDIDATE_QUALITY_FILTER", False)

    await candidates_builder._build_s4("token", "001", rdb)

    key, codes, ttl = rdb.saved
    assert key == "candidates:s4:001"
    assert "005930" in codes
    assert "035720" in codes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder_name, source_fetch_attr, pool_key, flu_lo, flu_hi, source_flu_rt",
    [
        ("_build_s7", "_fetch_ka10027", "candidates:s7:001", 0.5, 10.0, "1.0"),
        ("_build_s8", "_fetch_ka10027", "candidates:s8:001", 0.5, 8.0, "1.0"),
        ("_build_s9", "_fetch_ka10027", "candidates:s9:001", 0.5, 8.0, "1.0"),
        ("_build_s14", "_fetch_ka10027", "candidates:s14:001", -10.0, -3.0, "-5.0"),
    ],
)
async def test_ka10027_builders_merge_toss_supplement(
    monkeypatch, builder_name, source_fetch_attr, pool_key, flu_lo, flu_hi, source_flu_rt
):
    """S7/S8/S9/S14도 S4/S13과 동일한 패턴으로 토스 랭킹 보강을 사용해야 한다
    (2026-08-12 사용자 요청: ka10027 기반 등락률 순위 전략으로 확장)."""
    import candidates_builder

    async def fake_fetch(token, market, sort_tp="1"):
        return [{"stk_cd": "005930", "flu_rt": source_flu_rt}]

    seen_band = {}

    async def fake_toss_supplement(rdb, market, lo, hi, limit):
        seen_band["band"] = (lo, hi)
        return [{"stk_cd": "035720", "flu_rt": (lo + hi) / 2, "source": "toss_ranking"}]

    async def fake_lpush(rdb, key, codes, ttl):
        rdb.saved = (key, codes, ttl)

    async def fake_filter(rdb, codes):
        return codes

    rdb = MagicMock()
    rdb.hset = AsyncMock(return_value=True)
    rdb.expire = AsyncMock(return_value=True)

    monkeypatch.setattr(candidates_builder, source_fetch_attr, fake_fetch)
    monkeypatch.setattr(candidates_builder, "_toss_ranking_supplement", fake_toss_supplement)
    monkeypatch.setattr(candidates_builder, "_lpush_with_ttl", fake_lpush)
    monkeypatch.setattr(candidates_builder, "_filter_individual_stocks", fake_filter)

    builder = getattr(candidates_builder, builder_name)
    await builder("token", "001", rdb)

    key, codes, ttl = rdb.saved
    assert key == pool_key
    assert "005930" in codes
    assert "035720" in codes
    assert seen_band["band"] == (flu_lo, flu_hi)


@pytest.mark.asyncio
async def test_ka10027_builders_dedupe_toss_overlap_with_kiwoom(monkeypatch):
    """키움 raw 응답에 이미 있는 코드는 토스 쪽에서 중복으로 다시 추가되지 않는다."""
    import candidates_builder

    async def fake_fetch(token, market, sort_tp="1"):
        return [{"stk_cd": "005930", "flu_rt": "1.0"}]

    async def fake_toss_supplement(rdb, market, lo, hi, limit):
        # 키움이 이미 반환한 종목이 토스 랭킹에도 잡힌 경우 — 교집합은 제외되어야 함
        return [{"stk_cd": "005930", "flu_rt": 1.0, "source": "toss_ranking"}]

    async def fake_lpush(rdb, key, codes, ttl):
        rdb.saved = (key, codes, ttl)

    async def fake_filter(rdb, codes):
        return codes

    rdb = MagicMock()
    monkeypatch.setattr(candidates_builder, "_fetch_ka10027", fake_fetch)
    monkeypatch.setattr(candidates_builder, "_toss_ranking_supplement", fake_toss_supplement)
    monkeypatch.setattr(candidates_builder, "_lpush_with_ttl", fake_lpush)
    monkeypatch.setattr(candidates_builder, "_filter_individual_stocks", fake_filter)

    await candidates_builder._build_s8("token", "001", rdb)

    key, codes, ttl = rdb.saved
    assert codes.count("005930") == 1
