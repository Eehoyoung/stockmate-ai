import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Pipe:
    def __init__(self):
        self.calls = []

    def delete(self, *args):
        self.calls.append(("delete", args))
        return self

    def rpush(self, *args):
        self.calls.append(("rpush", args))
        return self

    def expire(self, *args):
        self.calls.append(("expire", args))
        return self

    def hset(self, *args, **kwargs):
        self.calls.append(("hset", args, kwargs))
        return self

    async def execute(self):
        return []


@pytest.mark.asyncio
async def test_persist_candidate_quality_writes_raw_qualified_and_hash(monkeypatch):
    import candidates_builder as cb

    monkeypatch.setattr(cb, "ENABLE_CANDIDATE_QUALITY_FILTER", True)
    pipe = _Pipe()
    rdb = MagicMock()
    rdb.pipeline.return_value = pipe

    raw_items = [
        {"stk_cd": "005930", "stk_nm": "삼성전자", "trde_qty": "900000"},
        {"stk_cd": "123456", "stk_nm": "테스트ETF", "trde_qty": "900000"},
    ]

    final_codes = await cb._persist_candidate_quality_batch(
        rdb,
        strategy_id="s1",
        market="001",
        source_api="ka10029",
        raw_items=raw_items,
        qualified_codes=["005930", "123456"],
        ttl=900,
    )

    assert final_codes == ["005930"]
    assert ("delete", ("candidates:raw:ka10029:001",)) in pipe.calls
    assert ("delete", ("candidates:qualified:s1:001",)) in pipe.calls
    hset_calls = [call for call in pipe.calls if call[0] == "hset"]
    assert any(call[1][0] == "candidate:quality:005930" for call in hset_calls)
    assert any(call[1][0] == "candidate:quality:123456" for call in hset_calls)


def test_priority_score_handles_string_and_bytes_quality_values():
    from candidates_builder import _calculate_watchlist_priority_score

    score = _calculate_watchlist_priority_score(
        "005930",
        ["s1", "s4"],
        {
            b"candidate_quality": b"A",
            b"liquidity_score": b"90",
            b"built_at": b"2026-05-06T09:00:00+09:00",
        },
    )

    assert score > 0
