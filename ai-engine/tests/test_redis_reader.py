"""
tests/test_redis_reader.py
redis_reader.py 의 Redis 읽기/쓰기 함수 단위 테스트.
unittest.mock 으로 실제 Redis 연결 없이 테스트.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_rdb(**method_return_map):
    """비동기 Redis 모킹"""
    rdb = MagicMock()
    for method, return_value in method_return_map.items():
        setattr(rdb, method, AsyncMock(return_value=return_value))
    return rdb


# ──────────────────────────────────────────────────────────────────
# pop_telegram_queue 테스트
# ──────────────────────────────────────────────────────────────────

class TestPopTelegramQueue:
    def test_returns_parsed_dict_on_valid_json(self):
        payload = {"strategy": "S1_GAP_OPEN", "stk_cd": "005930"}
        rdb = _make_rdb(rpop=json.dumps(payload))

        from redis_reader import pop_telegram_queue
        result = _run(pop_telegram_queue(rdb))

        assert result == payload
        rdb.rpop.assert_awaited_once_with("telegram_queue")

    def test_returns_none_when_queue_empty(self):
        rdb = _make_rdb(rpop=None)

        from redis_reader import pop_telegram_queue
        result = _run(pop_telegram_queue(rdb))

        assert result is None

    def test_returns_none_on_invalid_json(self):
        rdb = _make_rdb(rpop="not-valid-json{{")

        from redis_reader import pop_telegram_queue
        result = _run(pop_telegram_queue(rdb))

        assert result is None

    def test_handles_empty_string(self):
        rdb = _make_rdb(rpop="")

        from redis_reader import pop_telegram_queue
        result = _run(pop_telegram_queue(rdb))

        # 빈 문자열은 None으로 처리
        assert result is None

    def test_deserializes_complex_payload(self):
        payload = {
            "strategy": "S2_VI_PULLBACK",
            "stk_cd": "000660",
            "pullback_pct": -1.5,
            "is_dynamic": True,
            "net_buy_amt": 10_000_000_000,
        }
        rdb = _make_rdb(rpop=json.dumps(payload, ensure_ascii=False))

        from redis_reader import pop_telegram_queue
        result = _run(pop_telegram_queue(rdb))

        assert result["pullback_pct"] == -1.5
        assert result["is_dynamic"] is True


# ──────────────────────────────────────────────────────────────────
# push_score_only_queue 테스트
# ──────────────────────────────────────────────────────────────────

class TestPushScoreOnlyQueue:
    def test_pushes_serialized_payload(self):
        rdb = _make_rdb(lpush=1, expire=True)
        payload = {"strategy": "S1_GAP_OPEN", "ai_score": 75.0, "action": "ENTER"}

        from redis_reader import push_score_only_queue
        _run(push_score_only_queue(rdb, payload))

        rdb.lpush.assert_awaited_once()
        args = rdb.lpush.call_args[0]
        assert args[0] == "ai_scored_queue"
        parsed = json.loads(args[1])
        assert parsed["ai_score"] == 75.0

    def test_sets_expire_43200(self):
        rdb = _make_rdb(lpush=1, expire=True)
        payload = {"strategy": "S1_GAP_OPEN", "ai_score": 75.0}

        from redis_reader import push_score_only_queue
        _run(push_score_only_queue(rdb, payload))

        rdb.expire.assert_awaited_once_with("ai_scored_queue", 43200)

    def test_handles_non_serializable_values(self):
        """직렬화 불가 객체 포함 시 default=str 로 처리"""
        from datetime import datetime
        rdb = _make_rdb(lpush=1, expire=True)
        payload = {"strategy": "S1_GAP_OPEN", "timestamp": datetime.now()}

        from redis_reader import push_score_only_queue
        # default=str 이 사용되어 오류 없이 처리되어야 함
        _run(push_score_only_queue(rdb, payload))
        rdb.lpush.assert_awaited_once()

    def test_serialization_error_logs_and_returns(self):
        """직렬화 완전 실패 시 (json.dumps 예외) lpush 미호출"""
        rdb = _make_rdb(lpush=1, expire=True)

        # json.dumps 가 오류를 내도록 패치
        with patch("redis_reader.json.dumps", side_effect=TypeError("unserializable")):
            from redis_reader import push_score_only_queue
            _run(push_score_only_queue(rdb, {"key": "val"}))

        rdb.lpush.assert_not_awaited()

    def test_ensure_ascii_false(self):
        """한글 등 ASCII 외 문자 포함 시 올바르게 직렬화"""
        rdb = _make_rdb(lpush=1, expire=True)
        payload = {"stk_nm": "삼성전자", "ai_reason": "강한 매수 신호"}

        from redis_reader import push_score_only_queue
        _run(push_score_only_queue(rdb, payload))

        args = rdb.lpush.call_args[0]
        assert "삼성전자" in args[1]  # ensure_ascii=False 로 한글 보존


# ──────────────────────────────────────────────────────────────────
# get_tick_data 테스트
# ──────────────────────────────────────────────────────────────────

class TestGetTickData:
    def test_returns_hash_data(self):
        expected = {"cur_prc": "50000", "flu_rt": "3.5"}
        rdb = _make_rdb(hgetall=expected)

        from redis_reader import get_tick_data
        result = _run(get_tick_data(rdb, "005930"))

        assert result == expected
        rdb.hgetall.assert_awaited_once_with("ws:tick:005930")

    def test_returns_empty_dict_when_no_data(self):
        rdb = _make_rdb(hgetall=None)

        from redis_reader import get_tick_data
        result = _run(get_tick_data(rdb, "005930"))

        assert result == {}

    def test_returns_empty_dict_when_empty_hash(self):
        rdb = _make_rdb(hgetall={})

        from redis_reader import get_tick_data
        result = _run(get_tick_data(rdb, "005930"))

        assert result == {}


# ──────────────────────────────────────────────────────────────────
# get_hoga_data 테스트
# ──────────────────────────────────────────────────────────────────

class TestGetHogaData:
    def test_returns_hoga_hash(self):
        expected = {"total_buy_bid_req": "2000", "total_sel_bid_req": "1000"}
        rdb = _make_rdb(hgetall=expected)

        from redis_reader import get_hoga_data
        result = _run(get_hoga_data(rdb, "005930"))

        assert result == expected
        rdb.hgetall.assert_awaited_once_with("ws:hoga:005930")


# ──────────────────────────────────────────────────────────────────
# get_avg_cntr_strength 테스트
# ──────────────────────────────────────────────────────────────────

class TestGetAvgCntrStrength:
    def test_returns_average_of_values(self):
        rdb = _make_rdb(lrange=["120.0", "130.0", "110.0"])

        from redis_reader import get_avg_cntr_strength
        result = _run(get_avg_cntr_strength(rdb, "005930", 3))

        assert result == pytest.approx(120.0)

    def test_returns_100_when_empty(self):
        rdb = _make_rdb(lrange=[])

        from redis_reader import get_avg_cntr_strength
        result = _run(get_avg_cntr_strength(rdb, "005930", 5))

        assert result == 100.0

    def test_returns_100_when_none(self):
        rdb = _make_rdb(lrange=None)

        from redis_reader import get_avg_cntr_strength
        result = _run(get_avg_cntr_strength(rdb, "005930", 5))

        assert result == 100.0

    def test_skips_invalid_values(self):
        """파싱 불가 값 건너뜀"""
        rdb = _make_rdb(lrange=["120.0", "invalid", "130.0"])

        from redis_reader import get_avg_cntr_strength
        result = _run(get_avg_cntr_strength(rdb, "005930", 3))

        assert result == pytest.approx(125.0)

    def test_handles_values_with_plus_sign(self):
        """+ 부호 포함 값 처리"""
        rdb = _make_rdb(lrange=["+120.0", "+130.0"])

        from redis_reader import get_avg_cntr_strength
        result = _run(get_avg_cntr_strength(rdb, "005930", 2))

        assert result == pytest.approx(125.0)

    def test_handles_comma_in_values(self):
        """쉼표 포함 값 처리"""
        rdb = _make_rdb(lrange=["1,200.0", "1,300.0"])

        from redis_reader import get_avg_cntr_strength
        result = _run(get_avg_cntr_strength(rdb, "005930", 2))

        assert result == pytest.approx(1250.0)


# ──────────────────────────────────────────────────────────────────
# get_vi_status 테스트
# ──────────────────────────────────────────────────────────────────

class TestGetViStatus:
    def test_returns_vi_hash(self):
        expected = {"vi_price": "50000", "status": "active"}
        rdb = _make_rdb(hgetall=expected)

        from redis_reader import get_vi_status
        result = _run(get_vi_status(rdb, "005930"))

        assert result == expected
        rdb.hgetall.assert_awaited_once_with("vi:005930")

    def test_returns_empty_when_no_vi(self):
        rdb = _make_rdb(hgetall={})

        from redis_reader import get_vi_status
        result = _run(get_vi_status(rdb, "005930"))

        assert result == {}


class TestMarketFreshness:
    def test_freshness_status_cancel_when_age_exceeds_cutoff(self):
        from redis_reader import freshness_status

        result = freshness_status({"updated_at_ms": "1000"}, "tick", now_ms=7001)

        assert result["state"] == "cancel"
        assert result["age_ms"] == 6001

    def test_freshness_status_missing_without_timestamp(self):
        from redis_reader import freshness_status

        result = freshness_status({"cur_prc": "50000"}, "tick", now_ms=7001)

        assert result["state"] == "missing"
        assert result["age_ms"] is None

    def test_get_market_freshness_reads_strength_meta(self):
        rdb = MagicMock()
        rdb.hgetall = AsyncMock(side_effect=[
            {"updated_at_ms": "10000"},
            {"updated_at_ms": "9500"},
            {"updated_at_ms": "4000"},
            {},
        ])

        from redis_reader import get_market_freshness
        result = _run(get_market_freshness(rdb, "005930", now_ms=10000))

        assert result["tick"]["state"] == "fresh"
        assert result["hoga"]["state"] == "fresh"
        assert result["strength"]["state"] == "caution"
        assert result["vi"]["state"] == "missing"
        assert rdb.hgetall.await_args_list[2][0][0] == "ws:strength_meta:005930"


# ──────────────────────────────────────────────────────────────────
# get_strength_with_status 테스트
# ──────────────────────────────────────────────────────────────────

import time


class TestGetStrengthWithStatus:
    @pytest.mark.asyncio
    async def test_meta_stale_returns_cancel(self):
        """strength list에 값이 있어도 meta가 stale이면 cancel 반환"""
        from redis_reader import get_strength_with_status

        now_ms = int(time.time() * 1000)
        stale_ms = str(now_ms - 15_000)  # 15초 전 → cancel (> 10,000ms)

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={"updated_at_ms": stale_ms})
        rdb.lrange = AsyncMock(return_value=["110.0", "105.0", "100.0"])

        result = await get_strength_with_status(rdb, "005930", now_ms=now_ms)

        assert result["status"]["state"] == "cancel"
        assert result["data"] is None
        assert result["source"] != "redis"
        # cancel 이므로 lrange 를 호출하지 않아야 함
        rdb.lrange.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_meta_missing_returns_missing(self):
        """meta 키 없으면 missing 반환"""
        from redis_reader import get_strength_with_status

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={})  # meta 없음
        rdb.lrange = AsyncMock(return_value=["110.0"])

        result = await get_strength_with_status(rdb, "005930")

        assert result["status"]["state"] == "missing"
        assert result["data"] is None
        rdb.lrange.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_meta_returns_average(self):
        """meta fresh이면 list 평균 반환"""
        from redis_reader import get_strength_with_status

        now_ms = int(time.time() * 1000)
        fresh_ms = str(now_ms - 500)  # 0.5초 전 → fresh

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={"updated_at_ms": fresh_ms})
        rdb.lrange = AsyncMock(return_value=["120.0", "115.0", "110.0"])

        result = await get_strength_with_status(rdb, "005930", count=3, now_ms=now_ms)

        assert result["status"]["state"] == "fresh"
        assert result["data"] == pytest.approx((120.0 + 115.0 + 110.0) / 3, rel=0.01)
        assert result["source"] == "redis"
        rdb.lrange.assert_awaited_once_with("ws:strength:005930", 0, 2)

    @pytest.mark.asyncio
    async def test_caution_meta_still_returns_data(self):
        """meta caution(5~10초)이면 경고 상태지만 data는 반환"""
        from redis_reader import get_strength_with_status

        now_ms = int(time.time() * 1000)
        caution_ms = str(now_ms - 7_000)  # 7초 전 → caution (> 5000ms, < 10000ms)

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={"updated_at_ms": caution_ms})
        rdb.lrange = AsyncMock(return_value=["100.0", "95.0"])

        result = await get_strength_with_status(rdb, "005930", now_ms=now_ms)

        assert result["status"]["state"] == "caution"
        assert result["data"] == pytest.approx(97.5, rel=0.01)
        assert result["source"] == "redis"

    @pytest.mark.asyncio
    async def test_now_ms_defaults_to_current_time(self):
        """now_ms=None 이면 현재 시각 기준으로 freshness 판정"""
        from redis_reader import get_strength_with_status

        # 방금(100ms 전) 기록된 meta → 반드시 fresh
        fresh_ms = str(int(time.time() * 1000) - 100)

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={"updated_at_ms": fresh_ms})
        rdb.lrange = AsyncMock(return_value=["105.0"])

        result = await get_strength_with_status(rdb, "005930")  # now_ms 생략

        assert result["status"]["state"] == "fresh"
        assert result["data"] == pytest.approx(105.0)
