"""
tests/test_indicator_rsi.py
indicator_rsi.py 순수 계산(calc_rsi) 및 _build_rsi_result 배선 테스트.
"""
from __future__ import annotations


def _candle(cur_prc: float) -> dict:
    return {"cur_prc": str(cur_prc)}


class TestCalcRsi:
    def test_insufficient_data_returns_zero_filled_list_of_same_length(self):
        from indicator_rsi import calc_rsi

        closes = [100.0, 101.0, 102.0]  # period=14 requires 15+
        result = calc_rsi(closes, period=14)
        assert result == [0.0, 0.0, 0.0]

    def test_monotonic_decline_yields_rsi_zero_at_latest_bar(self):
        """가장 최근 봉까지 계속 하락(상승일 0회)하면 avg_gain=0 -> RSI=0.0."""
        from indicator_rsi import calc_rsi

        # newest-first: index 0=100(가장 낮음) ... index 15=115(가장 오래됨, 가장 높음)
        # => 시간순(오래된->최근)으로는 115 -> 100 까지 계속 하락.
        closes = [float(100 + i) for i in range(16)]
        rsi_vals = calc_rsi(closes, period=14)
        assert rsi_vals[0] == 0.0

    def test_monotonic_rise_yields_rsi_hundred_at_latest_bar(self):
        """계속 상승(하락일 0회)하면 avg_loss=0 -> RSI=100.0."""
        from indicator_rsi import calc_rsi

        # newest-first: index 0=115(가장 높음) ... index 15=100(가장 오래됨, 가장 낮음)
        closes = [float(115 - i) for i in range(16)]
        rsi_vals = calc_rsi(closes, period=14)
        assert rsi_vals[0] == 100.0

    def test_rsi_bounded_between_0_and_100(self):
        from indicator_rsi import calc_rsi

        closes = [100.0, 105.0, 98.0, 110.0, 95.0, 120.0, 90.0, 130.0,
                  85.0, 140.0, 80.0, 150.0, 75.0, 160.0, 70.0, 170.0, 65.0]
        rsi_vals = calc_rsi(closes, period=14)
        for v in rsi_vals:
            assert 0.0 <= v <= 100.0


class TestBuildRsiResult:
    """_build_rsi_result: 2026-08-06 수정된 0.0/None 센티널 충돌 회귀 테스트.

    length guard(len(closes) >= period+2)를 통과하면 index 0/1은 항상
    calc_rsi()의 실제 계산값이며, calc_rsi() 내부의 '데이터부족=0.0' 센티널은
    최신 index(0/1)에는 절대 등장할 수 없다. 따라서 진짜 RSI=0.0(완전
    과매도)을 None으로 뭉개면 안 된다.
    """

    def test_genuine_rsi_zero_is_not_nulled_out(self):
        from indicator_rsi import _build_rsi_result

        candles = [_candle(100 + i) for i in range(16)]  # 최신까지 계속 하락
        result = _build_rsi_result("005930", candles, period=14)
        assert result.rsi == 0.0
        assert result.rsi is not None
        assert result.is_oversold is True

    def test_genuine_rsi_hundred_is_preserved(self):
        from indicator_rsi import _build_rsi_result

        candles = [_candle(115 - i) for i in range(16)]  # 최신까지 계속 상승
        result = _build_rsi_result("005930", candles, period=14)
        assert result.rsi == 100.0
        assert result.is_overbought is True

    def test_insufficient_candles_returns_none(self):
        from indicator_rsi import _build_rsi_result

        candles = [_candle(100 + i) for i in range(5)]  # period+2=16 미달
        result = _build_rsi_result("005930", candles, period=14)
        assert result.rsi is None
        assert result.rsi_prev is None

    def test_rsi_prev_is_populated_when_available(self):
        from indicator_rsi import _build_rsi_result

        candles = [_candle(100 + i) for i in range(17)]
        result = _build_rsi_result("005930", candles, period=14)
        assert result.rsi is not None
        assert result.rsi_prev is not None


class TestRsiResultTurningProperties:
    def test_is_turning_up_requires_prior_oversold(self):
        from indicator_rsi import RSIResult

        r = RSIResult(rsi=35.0, rsi_prev=25.0)
        assert r.is_turning_up() is True

        r2 = RSIResult(rsi=35.0, rsi_prev=40.0)
        assert r2.is_turning_up() is False

    def test_is_turning_down_requires_prior_overbought(self):
        from indicator_rsi import RSIResult

        r = RSIResult(rsi=65.0, rsi_prev=75.0)
        assert r.is_turning_down() is True
