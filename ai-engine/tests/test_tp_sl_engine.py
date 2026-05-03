from tp_sl_engine import TpSlResult, _apply_policy_metadata, calc_tp_sl


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
    assert payload["trailing_activation"] > 100
    assert payload["trailing_activation"] <= payload["tp1_price"]
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


def test_tp1_has_minimum_distance_and_tp2_is_consolidated():
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
    assert result.tp2_price is None
    payload = result.to_signal_fields()
    assert payload["display_tp2_price"] > payload["tp1_price"]
    assert "single_tp_avg" in result.tp_method


def test_day_strategy_emits_time_stop_policy():
    result = calc_tp_sl(
        strategy="S1_GAP_OPEN",
        cur_prc=100,
        highs=[100, 103, 104, 102, 101],
        lows=[],
        closes=[],
        stk_cd="005930",
        atr=2.0,
        prev_close=98.0,
    )

    payload = result.to_signal_fields()
    assert payload["time_stop_type"] == "intraday_minutes"
    assert payload["time_stop_minutes"] == 30
    assert payload["time_stop_session"] == "same_day_close"
    assert payload["min_rr_ratio"] == 1.8
    assert payload["allow_overnight"] is False


def test_day_strategy_does_not_average_tp_targets():
    result = calc_tp_sl(
        strategy="S6_THEME_LAGGARD",
        cur_prc=100,
        highs=[100, 110, 112, 111, 108, 115, 114, 109],
        lows=[98, 97, 99, 100, 101, 102, 101, 100],
        closes=[99, 108, 110, 109, 107, 113, 112, 108],
        stk_cd="005930",
        atr=3.0,
        ma5=98.5,
    )

    assert result.tp2_price is None
    assert "single_tp_avg" not in result.tp_method


def test_momentum_keeps_technical_stop_when_support_is_far():
    result = calc_tp_sl(
        strategy="S15_MOMENTUM_ALIGN",
        cur_prc=31850,
        highs=[],
        lows=[],
        closes=[],
        stk_cd="010140",
        atr=1400.0,
        ma20=27680.0,
    )

    assert result.sl_price == int(27680.0 * 0.99)
    assert "risk_cap" not in result.sl_method


def test_strategy_specific_min_rr_is_advisory_for_day_trade():
    result = calc_tp_sl(
        strategy="S2_VI_PULLBACK",
        cur_prc=100,
        highs=[],
        lows=[],
        closes=[],
        stk_cd="005930",
        atr=1.5,
        vi_price=102.0,
    )

    assert result.rr_ratio < 1.6
    assert result.skip_entry is False
    assert "strategy advisory min_rr" in result.rr_skip_reason


def test_invalid_tp_sl_geometry_remains_hard_skip():
    result = _apply_policy_metadata(
        "S2_VI_PULLBACK",
        TpSlResult(
            sl_price=101,
            tp1_price=99,
            rr_ratio=0.0,
            skip_entry=True,
        ),
        cur_prc=100,
        min_rr=1.6,
    )

    assert result.rr_ratio == 0.0
    assert result.skip_entry is True
    assert "strategy advisory min_rr" not in (result.rr_skip_reason or "")
