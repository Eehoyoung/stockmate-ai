import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _candles(count=60):
    candles = []
    for i in range(count):
        if i == 0:
            close = 107
            high = 108
            low = 101
            volume = 2200
        elif i < 20:
            close = 104 - (i * 0.2)
            high = 107
            low = 90
            volume = 1000
        elif i < 40:
            close = 96 - ((i - 20) * 0.1)
            high = 102
            low = 85
            volume = 900
        else:
            close = 94
            high = 101
            low = 84
            volume = 800
        candles.append({
            "cur_prc": str(round(close, 2)),
            "open_pric": str(round(close - 1, 2)),
            "high_pric": str(round(high, 2)),
            "low_pric": str(round(low, 2)),
            "trde_qty": str(volume),
            "trde_prica": "3000000000",
        })
    return candles


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.kv = {}
        self.lists = {}
        self.zsets = {}
        self.sets = {}
        self.expires = {}

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)
        return 1

    async def expire(self, key, ttl):
        self.expires[key] = ttl
        return True

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def rpop(self, key):
        values = self.lists.get(key, [])
        return values.pop() if values else None

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]
        return True

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:end + 1]


def test_calculate_s16_metrics_promotes_confirmed_setup_to_triggered():
    from s16_accumulation_state import STATE_TRIGGERED
    from strategy_16_accumulation import calculate_s16_metrics

    metrics = calculate_s16_metrics(
        _candles(),
        market_cap_eok=5000,
        cntr_strength=135,
        bid_ratio=1.6,
        supply_score_hint=25,
    )

    assert metrics.state == STATE_TRIGGERED
    assert metrics.total_score >= 80
    assert metrics.rr_ratio >= 1.6
    assert metrics.box_low > 0
    assert metrics.box_high > metrics.box_low


def test_market_cap_input_normalizes_legacy_won_unit():
    from strategy_16_accumulation import _normalize_market_cap_eok, calculate_s16_metrics

    assert _normalize_market_cap_eok(500_000_000_000) == 5000

    metrics = calculate_s16_metrics(
        _candles(),
        market_cap_eok=500_000_000_000,
        cntr_strength=135,
        bid_ratio=1.6,
        supply_score_hint=25,
    )

    assert metrics.risk_score == 10


def test_observed_calendar_days_counts_kst_dates():
    from datetime import datetime
    from strategy_16_accumulation import KST, _observed_calendar_days

    first = int(datetime(2026, 7, 1, 15, 0, tzinfo=KST).timestamp())
    current = int(datetime(2026, 7, 3, 9, 0, tzinfo=KST).timestamp())

    assert _observed_calendar_days(first, current) == 3
    assert _observed_calendar_days(current, current) == 1


def test_calculate_s16_metrics_rejects_overheated_and_out_of_range_market_cap():
    from s16_accumulation_state import STATE_REJECTED
    from strategy_16_accumulation import calculate_s16_metrics

    candles = _candles()
    candles[0]["cur_prc"] = "160"
    candles[0]["high_pric"] = "162"
    metrics = calculate_s16_metrics(
        candles,
        market_cap_eok=500,
        cntr_strength=135,
        bid_ratio=1.6,
        supply_score_hint=25,
    )

    assert metrics.state == STATE_REJECTED
    assert metrics.risk_score < 5


def test_build_s16_signal_contains_execution_contract_fields():
    from s16_accumulation_state import STRATEGY_NAME
    from strategy_16_accumulation import build_s16_signal, calculate_s16_metrics

    metrics = calculate_s16_metrics(
        _candles(),
        market_cap_eok=5000,
        cntr_strength=135,
        bid_ratio=1.6,
        supply_score_hint=25,
    )
    signal = build_s16_signal("A005930", "Samsung", metrics, market_cap_eok=5000)

    assert signal["stk_cd"] == "005930"
    assert signal["strategy"] == STRATEGY_NAME
    assert signal["effective_rr"] == signal["rr_ratio"]
    assert signal["signal_mode"] == "LIVE"


def test_s16_redis_watch_state_and_trigger_queue_round_trip():
    from s16_accumulation_state import (
        ARMED_ZSET,
        STATE_ARMED,
        STRATEGY_NAME,
        S16WatchState,
        enqueue_trigger,
        load_watch_state,
        pop_trigger,
        save_watch_state,
        watch_key,
    )

    rdb = FakeRedis()
    state = S16WatchState(
        stk_cd="A005930",
        state=STATE_ARMED,
        first_seen_at=1,
        last_seen_at=2,
        observe_days=3,
        total_score=78.5,
    )
    _run(save_watch_state(rdb, state, next_check_at=10))
    loaded = _run(load_watch_state(rdb, "005930"))

    assert loaded is not None
    assert loaded.stk_cd == "005930"
    assert rdb.hashes[watch_key("005930")]["state"] == STATE_ARMED
    assert rdb.zsets[ARMED_ZSET]["005930"] == 78.5

    payload = {"stk_cd": "A005930", "strategy": "ignored", "rr_ratio": 1.8}
    assert _run(enqueue_trigger(rdb, payload, ymd="20260701")) is True
    assert _run(enqueue_trigger(rdb, payload, ymd="20260701")) is False
    popped = _run(pop_trigger(rdb))
    assert popped["stk_cd"] == "005930"
    assert popped["strategy"] == STRATEGY_NAME


def test_scan_accumulation_shadow_is_disabled_by_default():
    from strategy_16_accumulation import scan_accumulation_shadow

    rdb = FakeRedis()
    assert _run(scan_accumulation_shadow("token", rdb=rdb)) == []


def test_scan_accumulation_shadow_drains_trigger_queue_when_enabled(monkeypatch):
    import strategy_16_accumulation as s16
    from s16_accumulation_state import enqueue_trigger

    rdb = FakeRedis()
    _run(enqueue_trigger(
        rdb,
        {"stk_cd": "005930", "strategy": s16.STRATEGY_NAME, "rr_ratio": 1.8},
        ymd="20260701",
    ))
    monkeypatch.setattr(s16, "S16_ENABLED", True)

    signals = _run(s16.scan_accumulation_shadow("token", rdb=rdb))

    assert len(signals) == 1
    assert signals[0]["stk_cd"] == "005930"
