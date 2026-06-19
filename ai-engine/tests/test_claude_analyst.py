from claude_analyst import _extract_json_block, _normalize_action_response


def test_extract_json_block_from_fenced_text():
    payload = """```json
    {"action":"ENTER","confidence":"HIGH","reasons":["a"]}
    ```"""
    parsed = _extract_json_block(payload)
    assert parsed["action"] == "ENTER"
    assert parsed["confidence"] == "HIGH"


def test_extract_json_block_repairs_missing_comma_between_fields():
    payload = """{
      "action": "HOLD",
      "confidence": "LOW",
      "reasons": ["체결강도 미달"]
      "risk_factors": ["분봉 모멘텀 약화"],
      "action_guide": ["재평가 필요"],
      "tp_sl": {"take_profit": 10000, "stop_loss": 9300}
      "summary": "관망 우세"
    }"""

    parsed = _extract_json_block(payload)

    assert parsed["action"] == "HOLD"
    assert parsed["risk_factors"] == ["분봉 모멘텀 약화"]
    assert parsed["summary"] == "관망 우세"


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
