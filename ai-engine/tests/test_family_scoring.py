import pytest


def _fresh_ctx(state="fresh", *, toss=True):
    ctx = {
        "freshness": {
            "tick": {"state": state},
            "hoga": {"state": state},
            "strength": {"state": state},
        },
        "market_regime": "bull",
    }
    if toss:
        ctx["toss_risk"] = {"warnings": []}
    return ctx


def test_component_caps_sum_to_100():
    from family_scoring import COMPONENT_CAPS

    assert sum(COMPONENT_CAPS.values()) == 100.0


def test_shadow_score_is_bounded_and_preserves_family_lineage():
    from family_scoring import compute_family_shadow_score

    result = compute_family_shadow_score(
        {
            "strategy": "S9_PULLBACK_SWING",
            "matched_setup_ids": ["S8_GOLDEN_CROSS", "S9_PULLBACK_SWING"],
            "signal_quality_score": 100,
            "effective_rr": 2.0,
            "min_rr_ratio": 1.55,
            "sl_price": 68000,
            "tp1_price": 74000,
        },
        _fresh_ctx(),
        legacy_rule_score=100,
        legacy_components={"technical_score": 40},
    )
    assert result["strategy_family"] == "G04"
    assert result["primary_setup_id"] == "S9_PULLBACK_SWING"
    assert 0 <= result["family_rule_score"] <= 100
    assert result["family_confirmation_bonus"] == 4.0
    assert result["family_shadow_only"] is True


def test_independent_confirmation_is_larger_but_total_is_capped():
    from family_scoring import confirmation_bonus

    bonus, evidence = confirmation_bonus(
        "S9_PULLBACK_SWING",
        ["S8_GOLDEN_CROSS", "S3_INST_FRGN", "S13_BOX_BREAKOUT"],
    )
    assert bonus == 8.0
    assert evidence[0]["correlated"] is True
    assert evidence[0]["bonus"] == 4.0
    assert evidence[1]["correlated"] is False
    assert evidence[1]["bonus"] == 4.0


@pytest.mark.parametrize("state", ["cancel", "missing", "blocked"])
def test_required_unusable_market_data_is_blocking(state):
    from family_scoring import compute_family_shadow_score

    result = compute_family_shadow_score(
        {"strategy": "S13_BOX_BREAKOUT", "effective_rr": 2.0},
        _fresh_ctx(state),
        legacy_rule_score=90,
    )
    assert "REQUIRED_MARKET_DATA_UNUSABLE" in result["blocking_reasons"]
    assert result["family_rule_components"]["liquidity_data_quality"] == 0.0


def test_optional_toss_absence_is_degraded_without_blocking():
    from family_scoring import compute_family_shadow_score

    result = compute_family_shadow_score(
        {"strategy": "S11_FRGN_CONT", "effective_rr": 1.8},
        _fresh_ctx(toss=False),
        legacy_rule_score=75,
    )
    assert "TOSS_RISK_MISSING" in result["degraded_reasons"]
    assert "REQUIRED_MARKET_DATA_UNUSABLE" not in result["blocking_reasons"]


def test_unknown_setup_fails_closed():
    from family_scoring import compute_family_shadow_score

    with pytest.raises(ValueError):
        compute_family_shadow_score(
            {"strategy": "S99_UNKNOWN"}, _fresh_ctx(), legacy_rule_score=80,
        )
