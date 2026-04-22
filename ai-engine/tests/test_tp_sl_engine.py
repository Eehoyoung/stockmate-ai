from tp_sl_engine import calc_tp_sl


def _series(base: float, step: float, size: int) -> list[float]:
    return [base + step * i for i in range(size)]


def test_swing_strategy_emits_trailing_metadata():
    highs = [100, 108, 112, 118, 120, 116, 114, 113, 112, 111]
    lows = [98, 96, 97, 101, 104, 103, 102, 101, 100, 99]
    closes = [99, 102, 108, 114, 118, 115, 113, 112, 111, 110]

    result = calc_tp_sl(
        strategy="S8_GOLDEN_CROSS",
        cur_prc=100,
        highs=highs,
        lows=lows,
        closes=closes,
        stk_cd="005930",
        atr=4.0,
        ma20=96.0,
        bb_upper=118.0,
    )

    payload = result.to_signal_fields()
    assert payload["trailing_pct"] == 2.5
    assert payload["trailing_activation"] == payload["tp1_price"]
    assert payload["trailing_basis"] == "tp1_hit"
    assert payload["strategy_version"]


def test_macd_weakening_tightens_trailing_and_marks_method():
    highs = [100, 110, 116, 120, 124, 121, 119, 118, 117, 116, 115]
    lows = [98, 96, 97, 99, 102, 103, 104, 103, 102, 101, 100]
    closes = [99, 104, 109, 114, 120, 118, 117, 116, 115, 114, 113]

    strong = calc_tp_sl(
        strategy="S15_MOMENTUM_ALIGN",
        cur_prc=100,
        highs=highs,
        lows=lows,
        closes=closes,
        stk_cd="005930",
        atr=4.0,
        ma20=95.0,
        bb_upper=125.0,
        macd_line=1.0,
        macd_signal=0.5,
        macd_hist=0.4,
    )
    weak = calc_tp_sl(
        strategy="S15_MOMENTUM_ALIGN",
        cur_prc=100,
        highs=highs,
        lows=lows,
        closes=closes,
        stk_cd="005930",
        atr=4.0,
        ma20=95.0,
        bb_upper=125.0,
        macd_line=0.1,
        macd_signal=0.4,
        macd_hist=-0.2,
    )

    assert weak.trailing_pct < strong.trailing_pct
    assert "macd_guard" in weak.tp_method


def test_tp1_has_minimum_distance_and_tp2_stays_above_tp1():
    highs = _series(100, 1, 20)
    lows = [96.0] * 20
    closes = _series(99, 0.5, 20)

    result = calc_tp_sl(
        strategy="S13_BOX_BREAKOUT",
        cur_prc=100,
        highs=highs,
        lows=lows,
        closes=closes,
        stk_cd="005930",
        atr=2.0,
    )

    assert result.tp1_price >= 103
    assert result.tp2_price is None or result.tp2_price > result.tp1_price
