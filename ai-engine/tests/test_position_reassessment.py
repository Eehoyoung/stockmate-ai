from position_reassessment import (
    build_reason_summary,
    classify_momentum_state,
    classify_trend_state,
    decide_exit_bias,
)


def test_classify_trend_state_bullish_alignment():
    assert classify_trend_state(105.0, 100.0, 95.0, 58.0) == "BULLISH"


def test_classify_trend_state_bearish_below_ma20():
    assert classify_trend_state(95.0, 100.0, 98.0, 52.0) == "BEARISH"


def test_classify_momentum_state_strong_when_above_vwap_and_hist_expands():
    assert classify_momentum_state(
        minute_rsi=61.0,
        macd_hist=0.18,
        macd_hist_prev=0.11,
        stoch_k=65.0,
        cur_prc=101.0,
        vwap=100.0,
    ) == "STRONG"


def test_classify_momentum_state_weak_when_below_vwap():
    assert classify_momentum_state(
        minute_rsi=49.0,
        macd_hist=0.05,
        macd_hist_prev=0.08,
        stoch_k=42.0,
        cur_prc=99.0,
        vwap=100.0,
    ) == "WEAK"


def test_decide_exit_bias_tighten_on_bearish_trend():
    assert decide_exit_bias("BEARISH", "NEUTRAL", 1.1, 103.0) == "TIGHTEN"


def test_build_reason_summary_contains_all_sections():
    summary = build_reason_summary("BULLISH", "STRONG", "HOLD")
    assert "일봉 추세 우상향" in summary
    assert "분봉 모멘텀 강함" in summary
    assert "추세 보유 우선" in summary
