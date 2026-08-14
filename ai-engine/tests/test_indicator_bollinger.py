"""
tests/test_indicator_bollinger.py
indicator_bollinger.py 순수 계산(calc_bollinger) 및 _build_bollinger_result 배선 테스트.
"""
from __future__ import annotations


def _candle(cur_prc: float) -> dict:
    return {"cur_prc": str(cur_prc)}


class TestCalcBollinger:
    def test_insufficient_data_returns_zero_tuples(self):
        from indicator_bollinger import calc_bollinger

        closes = [100.0, 101.0]
        bands = calc_bollinger(closes, period=20, num_std=2.0)
        assert bands == [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]

    def test_constant_series_has_zero_width_band(self):
        from indicator_bollinger import calc_bollinger

        closes = [100.0] * 25
        bands = calc_bollinger(closes, period=20, num_std=2.0)
        upper, middle, lower = bands[0]
        assert middle == 100.0
        assert upper == 100.0
        assert lower == 100.0

    def test_upper_gte_middle_gte_lower(self):
        from indicator_bollinger import calc_bollinger

        closes = [float(100 + (i % 5) * 7) for i in range(30)]
        bands = calc_bollinger(closes, period=20, num_std=2.0)
        for upper, middle, lower in bands[:10]:
            assert upper >= middle >= lower


class TestBuildBollingerResult:
    def test_insufficient_candles_returns_none(self):
        from indicator_bollinger import _build_bollinger_result

        candles = [_candle(100 + i) for i in range(5)]
        result = _build_bollinger_result("005930", candles, period=20, num_std=2.0)
        assert result.upper is None
        assert result.bandwidth is None

    def test_sufficient_candles_populate_bandwidth_and_pct_b(self):
        from indicator_bollinger import _build_bollinger_result

        closes = [float(100 + (i % 5) * 7) for i in range(30)]
        candles = [_candle(c) for c in closes]
        result = _build_bollinger_result("005930", candles, period=20, num_std=2.0)
        assert result.upper is not None
        assert result.bandwidth is not None
        assert result.pct_b is not None


class TestBollingerResultProperties:
    def test_is_above_upper(self):
        from indicator_bollinger import BollingerResult

        r = BollingerResult(cur_prc=110.0, upper=105.0, lower=95.0)
        assert r.is_above_upper is True
        assert r.is_below_lower is False

    def test_pct_b_near_lower_and_upper(self):
        from indicator_bollinger import BollingerResult

        near_lower = BollingerResult(pct_b=0.1)
        assert near_lower.is_near_lower is True
        assert near_lower.is_near_upper is False

        near_upper = BollingerResult(pct_b=0.9)
        assert near_upper.is_near_upper is True

    def test_is_squeeze(self):
        from indicator_bollinger import BollingerResult

        r = BollingerResult(bandwidth=3.0)
        assert r.is_squeeze is True
