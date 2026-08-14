import asyncio
import os
import sys
import time
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
        return {"for_cont_nettrde_upper": self._items, "return_code": 0}

    def raise_for_status(self):
        return None


class _MockClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._post)

    async def _post(self, url, headers=None, json=None):
        if not self._responses:
            raise AssertionError("No mock response left")
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_s11_enriches_investor_flow_and_bid_ratio(monkeypatch):
    import strategy_11_frgn_cont as s11

    rdb = MagicMock()
    rdb.lrange = AsyncMock(return_value=[])
    rdb.hgetall = AsyncMock(return_value={
        "flu_rt": "3.0",
        "cntr_str": "125",
        "updated_at_ms": str(int(time.time() * 1000)),
    })

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {"tp1_price": 10500, "sl_price": 9500, "rr_ratio": 1.0}

    raw_items = [{
        "stk_cd": "005930",
        "cur_prc": "10000",
        "dm1": "1000000",
        "dm2": "900000",
        "dm3": "800000",
        "tot": "2700000",
    }]

    monkeypatch.setattr(s11, "fetch_frgn_cont_buy", AsyncMock(return_value=raw_items))
    monkeypatch.setattr(
        s11,
        "fetch_investor_flow_summary_cached",
        AsyncMock(return_value=(
            {"smart_money": 7000, "foreign": 5000, "institution": 2000, "individual": -7000},
            {"api_id": "ka10061"},
        )),
    )
    monkeypatch.setattr(s11, "fetch_hoga", AsyncMock(return_value=1.25))
    monkeypatch.setattr(
        s11,
        "fetch_intraday_investor_flow_cached",
        AsyncMock(return_value=(
            {"combined_slope": 25.0, "recent_reversal": True, "recent_reversal_direction": "positive"},
            {"api_id": "ka10064", "source": "rest", "error": None},
        )),
    )
    monkeypatch.setattr(s11, "fetch_stk_nm", AsyncMock(return_value="삼성전자"))
    monkeypatch.setattr(s11, "fetch_daily_candles", AsyncMock(return_value=[]))
    monkeypatch.setattr(s11, "calc_tp_sl", MagicMock(return_value=fake_tp_sl))

    result = await s11.scan_frgn_cont_swing("token", rdb=rdb)

    assert len(result) == 1
    signal = result[0]
    assert signal["bid_ratio"] == 1.25
    assert signal["investor_smart_money"] == 7000
    assert signal["investor_flow_meta"]["api_id"] == "ka10061"
    assert signal["score"] > 0
    assert signal["extra"]["intraday_investor_flow"]["combined_slope"] == 25.0
    assert signal["extra"]["intraday_investor_flow"]["recent_reversal"] is True


@pytest.mark.asyncio
async def test_s11_skips_empty_current_price_without_aborting_scan(monkeypatch):
    import strategy_11_frgn_cont as s11

    rdb = MagicMock()
    rdb.lrange = AsyncMock(return_value=[])
    rdb.hgetall = AsyncMock(return_value={
        "flu_rt": "3.0",
        "cntr_str": "125",
        "updated_at_ms": str(int(time.time() * 1000)),
    })
    monkeypatch.setattr(s11, "S11_SCAN_LIMIT_PER_MARKET", 1)
    monkeypatch.setattr(s11, "fetch_frgn_cont_buy", AsyncMock(return_value=[
        {
            "stk_cd": "005930",
            "cur_prc": "",
            "dm1": "1000000",
            "dm2": "900000",
            "dm3": "800000",
            "tot": "2700000",
        },
        {
            "stk_cd": "000660",
            "cur_prc": "10000",
            "dm1": "1000000",
            "dm2": "900000",
            "dm3": "800000",
            "tot": "2700000",
        },
    ]))
    monkeypatch.setattr(
        s11,
        "fetch_investor_flow_summary_cached",
        AsyncMock(return_value=({}, {"api_id": "ka10061"})),
    )
    monkeypatch.setattr(s11, "fetch_hoga", AsyncMock(return_value=1.0))
    monkeypatch.setattr(s11, "calc_tp_sl", MagicMock(side_effect=AssertionError("invalid price must be skipped")))

    result = await s11.scan_frgn_cont_swing("token", market="001", rdb=rdb)

    assert result == []


def test_fetch_frgn_cont_buy_strips_kiwoom_suffix():
    """ka10035 응답의 '_AL' 접미사를 정규화하지 않으면 candidates:s11 풀(정규화된 코드)과
    교집합이 항상 비게 되는 회귀 방지 테스트 (S11이 몇 달간 신호를 하나도 못 낸 원인)."""
    import strategy_11_frgn_cont as s11

    client = _MockClient([
        _MockResponse([
            {"stk_cd": "005930_AL", "cur_prc": "10000", "dm1": "100", "dm2": "100", "dm3": "100", "tot": "300"},
        ]),
    ])

    with patch("strategy_11_frgn_cont.kiwoom_client", return_value=client):
        result = _run(s11.fetch_frgn_cont_buy("token", "001"))

    assert len(result) == 1
    assert result[0]["stk_cd"] == "005930"


@pytest.mark.asyncio
async def test_s11_matches_pool_despite_raw_kiwoom_suffix(monkeypatch):
    """candidates:s11 풀(정규화됨)과 ka10035 raw item(접미사 포함)이 실제로 매칭되는지 확인."""
    import strategy_11_frgn_cont as s11

    rdb = MagicMock()
    rdb.lrange = AsyncMock(return_value=["005930"])
    rdb.hgetall = AsyncMock(return_value={
        "flu_rt": "3.0",
        "cntr_str": "125",
        "updated_at_ms": str(int(time.time() * 1000)),
    })

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {"tp1_price": 10500, "sl_price": 9500, "rr_ratio": 1.0}

    client = _MockClient([
        _MockResponse([
            {"stk_cd": "005930_AL", "cur_prc": "10000", "dm1": "1000000", "dm2": "900000",
             "dm3": "800000", "tot": "2700000"},
        ]),
    ])

    monkeypatch.setattr(s11, "kiwoom_client", lambda: client)
    monkeypatch.setattr(
        s11,
        "fetch_investor_flow_summary_cached",
        AsyncMock(return_value=(
            {"smart_money": 7000, "foreign": 5000, "institution": 2000, "individual": -7000},
            {"api_id": "ka10061"},
        )),
    )
    monkeypatch.setattr(s11, "fetch_hoga", AsyncMock(return_value=1.25))
    monkeypatch.setattr(
        s11,
        "fetch_intraday_investor_flow_cached",
        AsyncMock(return_value=(
            {"combined_slope": 25.0, "recent_reversal": True, "recent_reversal_direction": "positive"},
            {"api_id": "ka10064", "source": "rest", "error": None},
        )),
    )
    monkeypatch.setattr(s11, "fetch_stk_nm", AsyncMock(return_value="삼성전자"))
    monkeypatch.setattr(s11, "fetch_daily_candles", AsyncMock(return_value=[]))
    monkeypatch.setattr(s11, "calc_tp_sl", MagicMock(return_value=fake_tp_sl))

    result = await s11.scan_frgn_cont_swing("token", market="001", rdb=rdb)

    assert len(result) == 1
    assert result[0]["stk_cd"] == "005930"
