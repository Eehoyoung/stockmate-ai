import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_s1_entry_policy_allows_balanced_gap_setup():
    from strategy_1_gap_opening import _s1_entry_policy

    policy, reasons = _s1_entry_policy(
        gap_pct=4.0,
        strength=150.0,
        bid_ratio=1.5,
        rr_ratio=1.2,
        early_open=False,
        expected_age_ms=5_000,
        expected_bid_decay_pct=-5.0,
        post_open_extension_pct=0.4,
        execution_quality="A",
        first_low_break=False,
        vwap_position="ABOVE_VWAP",
    )

    assert policy == "ENTER_CANDIDATE"
    assert reasons == []


def test_s1_entry_policy_holds_when_expected_bid_weakens():
    from strategy_1_gap_opening import _s1_entry_policy

    policy, reasons = _s1_entry_policy(
        gap_pct=4.0,
        strength=150.0,
        bid_ratio=1.5,
        rr_ratio=1.2,
        early_open=False,
        expected_age_ms=5_000,
        expected_bid_decay_pct=-35.0,
        post_open_extension_pct=0.4,
        execution_quality="A",
        first_low_break=False,
        vwap_position="ABOVE_VWAP",
    )

    assert policy == "HOLD_RECHECK"
    assert any("expected bid weakened" in reason for reason in reasons)


def test_s1_entry_policy_cancels_first_low_break_below_vwap():
    from strategy_1_gap_opening import _s1_entry_policy

    policy, reasons = _s1_entry_policy(
        gap_pct=4.0,
        strength=160.0,
        bid_ratio=1.8,
        rr_ratio=1.5,
        early_open=False,
        expected_age_ms=5_000,
        expected_bid_decay_pct=0.0,
        post_open_extension_pct=0.2,
        execution_quality="REJECT",
        first_low_break=True,
        vwap_position="BELOW_VWAP",
    )

    assert policy == "CANCEL"
    assert "first low break below VWAP" in reasons


def test_s1_entry_policy_holds_overheated_gap_without_full_confirmation():
    from strategy_1_gap_opening import _s1_entry_policy

    policy, reasons = _s1_entry_policy(
        gap_pct=9.0,
        strength=140.0,
        bid_ratio=1.4,
        rr_ratio=1.1,
        early_open=False,
        expected_age_ms=5_000,
        expected_bid_decay_pct=0.0,
        post_open_extension_pct=0.6,
        execution_quality="B",
        first_low_break=False,
        vwap_position="ABOVE_VWAP",
    )

    assert policy == "HOLD_RECHECK"
    assert any("8-12pct gap" in reason for reason in reasons)
