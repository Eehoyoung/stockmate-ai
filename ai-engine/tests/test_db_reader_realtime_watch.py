import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_realtime_watch_includes_paper_position_without_fill():
    from db_reader import get_realtime_watch_codes

    pool = AsyncMock()
    pool.fetch.return_value = [{"stk_cd": "373220"}]

    assert await get_realtime_watch_codes(pool) == ["373220"]
    sql = pool.fetch.await_args.args[0]
    assert "executed_at IS NOT NULL" not in sql
    assert "entry_qty" not in sql
