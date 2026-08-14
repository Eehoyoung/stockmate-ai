"""
tests/test_indicator_macd.py
indicator_macd.py 순수 계산(calc_ema, calc_macd) 및 _build_macd_result 배선 테스트.
"""
from __future__ import annotations


def _candle(cur_prc: float) -> dict:
    return {"cur_prc": str(cur_prc)}


class TestCalcEma:
    def test_insufficient_data_returns_zero_filled_list(self):
        from indicator_macd import calc_ema

        prices = [100.0, 101.0]
        assert calc_ema(prices, period=12) == [0.0, 0.0]

    def test_ema_of_constant_series_equals_constant(self):
        from indicator_macd import calc_ema

        prices = [100.0] * 30
        ema = calc_ema(prices, period=12)
        assert ema[0] == 100.0

    def test_ema_tracks_rising_trend(self):
        from indicator_macd import calc_ema

        # newest-first: index 0이 가장 최근(가장 높음)
        prices = [float(200 - i) for i in range(40)]
        ema = calc_ema(prices, period=12)
        # 최근 EMA는 최근 관측치 근처(더 낮은 과거 평균보다 높아야 함)
        assert ema[0] > ema[20]


class TestCalcMacd:
    def test_insufficient_data_returns_zero_filled_lists(self):
        from indicator_macd import calc_macd

        closes = [100.0, 101.0, 102.0]
        macd_line, signal_line, hist = calc_macd(closes, fast=12, slow=26, signal_span=9)
        assert macd_line == [0.0, 0.0, 0.0]
        assert signal_line == [0.0, 0.0, 0.0]
        assert hist == [0.0, 0.0, 0.0]

    def test_histogram_equals_macd_minus_signal(self):
        from indicator_macd import calc_macd

        closes = [float(100 + (i % 7) * 3) for i in range(60)]
        macd_line, signal_line, hist = calc_macd(closes)
        for m, s, h in zip(macd_line[:20], signal_line[:20], hist[:20]):
            if m != 0.0 and s != 0.0:
                assert h == m - s

    def test_uptrend_yields_positive_macd(self):
        from indicator_macd import calc_macd

        closes = [float(100 + i) for i in range(60)]  # 최신이 가장 큼(index 0=최근)
        closes = list(reversed(closes))  # 이제 index0=가장 최근=가장 큼(상승추세)
        macd_line, _, _ = calc_macd(closes)
        assert macd_line[0] > 0.0


class TestBuildMacdResult:
    def test_insufficient_candles_returns_none(self):
        from indicator_macd import _build_macd_result

        candles = [_candle(100 + i) for i in range(10)]
        result = _build_macd_result("005930", candles, fast=12, slow=26, signal_span=9)
        assert result.macd is None
        assert result.signal is None
        assert result.histogram is None

    def test_sufficient_candles_populate_result(self):
        from indicator_macd import _build_macd_result

        closes_chrono = [float(100 + i) for i in range(60)]
        candles = [_candle(c) for c in reversed(closes_chrono)]
        result = _build_macd_result("005930", candles, fast=12, slow=26, signal_span=9)
        assert result.macd is not None
        assert result.signal is not None
        assert result.histogram is not None
        assert result.is_above_zero is True


class TestMacdResultCrossProperties:
    def test_is_golden_cross(self):
        from indicator_macd import MACDResult

        r = MACDResult(macd=1.0, signal=0.5, macd_prev=0.4, signal_prev=0.5)
        assert r.is_golden_cross() is True

    def test_is_dead_cross(self):
        from indicator_macd import MACDResult

        r = MACDResult(macd=0.4, signal=0.5, macd_prev=0.6, signal_prev=0.5)
        assert r.is_dead_cross() is True

    def test_cross_false_when_missing_data(self):
        from indicator_macd import MACDResult

        r = MACDResult(macd=1.0, signal=None, macd_prev=0.4, signal_prev=0.5)
        assert r.is_golden_cross() is False
        assert r.is_dead_cross() is False
