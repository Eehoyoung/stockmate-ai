import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_s9_reads_strategy_owned_candidate_pool_when_available():
    from strategy_9_pullback import scan_pullback_swing

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[[], []])

    result = await scan_pullback_swing("token", rdb=rdb)

    assert result == []
    assert rdb.lrange.await_args_list[0].args == ("candidates:s9:001", 0, 99)
    assert rdb.lrange.await_args_list[1].args == ("candidates:s9:101", 0, 99)
