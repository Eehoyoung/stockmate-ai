import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rdb(**overrides):
    rdb = MagicMock()
    rdb.zrevrange = AsyncMock(return_value=overrides.get("zrevrange", []))
    smembers = overrides.get("smembers")
    if smembers is None:
        smembers = [
            overrides.get("hold_watchlist", set()),
            overrides.get("priority_watchlist", set()),
            overrides.get("watchlist", set()),
        ]
    rdb.smembers = AsyncMock(side_effect=smembers)
    rdb.lrange = AsyncMock(return_value=overrides.get("lrange", []))
    return rdb


@pytest.mark.asyncio
async def test_ranked_candidates_prefers_zset_order():
    from ws_client import _get_ranked_candidates

    rdb = _rdb(zrevrange=["000003", "000002", "000001"])

    ranked, top100 = await _get_ranked_candidates(rdb)

    assert ranked == ["000003", "000002", "000001"]
    assert top100 == ranked
    rdb.smembers.assert_awaited_once_with("hold_monitor:watchlist")


@pytest.mark.asyncio
async def test_ranked_candidates_falls_back_to_priority_set():
    from ws_client import _get_ranked_candidates

    rdb = _rdb(zrevrange=[], priority_watchlist={"000002"}, watchlist={"000001", "000002"})

    ranked, top100 = await _get_ranked_candidates(rdb)

    assert ranked == ["000002", "000001"]
    assert top100 == ranked


@pytest.mark.asyncio
async def test_ranked_candidates_falls_back_to_watchlist_set():
    from ws_client import _get_ranked_candidates

    rdb = _rdb(zrevrange=[], watchlist={"000004", "000003"})

    ranked, top100 = await _get_ranked_candidates(rdb)

    assert ranked == ["000003", "000004"]
    assert top100 == ranked


@pytest.mark.asyncio
async def test_ranked_candidates_keeps_hold_codes_ahead_of_zset():
    from ws_client import _get_ranked_candidates

    rdb = _rdb(zrevrange=["000003", "000002"], hold_watchlist={"000001"})

    ranked, top100 = await _get_ranked_candidates(rdb)

    assert ranked == ["000001", "000003", "000002"]
    assert top100 == ranked


@pytest.mark.asyncio
async def test_ranked_candidates_keeps_hold_codes_ahead_of_watchlist():
    from ws_client import _get_ranked_candidates

    rdb = _rdb(zrevrange=[], watchlist={"000004", "000003"}, hold_watchlist={"000001"})

    ranked, top100 = await _get_ranked_candidates(rdb)

    assert ranked == ["000001", "000003", "000004"]
    assert top100 == ranked
