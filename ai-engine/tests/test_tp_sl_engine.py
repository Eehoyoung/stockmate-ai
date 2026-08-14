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


def test_s8_zone_exposes_support_gap_for_pre_ai():
    result = calc_tp_sl(
        strategy="S8_GOLDEN_CROSS",
        cur_prc=100,
        highs=[100, 118, 112, 119, 110, 108],
        lows=[99, 96, 97, 95, 98, 94],
        closes=[100, 99, 98, 97, 96, 95],
        stk_cd="005930",
        ma5=96.0,
        ma20=95.0,
        ma60=90.0,
        bb_upper=120.0,
        compute_zones=True,
    )

    payload = result.to_signal_fields()
    assert payload["s8_buy_zone_role"] == "support_zone"
    assert payload["buy_zone"]["high"] < 100
    assert 3.0 < payload["s8_buy_zone_high_gap_pct"] < 6.0


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
    assert payload["min_rr_ratio"] == 1.5
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


def test_priority_strategies_fit_tp_to_strategy_rr():
    cases = [
        (
            "S1_GAP_OPEN",
            dict(cur_prc=1000, highs=[1000, 1026, 1015], lows=[], closes=[], atr=20.0, prev_close=980.0),
            "s1_intraday",
        ),
        (
            "S6_THEME_LAGGARD",
            dict(
                cur_prc=100,
                highs=[100, 101, 102, 103, 104],
                lows=[98, 97, 99, 100, 101],
                closes=[99, 100, 101, 102, 103],
                atr=2.0,
                ma5=98.5,
            ),
            "s6_theme",
        ),
        (
            "S12_CLOSING",
            dict(
                cur_prc=100,
                highs=[100, 101, 102, 102.5],
                lows=[98, 97, 99, 100, 101],
                closes=[99, 100, 101, 102, 103],
                atr=2.0,
                ma5=98.5,
                ma20=96.0,
            ),
            "s12_closing",
        ),
        (
            "S15_MOMENTUM_ALIGN",
            dict(
                cur_prc=100,
                highs=[100, 101, 102, 103],
                lows=[98, 97, 99, 100, 101],
                closes=[99, 100, 101, 102, 103],
                atr=1.0,
                ma20=96.0,
            ),
            "s15_momentum",
        ),
    ]

    for strategy, kwargs, tag in cases:
        result = calc_tp_sl(strategy=strategy, stk_cd="005930", **kwargs)
        assert result.effective_rr >= result.min_rr_ratio
        assert f"rr_fit_{tag}" in result.tp_method


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


def test_s11_frgn_cont_swing_low_near_price_respects_min_sl_gap():
    """S11: swing_low가 진입가의 99.8% (0.2% 이내)에 있어도 SL이 진입가 대비
    최소 2% 이격을 유지해야 한다.

    2026-08-05 운영 관측: SL이 진입가 대비 0.1~0.2%만 떨어져 있어 rr_ratio가
    10~28배로 튀는 이상치가 다수 발생 (예: 255440 rr_ratio=28.70, 365330
    rr_ratio=14.87). swing_low fallback 분기(ma20_gap > 6%)에서 `swing_lows[0]`
    이 cur_prc에 얼마나 가까운지에 대한 하한이 없던 것이 원인.
    """
    cur_prc = 10000.0
    # 단일 국소 저점(local min)이 cur_prc*0.998 지점에 위치하도록 구성
    # (다른 인덱스는 단조 증감이라 find_swing_lows가 이 지점만 후보로 반환한다)
    lows = [
        9999, 9997, 9995, 9993, 9991, 9989, 9987, 9985,
        9980,  # local min == cur_prc * 0.998
        9985, 9987, 9989, 9991, 9993, 9995, 9997, 9999,
    ]
    highs = [10050] * len(lows)
    closes = [cur_prc] * len(lows)

    result = calc_tp_sl(
        strategy="S11_FRGN_CONT",
        cur_prc=cur_prc,
        highs=highs,
        lows=lows,
        closes=closes,
        stk_cd="005930",
        ma20=cur_prc * 0.90,  # MA20 gap(10%) > 6% → swing_low fallback 분기 사용
    )

    payload = result.to_signal_fields()
    sl_gap_pct = (cur_prc - payload["sl_price"]) / cur_prc

    assert sl_gap_pct >= 0.0199  # 최소 2% 이격 (정수 반올림 오차 허용)
    assert "min_gap" in payload["sl_method"]
    # 회귀 방지: 예전 로직대로면 sl_price ≈ 9880 (gap 1.2%) → rr_ratio가
    # 비정상적으로 커졌던 원인. 이제는 최소 이격이 강제되어야 한다.
    assert payload["rr_ratio"] < 10.0


def test_s11_frgn_cont_ma20_branch_also_respects_min_sl_gap():
    """S11: MA20 분기(ma20_gap<=6%)에서도 MA20이 진입가보다 높은 경우
    (돌파 직후 재차 눌림) SL이 최소 2% 이격을 벗어나지 않는지 확인."""
    cur_prc = 10000.0
    lows = [9500.0] * 10
    highs = [10500.0] * 10
    closes = [cur_prc] * 10

    result = calc_tp_sl(
        strategy="S11_FRGN_CONT",
        cur_prc=cur_prc,
        highs=highs,
        lows=lows,
        closes=closes,
        stk_cd="005930",
        ma20=cur_prc * 1.01,  # MA20이 진입가보다 살짝 위 → ma20*0.98 이 지나치게 타이트
    )

    payload = result.to_signal_fields()
    sl_gap_pct = (cur_prc - payload["sl_price"]) / cur_prc

    assert sl_gap_pct >= 0.0199
