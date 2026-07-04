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
