import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_s2_window_uses_open_day_and_1450_exclusive_boundary():
    from vi_watch_worker import _is_s2_window_open

    kst = timezone(timedelta(hours=9))
    assert _is_s2_window_open(datetime(2026, 8, 3, 9, 0, tzinfo=kst)) is True
    assert _is_s2_window_open(datetime(2026, 8, 3, 14, 49, 59, tzinfo=kst)) is True
    assert _is_s2_window_open(datetime(2026, 8, 3, 14, 50, tzinfo=kst)) is False
    assert _is_s2_window_open(datetime(2026, 8, 2, 10, 0, tzinfo=kst)) is False


def test_etf_etn_item_filter_blocks_products_only():
    from vi_watch_worker import _is_etf_or_etn_item

    assert _is_etf_or_etn_item({"stk_nm": "키움 코스닥 150 TR ETN"}) is True
    assert _is_etf_or_etn_item({"stk_nm": "KODEX 200 ETF"}) is True
    assert _is_etf_or_etn_item({"stk_nm": "IBK 코스피액티브"}) is True
    assert _is_etf_or_etn_item({"stk_nm": "삼성전자"}) is False


@pytest.mark.asyncio
async def test_stale_release_filter_keeps_only_latest_vi_price():
    from vi_watch_worker import _is_stale_release_item

    rdb = AsyncMock()
    rdb.hgetall.return_value = {"vi_price": "2160"}

    assert await _is_stale_release_item(rdb, {"stk_cd": "179530", "vi_price": 2040}) is True
    assert await _is_stale_release_item(rdb, {"stk_cd": "179530", "vi_price": 2160}) is False


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


@pytest.mark.asyncio
async def test_supplement_only_enqueues_fresh_released_vi(monkeypatch):
    import vi_watch_worker

    monkeypatch.setattr(vi_watch_worker.time, "time", lambda: 1_000.0)
    rdb = AsyncMock()
    rdb.lrange.side_effect = [["005930", "000660", "035420"], []]
    rdb.exists.return_value = False

    async def hgetall(key):
        return {
            "vi:005930": {
                "status": "released",
                "released_at_ms": "990000",
                "vi_price": "70000",
                "vi_type": "2",
            },
            "vi:000660": {
                "status": "released",
                "released_at_ms": "900000",
                "vi_price": "120000",
                "vi_type": "2",
            },
            "vi:035420": {
                "status": "active",
                "released_at_ms": "995000",
                "vi_price": "60000",
                "vi_type": "1",
            },
        }[key]

    rdb.hgetall.side_effect = hgetall
    rdb.set.return_value = True

    count = await vi_watch_worker._supplement_from_pool(rdb)

    assert count == 1
    queued = rdb.lpush.await_args.args
    assert queued[0] == "vi_watch_queue"
    assert '"stk_cd": "005930"' in queued[1]
    rdb.set.assert_awaited_once_with(
        "vi:release:queue_dedup:005930:70000.0",
        "1",
        nx=True,
        ex=vi_watch_worker._SUPPLEMENT_DEDUP_SEC,
    )


@pytest.mark.asyncio
async def test_supplement_deduplicates_same_release(monkeypatch):
    import vi_watch_worker

    monkeypatch.setattr(vi_watch_worker.time, "time", lambda: 1_000.0)
    rdb = AsyncMock()
    rdb.lrange.side_effect = [["005930"], []]
    rdb.exists.return_value = False
    rdb.hgetall.return_value = {
        "status": "released",
        "released_at_ms": "995000",
        "vi_price": "70000",
        "vi_type": "2",
    }
    rdb.set.return_value = False

    count = await vi_watch_worker._supplement_from_pool(rdb)

    assert count == 0
    rdb.lpush.assert_not_awaited()


@pytest.mark.asyncio
async def test_requeue_uses_five_second_worker_cadence(monkeypatch):
    import vi_watch_worker

    rdb = AsyncMock()
    sleep = AsyncMock()
    metric = AsyncMock()
    monkeypatch.setattr(vi_watch_worker.asyncio, "sleep", sleep)
    monkeypatch.setattr(vi_watch_worker, "_record_worker_metric", metric)

    await vi_watch_worker._requeue_watch_item(rdb, '{"stk_cd":"005930"}', "005930")

    rdb.lpush.assert_awaited_once_with("vi_watch_queue", '{"stk_cd":"005930"}')
    metric.assert_awaited_once_with(rdb, "requeued", "005930")
    sleep.assert_awaited_once_with(vi_watch_worker.POLL_INTERVAL)
