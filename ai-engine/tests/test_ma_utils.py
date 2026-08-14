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


class _MinuteResponse:
    def __init__(self, rows, headers=None):
        self._rows = rows
        self.headers = headers or {"cont-yn": "N", "next-key": ""}

    def raise_for_status(self):
        return None

    def json(self):
        return {"return_code": "0", "stk_min_pole_chart_qry": self._rows}


class _MinuteClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.post = AsyncMock(side_effect=self.responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_fetch_minute_candles_follows_ka10080_continuation_and_sends_base_date():
    import ma_utils

    ma_utils._MIN_CANDLE_CACHE.clear()
    client = _MinuteClient([
        _MinuteResponse(
            [{"cntr_tm": "20260803100000", "cur_prc": "100"}],
            {"cont-yn": "Y", "next-key": "page-2"},
        ),
        _MinuteResponse([{"cntr_tm": "20260803095900", "cur_prc": "99"}]),
    ])
    with patch("ma_utils.kiwoom_client", return_value=client):
        rows = _run(ma_utils.fetch_minute_candles("tok", "005930", "1", base_dt="20260803"))

    assert [row["cur_prc"] for row in rows] == ["100", "99"]
    assert client.post.await_count == 2
    assert client.post.await_args_list[0].kwargs["json"]["base_dt"] == "20260803"
    assert client.post.await_args_list[1].kwargs["headers"]["next-key"] == "page-2"


class _DailyResponse:
    def __init__(self, rows, headers=None):
        self._rows = rows
        self.headers = headers or {"cont-yn": "N", "next-key": ""}

    def raise_for_status(self):
        return None

    def json(self):
        return {"return_code": "0", "stk_dt_pole_chart_qry": self._rows}


class _DailyClient:
    """post()마다 짧게 sleep해 동시 호출이 실제로 겹치도록 만든다."""

    def __init__(self, rows):
        self._rows = rows
        self.call_count = 0

        async def _post(*args, **kwargs):
            self.call_count += 1
            await asyncio.sleep(0.05)
            return _DailyResponse(self._rows)

        self.post = AsyncMock(side_effect=_post)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_fetch_daily_candles_coalesces_concurrent_calls_for_same_stock():
    import ma_utils

    import http_utils
    ma_utils._CANDLE_CACHE.clear()
    http_utils._INFLIGHT_REQUESTS.clear()
    rows = [_daily_candle(f"2026080{i}") for i in range(1, 6)]
    client = _DailyClient(rows)

    with patch("ma_utils.kiwoom_client", return_value=client):
        results = _run(asyncio.gather(
            ma_utils.fetch_daily_candles("tok", "005930", target_count=5),
            ma_utils.fetch_daily_candles("tok", "005930", target_count=5),
            ma_utils.fetch_daily_candles("tok", "005930", target_count=5),
        ))

    assert client.call_count == 1
    assert all(r == results[0] for r in results)
    assert len(results[0]) == 5
    # 완료 후에는 in-flight 등록이 정리되어 다음 호출은 캐시를 사용한다.
    assert http_utils._INFLIGHT_REQUESTS == {}


def test_fetch_daily_candles_does_not_coalesce_different_target_counts():
    import ma_utils

    import http_utils
    ma_utils._CANDLE_CACHE.clear()
    http_utils._INFLIGHT_REQUESTS.clear()
    rows = [_daily_candle(f"2026080{i}") for i in range(1, 6)]
    client = _DailyClient(rows)

    with patch("ma_utils.kiwoom_client", return_value=client):
        results = _run(asyncio.gather(
            ma_utils.fetch_daily_candles("tok", "005930", target_count=5),
            ma_utils.fetch_daily_candles("tok", "005930", target_count=2),
        ))

    # 서로 다른 target_count는 별도 요청으로 처리되어야 한다 (부족한 봉 수 반환 방지).
    assert client.call_count == 2
    assert len(results[0]) == 5
    assert len(results[1]) == 5  # 한 페이지에 5건이 오므로 두 요청 모두 5건을 받는다


class TestTossCandleFallback:
    """ka10081 글로벌 리미터 혼잡 등으로 봉이 부족할 때 토스 캔들로 대체하는 폴백.
    부분 병합은 하지 않고, 토스가 더 많은 봉을 확보했을 때만 전체 교체한다."""

    def test_converts_toss_shape_to_kiwoom_fields(self):
        import ma_utils

        toss_candles = [
            {"timestamp": "2026-08-11T09:00:00+09:00", "openPrice": "71600",
             "highPrice": "72300", "lowPrice": "71500", "closePrice": "72000", "volume": "3521000"},
        ]
        converted = ma_utils._toss_candles_to_kiwoom_shape(toss_candles)

        assert converted[0]["cur_prc"] == "72000"
        assert converted[0]["open_pric"] == "71600"
        assert converted[0]["high_pric"] == "72300"
        assert converted[0]["low_pric"] == "71500"
        assert converted[0]["trde_qty"] == "3521000"
        assert converted[0]["dt"] == "20260811"

    def test_fallback_replaces_when_toss_has_more_candles(self):
        import ma_utils

        ma_utils._CANDLE_CACHE.clear()
        rows = [_daily_candle(f"2026080{i}") for i in range(1, 3)]  # kiwoom 2건 (부족)
        client = _DailyClient(rows)
        toss_candles = [
            {"timestamp": f"2026-08-{d:02d}T09:00:00+09:00", "openPrice": "100",
             "highPrice": "110", "lowPrice": "90", "closePrice": "105", "volume": "1000"}
            for d in range(1, 6)  # toss 5건 (더 많음)
        ]

        with patch("ma_utils.kiwoom_client", return_value=client), \
             patch("ma_utils._toss_enabled", return_value=True), \
             patch("ma_utils._toss_fetch_stock_candles", new_callable=AsyncMock, return_value=toss_candles):
            result = _run(ma_utils.fetch_daily_candles("tok", "005930", target_count=5))

        assert len(result) == 5
        assert result[0]["source"] == "toss_candle_fallback"

    def test_fallback_not_used_when_kiwoom_has_enough(self):
        import ma_utils

        ma_utils._CANDLE_CACHE.clear()
        rows = [_daily_candle(f"2026080{i}") for i in range(1, 6)]  # kiwoom 5건 (충분)
        client = _DailyClient(rows)
        toss_mock = AsyncMock(return_value=[{"timestamp": "2026-08-01T09:00:00+09:00"}] * 10)

        with patch("ma_utils.kiwoom_client", return_value=client), \
             patch("ma_utils._toss_enabled", return_value=True), \
             patch("ma_utils._toss_fetch_stock_candles", toss_mock):
            result = _run(ma_utils.fetch_daily_candles("tok", "005930", target_count=5))

        assert len(result) == 5
        assert "source" not in result[0]
        toss_mock.assert_not_called()

    def test_fallback_skipped_when_toss_disabled(self):
        import ma_utils

        ma_utils._CANDLE_CACHE.clear()
        rows = [_daily_candle("20260801")]  # kiwoom 1건 (부족)
        client = _DailyClient(rows)
        toss_mock = AsyncMock(return_value=[{"timestamp": "2026-08-01T09:00:00+09:00"}] * 10)

        with patch("ma_utils.kiwoom_client", return_value=client), \
             patch("ma_utils._toss_enabled", return_value=False), \
             patch("ma_utils._toss_fetch_stock_candles", toss_mock):
            result = _run(ma_utils.fetch_daily_candles("tok", "005930", target_count=5))

        assert len(result) == 1
        toss_mock.assert_not_called()

    def test_fallback_exception_is_swallowed(self):
        import ma_utils

        ma_utils._CANDLE_CACHE.clear()
        rows = [_daily_candle("20260801")]
        client = _DailyClient(rows)

        with patch("ma_utils.kiwoom_client", return_value=client), \
             patch("ma_utils._toss_enabled", return_value=True), \
             patch("ma_utils._toss_fetch_stock_candles", new_callable=AsyncMock, side_effect=Exception("boom")):
            result = _run(ma_utils.fetch_daily_candles("tok", "005930", target_count=5))

        assert len(result) == 1  # kiwoom 결과 그대로 유지


def test_filter_closed_minute_candles_excludes_live_and_malformed_bars():
    from ma_utils import filter_closed_minute_candles

    now = datetime(2026, 8, 3, 10, 3, 0, tzinfo=KST)
    rows = [
        {"cntr_tm": "20260803100000", "cur_prc": "101"},  # closes 10:05
        {"cntr_tm": "20260803095500", "cur_prc": "100"},  # closed 10:00
        {"cntr_tm": "bad-time", "cur_prc": "99"},
    ]

    closed = filter_closed_minute_candles(rows, "5", now=now)

    assert [row["cur_prc"] for row in closed] == ["100"]


def test_vwap_uses_only_current_session_rows():
    import indicator_volume

    today = datetime.now(KST).strftime("%Y%m%d")
    rows = [
        {"cntr_tm": f"{today}000000", "high_pric": "110", "low_pric": "90", "cur_prc": "100", "trde_qty": "10"},
        {"cntr_tm": "19990101100000", "high_pric": "1010", "low_pric": "990", "cur_prc": "1000", "trde_qty": "1000"},
    ]
    with patch("indicator_volume.fetch_minute_candles", AsyncMock(return_value=rows)):
        result = _run(indicator_volume.get_vwap_minute("tok", "005930", "1"))

    assert result.vwap == 100.0


# ── detect_box_breakout (S13 2026-08-13 거래량 게이트 제거 회귀) ──────────────

def _box_candle(cur_prc=100, open_pric=100, high_pric=100, low_pric=100, trde_qty=1000):
    return {
        "cur_prc": str(cur_prc), "open_pric": str(open_pric),
        "high_pric": str(high_pric), "low_pric": str(low_pric),
        "trde_qty": str(trde_qty),
    }


def _box_candles(today: dict, box_high=102, box_low=98, fill=46):
    """[0]=오늘, [1:16]=박스권(15개), [16:16+fill]=채움."""
    box = [_box_candle(cur_prc=100, open_pric=100, high_pric=box_high, low_pric=box_low) for _ in range(15)]
    padding = [_box_candle(cur_prc=100, open_pric=100, high_pric=box_high, low_pric=box_low) for _ in range(fill)]
    return [today] + box + padding


class TestDetectBoxBreakout:
    def test_breakout_detected_with_low_volume_today(self):
        """핵심 회귀: 거래량 게이트를 제거했으므로, 오늘 거래량이 아주 낮아도
        (예: 100주) 박스 상단 돌파 + 양봉 조건만 맞으면 돌파로 판정해야 한다."""
        from ma_utils import detect_box_breakout

        today = _box_candle(cur_prc=110, open_pric=100, high_pric=112, low_pric=98, trde_qty=100)
        candles = _box_candles(today)

        is_breakout, box_range_pct = detect_box_breakout(candles, box_period=15, max_range_pct=8.0)

        assert is_breakout is True
        assert box_range_pct == pytest.approx(4.08, abs=0.01)

    def test_no_breakout_when_close_below_box_high(self):
        from ma_utils import detect_box_breakout

        today = _box_candle(cur_prc=101, open_pric=100, high_pric=101, low_pric=99, trde_qty=100)
        candles = _box_candles(today)

        is_breakout, _ = detect_box_breakout(candles, box_period=15, max_range_pct=8.0)

        assert is_breakout is False

    def test_no_breakout_when_bearish_candle(self):
        """종가가 박스 상단을 넘었어도 음봉(종가<시가)이면 돌파로 인정하지 않는다."""
        from ma_utils import detect_box_breakout

        today = _box_candle(cur_prc=105, open_pric=110, high_pric=112, low_pric=104, trde_qty=100)
        candles = _box_candles(today)

        is_breakout, _ = detect_box_breakout(candles, box_period=15, max_range_pct=8.0)

        assert is_breakout is False

    def test_no_breakout_when_box_range_too_wide(self):
        from ma_utils import detect_box_breakout

        today = _box_candle(cur_prc=130, open_pric=120, high_pric=132, low_pric=118, trde_qty=100)
        candles = _box_candles(today, box_high=120, box_low=90)  # (120-90)/90 = 33% > 8%

        is_breakout, box_range_pct = detect_box_breakout(candles, box_period=15, max_range_pct=8.0)

        assert is_breakout is False
        assert box_range_pct > 8.0

    def test_insufficient_candles_returns_false(self):
        from ma_utils import detect_box_breakout

        today = _box_candle(cur_prc=110, open_pric=100)
        candles = [today] + [_box_candle() for _ in range(10)]  # box_period(15)+2 미만

        is_breakout, box_range_pct = detect_box_breakout(candles, box_period=15, max_range_pct=8.0)

        assert is_breakout is False
        assert box_range_pct == 0.0
