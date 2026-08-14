"""
tests/test_indicator_ichimoku.py
indicator_ichimoku.py 순수 계산(calc_ichimoku) 테스트.
"""
from __future__ import annotations


class TestCalcIchimoku:
    def test_insufficient_data_returns_none(self):
        from indicator_ichimoku import calc_ichimoku

        closes = [100.0] * 50  # 78봉 미달
        result = calc_ichimoku(closes, closes, closes)
        assert result is None

    def test_flat_series_yields_flat_bullish_cloud_and_no_thickness(self):
        from indicator_ichimoku import calc_ichimoku

        n = 100
        flat = [100.0] * n
        result = calc_ichimoku(flat, flat, flat)
        assert result is not None
        assert result.tenkan == 100.0
        assert result.kijun == 100.0
        assert result.cloud_top == 100.0
        assert result.cloud_bottom == 100.0
        assert result.cloud_thickness_pct == 0.0
        assert result.price_above_cloud is False  # cur_prc(100) > cloud_top(100) 아님

    def test_strong_uptrend_yields_price_above_cloud_and_bullish_signals(self):
        from indicator_ichimoku import calc_ichimoku

        n = 100
        # newest-first: index 0이 가장 최근(가장 높음) -> 시간순 계속 상승
        highs = [float(500 - i) for i in range(n)]
        lows = [h - 5 for h in highs]
        closes = [h - 2 for h in highs]

        result = calc_ichimoku(highs, lows, closes)
        assert result is not None
        assert result.price_above_cloud is True
        assert result.tenkan_above_kijun is True
        assert result.kijun_rising is True

    def test_cloud_top_is_max_of_span_a_and_span_b(self):
        from indicator_ichimoku import calc_ichimoku

        n = 100
        highs = [float(300 + (i % 10) * 5) for i in range(n)]
        lows = [h - 20 for h in highs]
        closes = [h - 10 for h in highs]
        result = calc_ichimoku(highs, lows, closes)
        assert result is not None
        assert result.cloud_top == max(result.span_a, result.span_b)
        assert result.cloud_bottom == min(result.span_a, result.span_b)
        assert result.is_bullish_cloud == (result.span_a > result.span_b)

    def test_malformed_input_returns_none_instead_of_raising(self):
        from indicator_ichimoku import calc_ichimoku

        # highs/lows 길이가 closes보다 짧아 내부 인덱싱에서 예외가 나야 하는 상황
        closes = [100.0] * 100
        highs = [105.0] * 60
        lows = [95.0] * 60
        result = calc_ichimoku(highs, lows, closes)
        assert result is None
