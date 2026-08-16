from __future__ import annotations

"""Versioned strategy-family catalog.

The legacy S identifiers remain the immutable setup and attribution keys.  The
G identifiers are additive portfolio/operation families and must never replace
``signal["strategy"]`` during the compatibility phase.
"""

from dataclasses import dataclass
import os


CATALOG_VERSION = "family_v1_2026_08_16"
RULE_SCORE_VERSION = "family_score_v1_2026_08_16"
PROMPT_VERSION = "family_prompt_v1_2026_08_16"


def family_lineage_enabled() -> bool:
    """Runtime kill switch; disabled until shadow activation is approved."""
    return os.getenv("ENABLE_STRATEGY_FAMILY_LINEAGE", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def family_live_routing_enabled() -> bool:
    """Master kill switch for family policy to influence live decisions."""
    return os.getenv("ENABLE_STRATEGY_FAMILY_LIVE_ROUTING", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


@dataclass(frozen=True)
class StrategyFamily:
    family_id: str
    name: str
    display_name_ko: str
    setup_ids: tuple[str, ...]
    rule_threshold: int
    merge_type: str


FAMILIES: tuple[StrategyFamily, ...] = (
    StrategyFamily("G01", "SESSION_EVENT", "세션·이벤트", (
        "S1_GAP_OPEN", "S2_VI_PULLBACK", "S12_CLOSING",
    ), 70, "orchestration_only"),
    StrategyFamily("G02", "FLOW_TREND", "수급추세", (
        "S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT",
    ), 70, "shared_features_and_confirmation"),
    StrategyFamily("G03", "ACCUMULATION_CONFIRM", "축적확인", (
        "S16_ACCUMULATION_SHADOW",
    ), 78, "state_machine_wrapper"),
    StrategyFamily("G04", "TREND_PHASE", "추세단계", (
        "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S15_MOMENTUM_ALIGN",
    ), 70, "stateful_setup_router"),
    StrategyFamily("G05", "STRUCTURAL_BREAKOUT", "구조돌파", (
        "S7_ICHIMOKU_BREAKOUT", "S10_NEW_HIGH", "S13_BOX_BREAKOUT",
    ), 74, "shared_breakout_engine"),
    StrategyFamily("G06", "INTRADAY_THEME_MOMENTUM", "장중급등·테마", (
        "S4_BIG_CANDLE", "S6_THEME_LAGGARD",
    ), 72, "shared_intraday_risk_budget"),
    StrategyFamily("G07", "REVERSAL_BOUNCE", "역추세반등", (
        "S14_OVERSOLD_BOUNCE",
    ), 75, "independent_wrapper"),
)


SETUP_BY_NUMBER: dict[int, str] = {
    1: "S1_GAP_OPEN",
    2: "S2_VI_PULLBACK",
    3: "S3_INST_FRGN",
    4: "S4_BIG_CANDLE",
    5: "S5_PROG_FRGN",
    6: "S6_THEME_LAGGARD",
    7: "S7_ICHIMOKU_BREAKOUT",
    8: "S8_GOLDEN_CROSS",
    9: "S9_PULLBACK_SWING",
    10: "S10_NEW_HIGH",
    11: "S11_FRGN_CONT",
    12: "S12_CLOSING",
    13: "S13_BOX_BREAKOUT",
    14: "S14_OVERSOLD_BOUNCE",
    15: "S15_MOMENTUM_ALIGN",
    16: "S16_ACCUMULATION_SHADOW",
}

SETUP_NUMBERS: tuple[int, ...] = tuple(SETUP_BY_NUMBER)
ALL_SETUP_IDS: frozenset[str] = frozenset(SETUP_BY_NUMBER.values())
SETUP_KEY_TO_ID: dict[str, str] = {f"s{number}": setup for number, setup in SETUP_BY_NUMBER.items()}
FAMILY_BY_ID: dict[str, StrategyFamily] = {family.family_id: family for family in FAMILIES}
FAMILY_BY_SETUP: dict[str, StrategyFamily] = {
    setup: family for family in FAMILIES for setup in family.setup_ids
}

DAY_SETUP_IDS: frozenset[str] = frozenset({
    "S1_GAP_OPEN", "S2_VI_PULLBACK", "S4_BIG_CANDLE", "S6_THEME_LAGGARD",
})
DEFAULT_SWING_SETUP_IDS: frozenset[str] = ALL_SETUP_IDS - DAY_SETUP_IDS

# New canonical effective-RR targets.  They are additive catalog metadata until
# the versioned TP/SL policy WP promotes them into the live hard-gate path.
EFFECTIVE_RR_BY_SETUP: dict[str, float] = {
    "S1_GAP_OPEN": 1.50,
    "S2_VI_PULLBACK": 1.80,
    "S3_INST_FRGN": 1.50,
    "S4_BIG_CANDLE": 1.70,
    "S5_PROG_FRGN": 1.50,
    "S6_THEME_LAGGARD": 1.60,
    "S7_ICHIMOKU_BREAKOUT": 1.80,
    "S8_GOLDEN_CROSS": 1.50,
    "S9_PULLBACK_SWING": 1.55,
    "S10_NEW_HIGH": 1.55,
    "S11_FRGN_CONT": 1.55,
    "S12_CLOSING": 1.50,
    "S13_BOX_BREAKOUT": 1.55,
    "S14_OVERSOLD_BOUNCE": 1.50,
    "S15_MOMENTUM_ALIGN": 1.55,
    "S16_ACCUMULATION_SHADOW": 1.80,
}


def family_for_setup(setup_id: str) -> StrategyFamily:
    """Return the one family owning ``setup_id``; unknown setups fail closed."""
    try:
        return FAMILY_BY_SETUP[setup_id]
    except KeyError as exc:
        raise ValueError(f"unknown strategy setup: {setup_id}") from exc


def setup_id_for_number(number: int) -> str:
    try:
        return SETUP_BY_NUMBER[number]
    except KeyError as exc:
        raise ValueError(f"unknown strategy number: {number}") from exc


def family_lineage(setup_id: str) -> dict[str, object]:
    """Additive payload fields; the caller keeps the legacy strategy value."""
    family = family_for_setup(setup_id)
    return {
        "family_id": family.family_id,
        "family_name": family.name,
        "strategy_family": family.family_id,
        "strategy_family_name": family.name,
        "primary_setup_id": setup_id,
        "matched_setup_ids": [setup_id],
        "family_policy_version": CATALOG_VERSION,
        "setup_version": f"{setup_id.lower()}_family_v1",
        "rule_score_version": RULE_SCORE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "confirmed_by_family_ids": [],
    }
