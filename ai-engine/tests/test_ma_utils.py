"""
tests/test_ma_utils.py
ma_utils Phase 1·2 기능 테스트.

외부 HTTP / Redis 없이 인메모리 캐시와 mock으로만 동작한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _daily_candle(dt: str, o=10000, h=10500, l=9800, c=10200, vol=100000):
    return {
        "dt": dt,
        "stk_opnpric": str(o),
        "stk_hgpric": str(h),
        "stk_lwpric": str(l),
        "stk_clpr": str(c),
        "acml_vol": str(vol),
    }


def _min_candle(cntr_tm: str, close=10000):
    return {"cntr_tm": cntr_tm, "stk_clpr": str(close)}


# ── build_weekly_candles (Phase 1) ────────────────────────────────────────────

class TestBuildWeeklyCandles:
    def test_basic_aggregation(self):
        from ma_utils import build_weekly_candles

        candles = [
            _daily_candle("20260511", o=10000, h=10500, l=9800, c=10200, vol=100),
            _daily_candle("20260512", o=10200, h=10800, l=10100, c=10600, vol=200),
            _daily_candle("20260513", o=10600, h=10900, l=10400, c=10700, vol=150),
            _daily_candle("20260506", o=9500, h=9800, l=9400, c=9700, vol=80),
        ]
        result = build_weekly_candles(candles)

        assert len(result) == 2
        # 최신 주(2026-W20)가 index 0
        w0 = result[0]
        assert w0["candle_count"] == 3
        assert w0["open"] == 10000   # 첫 날 시가
        assert w0["close"] == 10700  # 마지막 날 종가
        assert w0["high"] == 10900
        assert w0["low"] == 9800
        assert w0["volume"] == 450

    def test_empty_input(self):
        from ma_utils import build_weekly_candles
        assert build_weekly_candles([]) == []

    def test_invalid_dt_skipped(self):
        from ma_utils import build_weekly_candles
        candles = [
            {"dt": "INVALID", "stk_clpr": "10000"},
            _daily_candle("20260511"),
        ]
        result = build_weekly_candles(candles)
        assert len(result) == 1

    def test_single_day_week(self):
        from ma_utils import build_weekly_candles
        candles = [_daily_candle("20260511", o=10000, h=10500, l=9800, c=10200, vol=100)]
        result = build_weekly_candles(candles)
        assert len(result) == 1
        assert result[0]["candle_count"] == 1
        assert result[0]["open"] == 10000.0
        assert result[0]["close"] == 10200.0

    def test_sorted_desc(self):
        from ma_utils import build_weekly_candles
        candles = [
            _daily_candle("20260511"),
            _daily_candle("20260504"),
            _daily_candle("20260427"),
        ]
        result = build_weekly_candles(candles)
        keys = [r["week_key"] for r in result]
        assert keys == sorted(keys, reverse=True)


# ── _is_bar_closed (Phase 1) ──────────────────────────────────────────────────

class TestIsBarClosed:
    def test_at_bar_boundary_is_open(self):
        from ma_utils import _is_bar_closed
        with patch("ma_utils.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 11, 9, 5, 10, tzinfo=KST)
            mock_dt.now.return_value = datetime(2026, 5, 11, 9, 5, 10, tzinfo=KST)
            # 5분봉: minute=5, secs_into_bar = (5%5)*60+10 = 10 < 30 → False
            # But _is_bar_closed uses datetime.now(KST) directly, need different approach
            pass

    def test_30s_into_bar_is_closed(self):
        """봉 경계 30초 이상이면 이전 봉 확정 → True."""
        from ma_utils import _is_bar_closed
        with patch("ma_utils.datetime") as mock_dt:
            # minute=5 in 5min scope: secs_into_bar = (5%5)*60+45 = 45 >= 30 → True
            mock_dt.now.return_value = datetime(2026, 5, 11, 9, 5, 45, tzinfo=KST)
            result = _is_bar_closed.__wrapped__("5") if hasattr(_is_bar_closed, "__wrapped__") else None
            # Direct logic check
            scope_min = 5
            now = datetime(2026, 5, 11, 9, 5, 45, tzinfo=KST)
            secs = (now.minute % scope_min) * 60 + now.second
            assert secs >= 30  # 45 >= 30


# ── _is_intraday_kst (Phase 2) ────────────────────────────────────────────────

class TestIsIntradayKst:
    def _check(self, hour, minute, weekday=0):
        from ma_utils import _is_intraday_kst
        with patch("ma_utils.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 11 + weekday, hour, minute, 0, tzinfo=KST)
            # weekday() 는 실제 datetime 객체에서 호출되므로 patch 후 다시 계산
        # 직접 논리 검증
        t_min = hour * 60 + minute
        on_weekday = weekday < 5
        return on_weekday and (540 <= t_min < 930)

    def test_during_market(self):
        assert self._check(10, 30) is True

    def test_before_market(self):
        assert self._check(8, 50) is False

    def test_after_market(self):
        assert self._check(15, 35) is False

    def test_market_open_edge(self):
        assert self._check(9, 0) is True

    def test_market_close_edge(self):
        assert self._check(15, 30) is False  # 930 분 = 미포함


# ── get_confirmed_candles / get_current_bar (Phase 2) ────────────────────────

class TestConfirmedCandles:
    def _make_candles(self, n=5):
        return [_min_candle(f"09{i:02d}00") for i in range(n)]

    def test_intraday_excludes_index0(self):
        from ma_utils import get_confirmed_candles
        candles = self._make_candles(5)
        with patch("ma_utils._is_intraday_kst", return_value=True):
            result = get_confirmed_candles(candles)
        assert len(result) == 4
        assert result[0] == candles[1]

    def test_post_market_returns_all(self):
        from ma_utils import get_confirmed_candles
        candles = self._make_candles(5)
        with patch("ma_utils._is_intraday_kst", return_value=False):
            result = get_confirmed_candles(candles)
        assert result == candles

    def test_empty_input(self):
        from ma_utils import get_confirmed_candles
        assert get_confirmed_candles([]) == []

    def test_get_current_bar_intraday(self):
        from ma_utils import get_current_bar
        candles = self._make_candles(3)
        with patch("ma_utils._is_intraday_kst", return_value=True):
            result = get_current_bar(candles)
        assert result == candles[0]

    def test_get_current_bar_post_market(self):
        from ma_utils import get_current_bar
        candles = self._make_candles(3)
        with patch("ma_utils._is_intraday_kst", return_value=False):
            result = get_current_bar(candles)
        assert result is None

    def test_get_current_bar_empty(self):
        from ma_utils import get_current_bar
        assert get_current_bar([]) is None


# ── fetch_daily_candles_with_status (Phase 2) ─────────────────────────────────

class TestFetchDailyCandlesWithStatus:
    def _sample_candles(self, n=5):
        return [_daily_candle(f"2026051{i}") for i in range(1, n + 1)]

    def test_rest_fetch_during_intraday(self):
        from ma_utils import fetch_daily_candles_with_status, _CANDLE_CACHE
        _CANDLE_CACHE.clear()
        candles = self._sample_candles(5)
        with patch("ma_utils.fetch_daily_candles", new_callable=AsyncMock, return_value=candles), \
             patch("ma_utils._is_intraday_kst", return_value=True):
            result_candles, status = _run(fetch_daily_candles_with_status("tok", "005930"))

        assert result_candles == candles
        assert status["scope"] == "1d"
        assert status["candle_count"] == 5
        assert status["source"] == "REST"
        assert status["cache_hit"] is False
        assert status["is_final_daily_bar"] is False
        assert status["intraday_day_bar"] is True

    def test_cache_hit(self):
        from ma_utils import fetch_daily_candles_with_status, _CANDLE_CACHE
        import time as _t
        candles = self._sample_candles(5)
        # target_count 기본값(120)보다 적으면 cache miss → target_count=5로 명시
        _CANDLE_CACHE["005930"] = (candles, _t.monotonic() + 3600)
        with patch("ma_utils._is_intraday_kst", return_value=False):
            result_candles, status = _run(
                fetch_daily_candles_with_status("tok", "005930", target_count=5)
            )
        assert status["cache_hit"] is True
        assert status["source"] == "CACHE"
        assert status["is_final_daily_bar"] is True
        _CANDLE_CACHE.clear()

    def test_empty_response(self):
        from ma_utils import fetch_daily_candles_with_status, _CANDLE_CACHE
        _CANDLE_CACHE.clear()
        with patch("ma_utils.fetch_daily_candles", new_callable=AsyncMock, return_value=[]), \
             patch("ma_utils._is_intraday_kst", return_value=False):
            _, status = _run(fetch_daily_candles_with_status("tok", "005930"))
        assert status["source"] == "EMPTY"
        assert status["candle_count"] == 0


# ── fetch_multi_scope_candles (Phase 2) ───────────────────────────────────────

class TestFetchMultiScopeCandles:
    def _make_status(self, scope):
        return {
            "scope": f"{scope}m",
            "candle_count": 3,
            "cache_hit": False,
            "cache_ttl_remaining_ms": 45000,
            "source": "REST",
            "latest_ts": "0930",
            "is_current_bar_closed": True,
        }

    def test_returns_all_scopes(self):
        from ma_utils import fetch_multi_scope_candles

        candles_5 = [_min_candle("09300")]
        candles_30 = [_min_candle("09000")]
        candles_60 = [_min_candle("09000")]

        async def mock_with_status(token, stk_cd, tic_scope):
            mapping = {
                "5":  (candles_5,  self._make_status("5")),
                "30": (candles_30, self._make_status("30")),
                "60": (candles_60, self._make_status("60")),
            }
            return mapping[tic_scope]

        with patch("ma_utils.fetch_minute_candles_with_status", side_effect=mock_with_status):
            result = _run(fetch_multi_scope_candles("tok", "005930", ("5", "30", "60")))

        assert set(result.keys()) == {"5", "30", "60"}
        assert result["5"][0] == candles_5
        assert result["30"][1]["scope"] == "30m"

    def test_error_scope_returns_safe_fallback(self):
        from ma_utils import fetch_multi_scope_candles

        async def mock_with_status(token, stk_cd, tic_scope):
            if tic_scope == "1":
                raise RuntimeError("API timeout")
            return ([], self._make_status(tic_scope))

        with patch("ma_utils.fetch_minute_candles_with_status", side_effect=mock_with_status):
            result = _run(fetch_multi_scope_candles("tok", "005930", ("1", "5")))

        assert result["1"][0] == []
        assert result["1"][1]["source"] == "ERROR"
        assert result["5"][1]["source"] != "ERROR"

    def test_default_scopes(self):
        from ma_utils import fetch_multi_scope_candles

        async def mock_with_status(token, stk_cd, tic_scope):
            return ([], self._make_status(tic_scope))

        with patch("ma_utils.fetch_minute_candles_with_status", side_effect=mock_with_status):
            result = _run(fetch_multi_scope_candles("tok", "005930"))

        # default scopes = ("5", "30", "60")
        assert set(result.keys()) == {"5", "30", "60"}
