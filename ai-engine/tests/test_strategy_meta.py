import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_all_known_strategies_have_non_empty_persona():
    from strategy_meta import ALL_STRATEGIES, get_persona

    for strategy in ALL_STRATEGIES:
        assert get_persona(strategy)


def test_unknown_strategy_uses_default_persona():
    from strategy_meta import DEFAULT_PERSONA, get_persona

    assert get_persona("S99_UNKNOWN") == DEFAULT_PERSONA
