import os
import sys
from unittest.mock import AsyncMock, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_record_signal_metric_matches_status_report_keys():
    from vi_watch_worker import _record_signal_metric

    rdb = AsyncMock()

    await _record_signal_metric(rdb, {"stk_cd": "005930", "score": 72.5})

    rdb.incr.assert_awaited_once_with("status:signals_10m:S2_VI_PULLBACK")
    rdb.hset.assert_awaited_once()
    assert rdb.hset.await_args.args[0] == "status:last_signal:S2_VI_PULLBACK"
    assert rdb.hset.await_args.kwargs["mapping"]["stk_cd"] == "005930"
    assert rdb.hset.await_args.kwargs["mapping"]["score"] == "72.5"
    rdb.expire.assert_has_awaits(
        [
            call("status:signals_10m:S2_VI_PULLBACK", 600),
            call("status:last_signal:S2_VI_PULLBACK", 600),
        ]
    )


@pytest.mark.asyncio
async def test_record_worker_metric_updates_status_hash_and_counter():
    from vi_watch_worker import _record_worker_metric

    rdb = AsyncMock()

    await _record_worker_metric(rdb, "published", "005930")

    rdb.hset.assert_awaited_once()
    assert rdb.hset.await_args.args[0] == "status:s2_vi_watch_worker"
    assert rdb.hset.await_args.kwargs["mapping"]["last_event"] == "published"
    assert rdb.hset.await_args.kwargs["mapping"]["last_stk_cd"] == "005930"
    rdb.hincrby.assert_awaited_once_with("status:s2_vi_watch_worker", "published_count", 1)
    rdb.expire.assert_awaited_once_with("status:s2_vi_watch_worker", 600)
