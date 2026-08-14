"""
tests/test_indicator_atr.py
indicator_atr.py 순수 계산(calc_atr, calc_williams_r) 및 _build_atr_result 배선 테스트.
"""
from __future__ import annotations


def _flat_candle(price: float) -> dict:
    return {"cur_prc": str(price), "high_pric": str(price), "low_pric": str(price)}


class TestCalcAtr:
    def test_insufficient_data_returns_zero_filled_list(self):
        from indicator_atr import calc_atr

        closes = [100.0, 101.0, 102.0]
        atr = calc_atr(closes, closes, closes, period=14)
        assert atr == [0.0, 0.0, 0.0]

    def test_completely_flat_series_yields_atr_zero(self):
        """high=low=close 전부 동일(완전 정체) -> TR=0 항상 -> ATR=0.0."""
        from indicator_atr import calc_atr

        n = 20
        flat = [10000.0] * n
        atr = calc_atr(flat, flat, flat, period=14)
        assert atr[0] == 0.0

    def test_atr_positive_when_range_exists(self):
        from indicator_atr import calc_atr

        n = 20
        closes = [10000.0 + (i % 3) * 50 for i in range(n)]
        highs = [c + 100 for c in closes]
        lows = [c - 100 for c in closes]
        atr = calc_atr(highs, lows, closes, period=14)
        assert atr[0] > 0.0


class TestCalcWilliamsR:
    def test_bounded_between_minus_100_and_0(self):
        from indicator_atr import calc_williams_r

        closes = [100.0, 105.0, 98.0, 110.0, 95.0, 120.0, 90.0, 130.0,
                  85.0, 140.0, 80.0, 150.0, 75.0, 160.0]
        highs = [c + 3 for c in closes]
        lows = [c - 3 for c in closes]
        wr = calc_williams_r(highs, lows, closes, period=14)
        for v in wr:
            if v != 0.0:  # 0.0=데이터부족 구간
                assert -100.0 <= v <= 0.0


class TestBuildAtrResult:
    """_build_atr_result: 2026-08-06 수정된 0.0/None 센티널 충돌 회귀 테스트.

    len(closes) >= period+1을 통과하면 index 0은 항상 실제 계산값이므로,
    완전 정체(ATR=0.0) 상황을 None으로 뭉개면 안 된다.
    """

    def test_genuine_atr_zero_is_not_nulled_out(self):
        from indicator_atr import _build_atr_result

        candles = [_flat_candle(10000.0) for _ in range(20)]
        result = _build_atr_result("005930", candles, period=14)
        assert result.atr == 0.0
        assert result.atr is not None
        # atr_pct도 0.0/None truthy 버그 없이 정상 계산되어야 함(0.0, not None)
        assert result.atr_pct == 0.0

    def test_insufficient_candles_returns_none(self):
        from indicator_atr import _build_atr_result

        candles = [_flat_candle(10000.0 + i) for i in range(5)]
        result = _build_atr_result("005930", candles, period=14)
        assert result.atr is None
        assert result.atr_pct is None

    def test_stop_loss_and_target_price_use_atr(self):
        from indicator_atr import ATRResult

        r = ATRResult(atr=100.0, cur_prc=10000.0)
        assert r.stop_loss_price(multiplier=2.0) == 9800.0
        assert r.target_price(multiplier=3.0) == 10300.0

    def test_stop_loss_price_none_when_atr_none(self):
        from indicator_atr import ATRResult

        r = ATRResult(atr=None, cur_prc=10000.0)
        assert r.stop_loss_price() is None
