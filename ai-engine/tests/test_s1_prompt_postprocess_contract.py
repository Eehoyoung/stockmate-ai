import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_s1_prompt_contains_runtime_inputs_and_tpsl_contract():
    from analyzer import _build_user_message

    signal = {
        "strategy": "S1_GAP_OPEN",
        "stk_cd": "005930",
        "stk_nm": "Samsung Electronics",
        "gap_pct": 4.2,
        "bid_ratio": 7.17,
        "cntr_strength": 143.5,
        "cur_prc": 84300,
        "tp1_price": 88000,
        "tp2_price": 92000,
        "sl_price": 82000,
        "signal_quality_score": 72.5,
        "signal_quality_bucket": "strong",
        "rr_quality_bucket": "ok",
        "strategy_sample_count": 12,
    }
    market_ctx = {
        "tick": {"flu_rt": "5.46", "acc_trde_prica": "12000000000"},
        "hoga": {},
        "strength": 0,
        "kospi_flu_rt": 0.34,
        "kosdaq_flu_rt": -0.12,
    }

    msg = _build_user_message(signal, market_ctx, 100.0)

    for expected in [
        "Samsung Electronics",
        "005930",
        "4.2",
        "7.17",
        "143.5",
        "5.46",
        "84,300",
        "88,000",
        "92,000",
        "82,000",
        "72.5",
        "strong",
        "TP1/TP2/SL",
        "JSON",
    ]:
        assert expected in msg


def test_ai_failure_fallback_is_cancel_and_keeps_price_fields_null():
    from analyzer import _fallback

    result = _fallback(100.0)

    assert result["action"] == "CANCEL"
    assert result["confidence"] == "LOW"
    assert result["cancel_type"] == "AI_UNAVAILABLE"
    assert result["cancel_reason"]
    assert result["claude_tp1"] is None
    assert result["claude_tp2"] is None
    assert result["claude_sl"] is None


def test_postprocess_preserves_claude_prices_for_enter_and_clears_cancel_reason():
    from analyzer import _normalize_signal_result

    result = _normalize_signal_result({
        "action": "ENTER",
        "ai_score": 81,
        "confidence": "HIGH",
        "reason": "entry accepted",
        "cancel_reason": "should be ignored",
        "claude_tp1": 88000,
        "claude_tp2": 92000,
        "claude_sl": 82000,
    })

    assert result["action"] == "ENTER"
    assert result["cancel_reason"] is None
    assert result["claude_tp1"] == 88000
    assert result["claude_tp2"] == 92000
    assert result["claude_sl"] == 82000


def test_postprocess_fills_cancel_reason_for_cancel():
    from analyzer import _normalize_signal_result

    result = _normalize_signal_result({
        "action": "CANCEL",
        "ai_score": 35,
        "confidence": "LOW",
        "reason": "weak opening auction",
    })

    assert result["action"] == "CANCEL"
    assert result["cancel_reason"] == "weak opening auction"
