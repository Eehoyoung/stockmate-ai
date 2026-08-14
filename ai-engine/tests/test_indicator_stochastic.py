"""
tests/test_indicator_stochastic.py
indicator_stochastic.py 순수 계산(calc_stochastic) 및 _build_stoch_result 배선 테스트.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _falling_then_flat_bottom_series(n_flat: int = 3):
    """시간순 하락 후 최근 n_flat봉 완전 평탄(저점 고정) -> 최신 Raw %K = 0."""
    chrono = list(range(200, 104, -5)) + [100] * n_flat  # 오래된->최근
    closes = list(reversed(chrono))  # 최신순
    highs = [c + 10 for c in closes]
    lows = [c for c in closes]
    return highs, lows, closes


def _rising_then_flat_top_series(n_flat: int = 3):
    """시간순 상승 후 최근 n_flat봉 완전 평탄(고점 고정) -> 최신 Raw %K = 100."""
    chrono = list(range(100, 196, 5)) + [200] * n_flat
    closes = list(reversed(chrono))
    highs = [c for c in closes]
    lows = [c - 10 for c in closes]
    return highs, lows, closes


def _candle(cur_prc: float, high: float, low: float) -> dict:
    return {"cur_prc": str(cur_prc), "high_pric": str(high), "low_pric": str(low)}


class TestCalcStochastic:
    def test_insufficient_data_returns_zero_filled_lists(self):
        from indicator_stochastic import calc_stochastic

        highs = [105.0, 104.0, 103.0]
        lows = [95.0, 94.0, 93.0]
        closes = [100.0, 99.0, 98.0]
        slow_k, slow_d = calc_stochastic(highs, lows, closes, 14, 3, 3)
        assert slow_k == [0.0, 0.0, 0.0]
        assert slow_d == [0.0, 0.0, 0.0]

    def test_close_at_period_low_yields_k_zero(self):
        """최근 슬로잉 구간이 기간 최저가에 고정되면 Slow %K = 0."""
        from indicator_stochastic import calc_stochastic

        highs, lows, closes = _falling_then_flat_bottom_series()
        slow_k, _ = calc_stochastic(highs, lows, closes, 14, 3, 3)
        assert slow_k[0] == 0.0

    def test_close_at_period_high_yields_k_hundred(self):
        from indicator_stochastic import calc_stochastic

        highs, lows, closes = _rising_then_flat_top_series()
        slow_k, _ = calc_stochastic(highs, lows, closes, 14, 3, 3)
        assert slow_k[0] == 100.0

    def test_k_and_d_bounded_between_0_and_100(self):
        from indicator_stochastic import calc_stochastic

        closes = [100.0, 105.0, 98.0, 110.0, 95.0, 120.0, 90.0, 130.0,
                  85.0, 140.0, 80.0, 150.0, 75.0, 160.0, 70.0, 170.0,
                  65.0, 180.0, 60.0, 190.0]
        highs = [c + 3 for c in closes]
        lows = [c - 3 for c in closes]
        slow_k, slow_d = calc_stochastic(highs, lows, closes, 14, 3, 3)
        for v in slow_k + slow_d:
            assert 0.0 <= v <= 100.0


class TestBuildStochResult:
    """_build_stoch_result: 2026-08-06 수정된 0.0/None 센티널 충돌 회귀 테스트.

    min_req = k_period+slowing+d_period 를 통과하면 index 0/1은 항상 실제
    계산값이므로, 진짜 %K=0.0(기간 최안값 마감)을 None으로 뭉개면 안 된다.
    """

    def test_genuine_k_zero_is_not_nulled_out(self):
        from indicator_stochastic import _build_stoch_result

        highs, lows, closes = _falling_then_flat_bottom_series()
        candles = [_candle(c, h, l) for c, h, l in zip(closes, highs, lows)]
        result = _build_stoch_result("005930", candles, k_period=14,
                                      d_period=3, slowing=3)
        assert result.k == 0.0
        assert result.k is not None
        assert result.is_oversold is True

    def test_genuine_k_hundred_is_preserved(self):
        from indicator_stochastic import _build_stoch_result

        highs, lows, closes = _rising_then_flat_top_series()
        candles = [_candle(c, h, l) for c, h, l in zip(closes, highs, lows)]
        result = _build_stoch_result("005930", candles, k_period=14,
                                      d_period=3, slowing=3)
        assert result.k == 100.0
        assert result.is_overbought is True

    def test_insufficient_candles_returns_none(self):
        from indicator_stochastic import _build_stoch_result

        candles = [_candle(100 + i, 102 + i, 98 + i) for i in range(5)]
        result = _build_stoch_result("005930", candles, k_period=14,
                                      d_period=3, slowing=3)
        assert result.k is None
        assert result.d is None


class TestGetStochasticDaily:
    """2026-08-06: claude_analyst.py의 일봉 지표 번들에 배선되며 재도입됨."""

    def test_wires_fetch_daily_candles_into_build_result(self):
        from indicator_stochastic import get_stochastic_daily

        highs, lows, closes = _rising_then_flat_top_series()
        candles = [_candle(c, h, l) for c, h, l in zip(closes, highs, lows)]

        with patch("indicator_stochastic.fetch_daily_candles",
                   new=AsyncMock(return_value=candles)):
            result = _run(get_stochastic_daily("token", "005930"))

        assert result.k == 100.0
