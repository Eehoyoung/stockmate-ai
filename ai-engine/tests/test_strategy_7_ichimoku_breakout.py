import os
import sys
import importlib
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_s7_reads_expanded_strategy_owned_candidate_pool_when_available(monkeypatch):
    monkeypatch.setenv("S7_POOL_READ_LIMIT", "180")
    import strategy_7_ichimoku_breakout
    strategy_7_ichimoku_breakout = importlib.reload(strategy_7_ichimoku_breakout)

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[[], []])

    result = await strategy_7_ichimoku_breakout.scan_ichimoku_breakout("token", rdb=rdb)

    assert result == []
    assert rdb.lrange.await_args_list[0].args == ("candidates:s7:001", 0, 179)
    assert rdb.lrange.await_args_list[1].args == ("candidates:s7:101", 0, 179)
