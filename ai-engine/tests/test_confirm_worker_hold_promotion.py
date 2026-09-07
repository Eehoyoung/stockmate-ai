from confirm_worker import _maybe_promote_hold_to_enter


def test_human_confirmed_high_confidence_hold_promotes_to_enter():
    result = _maybe_promote_hold_to_enter({
        "action": "HOLD",
        "ai_score": 85,
        "confidence": "HIGH",
        "reason": "strong setup",
        "cancel_reason": "wait",
    })

    assert result["action"] == "ENTER"
    assert result["cancel_reason"] is None
