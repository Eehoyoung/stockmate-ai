import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Response:
    headers = {"cont-yn": "N"}

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


@pytest.mark.asyncio
async def test_candidate_builder_uses_official_etf_etn_request_filters(monkeypatch):
    import candidates_builder as cb

    calls = []

    async def fake_post(url, headers, body, api_id):
        calls.append((api_id, body))
        response_body = {
            "ka10029": {"exp_cntr_flu_rt_upper": []},
            "ka10023": {"trde_qty_sdnin": []},
            "ka10027": {"pred_pre_flu_rt_upper": []},
            "ka10054": {"motn_stk": []},
        }[api_id]
        return _Response(response_body)

    monkeypatch.setattr(cb, "kiwoom_post", fake_post)
    monkeypatch.setattr(cb, "validate_kiwoom_response", lambda *args: True)
    monkeypatch.setattr(cb, "_lpush_with_ttl", AsyncMock())

    await cb._fetch_ka10029("token", "001")
    await cb._fetch_ka10023("token", "001")
    await cb._fetch_ka10027("token", "001")
    await cb._build_s2("token", "001", object())

    payloads = {api_id: body for api_id, body in calls}
    assert payloads["ka10029"]["stk_cnd"] == "16"
    assert payloads["ka10023"]["stk_cnd"] == "20"
    assert payloads["ka10027"]["stk_cnd"] == "16"
    assert payloads["ka10054"]["skip_stk"] == "000000011"


def test_etf_etn_name_filter_is_case_insensitive():
    import candidates_builder as cb
    import strategy_10_new_high as s10

    for value in ("KODEX 200 ETF", "ETN 테스트", "leveraged etf"):
        assert cb._is_etf_or_etn_name(value)
        assert s10._is_etf_or_etn_name(value)

    assert not cb._is_etf_or_etn_name("삼성전자")
    assert not s10._is_etf_or_etn_name("삼성전자")


def test_live_confluence_uses_documented_production_requests():
    import candidates_builder as cb

    requests = {name: (body, api_id, response_key) for name, body, api_id, response_key in cb._live_confluence_requests("001")}

    assert requests["liquidity"][1:] == ("ka10030", "tdy_trde_qty_upper")
    assert requests["liquidity"][0]["mang_stk_incls"] == "16"
    assert requests["foreign_net_buy"][0] == {
        "mrkt_tp": "001", "trde_tp": "2", "dt": "0", "stex_tp": "3",
    }
    assert requests["same_net_buy"][0]["strt_dt"]
    assert requests["same_net_buy"][0]["end_dt"]
    assert requests["bid_balance"][0]["stk_cnd"] == "1"
    assert requests["bid_surge"][0]["stk_cnd"] == "1"
    assert requests["ratio_surge"][0]["stk_cnd"] == "1"


def test_live_confluence_requires_liquidity_and_flow_confirmation():
    from candidates_builder import _score_live_confluence

    scores, confirmed = _score_live_confluence(
        {"A", "B", "C"},
        {
            "liquidity": {"A", "B"},
            "foreign_net_buy": {"A"},
            "same_net_buy": {"B"},
            "bid_balance": {"A"},
            "bid_surge": {"A"},
        },
    )

    assert confirmed == ["A", "B"]
    assert scores["A"] > scores["B"]
    assert "C" not in scores


@pytest.mark.asyncio
async def test_s10_filters_etf_etn_when_ka10016_cannot_do_so(monkeypatch):
    import candidates_builder as cb

    captured = {}

    async def fake_post(url, headers, body, api_id):
        assert api_id == "ka10016"
        return _Response({
            "ntl_pric": [
                {"stk_cd": "005930", "stk_nm": "삼성전자"},
                {"stk_cd": "069500", "stk_nm": "KODEX 200 ETF"},
                {"stk_cd": "580001", "stk_nm": "테스트 ETN"},
            ]
        })

    async def capture_filter(rdb, codes):
        captured["after_name_filter"] = codes
        return codes

    async def capture_persist(rdb, **kwargs):
        captured["qualified_codes"] = kwargs["qualified_codes"]
        return kwargs["qualified_codes"]

    monkeypatch.setattr(cb, "kiwoom_post", fake_post)
    monkeypatch.setattr(cb, "validate_kiwoom_response", lambda *args: True)
    monkeypatch.setattr(cb, "_filter_individual_stocks", capture_filter)
    monkeypatch.setattr(cb, "_persist_candidate_quality_batch", capture_persist)
    monkeypatch.setattr(cb, "_lpush_with_ttl", AsyncMock())

    await cb._build_s10("token", "001", object())

    assert captured["after_name_filter"] == ["005930"]
    assert captured["qualified_codes"] == ["005930"]
