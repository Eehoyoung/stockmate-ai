from claude_analyst import _extract_json_block, _normalize_action_response


def test_extract_json_block_from_fenced_text():
    payload = """```json
    {"action":"ENTER","confidence":"HIGH","reasons":["a"]}
    ```"""
    parsed = _extract_json_block(payload)
    assert parsed["action"] == "ENTER"
    assert parsed["confidence"] == "HIGH"


def test_normalize_action_response_defaults_and_sanitizes():
    parsed = _normalize_action_response({
        "action": "watch",
        "confidence": "strong",
        "reasons": "momentum",
        "risk_factors": ["volatility", ""],
        "action_guide": None,
        "tp_sl": {"take_profit": "88000", "stop_loss": "83000"},
    })

    assert parsed["action"] == "HOLD"
    assert parsed["confidence"] == "LOW"
    assert parsed["reasons"] == ["momentum"]
    assert parsed["risk_factors"] == ["volatility"]
    assert parsed["tp_sl"]["take_profit"] == 88000.0
    assert parsed["tp_sl"]["stop_loss"] == 83000.0
    assert parsed["portfolio_not_linked"] is True
