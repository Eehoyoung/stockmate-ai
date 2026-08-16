import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_all_known_strategies_have_non_empty_persona():
    from strategy_meta import ALL_STRATEGIES, get_persona

    for strategy in ALL_STRATEGIES:
        assert get_persona(strategy)


def test_unknown_strategy_uses_default_persona():
    from strategy_meta import DEFAULT_PERSONA, get_persona

    assert get_persona("S99_UNKNOWN") == DEFAULT_PERSONA


def test_normalize_market_type_recognizes_kospi_and_kosdaq_codes():
    from strategy_meta import normalize_market_type

    assert normalize_market_type("001") == "001"
    assert normalize_market_type("KOSPI") == "001"
    assert normalize_market_type("101") == "101"
    assert normalize_market_type("kosdaq") == "101"
    assert normalize_market_type("unknown") == ""
    assert normalize_market_type(None) == ""


def test_regime_from_flu_rt_thresholds():
    from strategy_meta import regime_from_flu_rt

    assert regime_from_flu_rt(None) == "neutral"
    assert regime_from_flu_rt(0.5) == "bull"
    assert regime_from_flu_rt(-0.5) == "bear"
    assert regime_from_flu_rt(0.2) == "sideways"


def test_detect_market_regime_uses_stocks_own_market_not_average():
    from strategy_meta import detect_market_regime

    # KOSPI +1.0% / KOSDAQ -1.0% -- averaging would call this "sideways",
    # but a KOSPI stock should be judged against KOSPI alone: "bull".
    ctx = {"kospi_flu_rt": 1.0, "kosdaq_flu_rt": -1.0, "market_type": "001"}
    assert detect_market_regime(ctx, "S8_GOLDEN_CROSS") == "bull"

    ctx_kosdaq = {"kospi_flu_rt": 1.0, "kosdaq_flu_rt": -1.0, "market_type": "101"}
    assert detect_market_regime(ctx_kosdaq, "S8_GOLDEN_CROSS") == "bear"


def test_detect_market_regime_falls_back_to_average_without_market_type():
    from strategy_meta import detect_market_regime

    ctx = {"kospi_flu_rt": 1.0, "kosdaq_flu_rt": -1.0}
    assert detect_market_regime(ctx, "S8_GOLDEN_CROSS") == "sideways"


def test_detect_market_regime_s1_prefers_pre_market_expected_flu_rt():
    from strategy_meta import detect_market_regime

    ctx = {
        "kospi_exp_flu_rt": 0.8,
        "kospi_flu_rt": -1.0,
        "market_type": "001",
    }
    assert detect_market_regime(ctx, "S1_GAP_OPEN") == "bull"
    # Other strategies ignore the pre-market expected value.
    assert detect_market_regime(ctx, "S3_INST_FRGN") == "bear"


def test_investor_flow_nudges_sideways_regime_to_bull():
    from strategy_meta import detect_market_regime

    ctx = {
        "kospi_flu_rt": 0.1,  # sideways band
        "market_type": "001",
        "investor_flow": {"kospi": {"foreigner_net": 6e11, "institution_net": 6e11}},  # 1.2조
    }
    assert detect_market_regime(ctx, "S9_PULLBACK_SWING") == "bull"


def test_investor_flow_nudges_sideways_regime_to_bear():
    from strategy_meta import detect_market_regime

    ctx = {
        "kosdaq_flu_rt": -0.2,  # sideways band
        "market_type": "101",
        "investor_flow": {"kosdaq": {"foreigner_net": -1.5e11, "institution_net": -1.0e11}},  # -0.25조
    }
    assert detect_market_regime(ctx, "S9_PULLBACK_SWING") == "bear"


def test_investor_flow_does_not_override_clear_price_regime():
    from strategy_meta import detect_market_regime

    # Price already clearly bull (+1.0%); a bearish flow must not flip it.
    ctx = {
        "kospi_flu_rt": 1.0,
        "market_type": "001",
        "investor_flow": {"kospi": {"foreigner_net": -2.0e12, "institution_net": -2.0e12}},
    }
    assert detect_market_regime(ctx, "S9_PULLBACK_SWING") == "bull"


def test_investor_flow_below_threshold_stays_sideways():
    from strategy_meta import detect_market_regime

    ctx = {
        "kospi_flu_rt": 0.0,
        "market_type": "001",
        "investor_flow": {"kospi": {"foreigner_net": 1.0e11, "institution_net": 1.0e11}},  # 0.2조 < 1.0조
    }
    assert detect_market_regime(ctx, "S9_PULLBACK_SWING") == "sideways"


def test_investor_flow_nudge_disabled_via_env(monkeypatch):
    monkeypatch.setenv("REGIME_INVESTOR_FLOW_ENABLED", "false")
    ctx = {
        "kospi_flu_rt": 0.1,
        "market_type": "001",
        "investor_flow": {"kospi": {"foreigner_net": 6e11, "institution_net": 6e11}},
    }
    from strategy_meta import detect_market_regime
    assert detect_market_regime(ctx, "S9_PULLBACK_SWING") == "sideways"


def test_s16_strategy_meta_is_registered(monkeypatch):
    monkeypatch.delenv("SWING_STRATEGIES", raising=False)
    import strategy_meta
    strategy_meta = importlib.reload(strategy_meta)

    strategy = "S16_ACCUMULATION_SHADOW"
    assert strategy in strategy_meta.ALL_STRATEGIES
    assert strategy_meta.is_swing(strategy) is True
    assert strategy_meta.get_threshold(strategy) == 75.0
    assert strategy_meta.get_hold_to_enter_threshold(strategy) == 85.0
    assert strategy_meta.get_strategy_base_rr_gate(strategy) == 1.60
    assert strategy_meta.get_strategy_rr_group(strategy) == "flow"


def test_family_live_routing_uses_canonical_rr_and_rolls_back(monkeypatch):
    import strategy_meta

    monkeypatch.setenv("ENABLE_STRATEGY_FAMILY_LIVE_ROUTING", "true")
    assert strategy_meta.get_strategy_base_rr_gate("S1_GAP_OPEN") == 1.50
    assert strategy_meta.get_strategy_base_rr_gate("S2_VI_PULLBACK") == 1.80
    assert strategy_meta.get_strategy_base_rr_gate("S16_ACCUMULATION_SHADOW") == 1.80

    monkeypatch.setenv("ENABLE_STRATEGY_FAMILY_LIVE_ROUTING", "false")
    assert strategy_meta.get_strategy_base_rr_gate("S1_GAP_OPEN") == 1.20
    assert strategy_meta.get_strategy_base_rr_gate("S16_ACCUMULATION_SHADOW") == 1.60
