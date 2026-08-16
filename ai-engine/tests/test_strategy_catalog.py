import pytest


def test_catalog_maps_all_16_setups_exactly_once():
    from strategy_catalog import ALL_SETUP_IDS, FAMILIES, FAMILY_BY_SETUP, SETUP_BY_NUMBER

    flattened = [setup for family in FAMILIES for setup in family.setup_ids]
    assert len(FAMILIES) == 7
    assert len(SETUP_BY_NUMBER) == 16
    assert len(flattened) == 16
    assert len(set(flattened)) == 16
    assert set(flattened) == set(ALL_SETUP_IDS) == set(FAMILY_BY_SETUP)


def test_approved_family_membership_is_stable():
    from strategy_catalog import FAMILY_BY_ID

    assert FAMILY_BY_ID["G01"].setup_ids == (
        "S1_GAP_OPEN", "S2_VI_PULLBACK", "S12_CLOSING",
    )
    assert FAMILY_BY_ID["G02"].setup_ids == (
        "S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT",
    )
    assert FAMILY_BY_ID["G03"].setup_ids == ("S16_ACCUMULATION_SHADOW",)
    assert FAMILY_BY_ID["G04"].setup_ids == (
        "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S15_MOMENTUM_ALIGN",
    )
    assert FAMILY_BY_ID["G05"].setup_ids == (
        "S7_ICHIMOKU_BREAKOUT", "S10_NEW_HIGH", "S13_BOX_BREAKOUT",
    )
    assert FAMILY_BY_ID["G06"].setup_ids == ("S4_BIG_CANDLE", "S6_THEME_LAGGARD")
    assert FAMILY_BY_ID["G07"].setup_ids == ("S14_OVERSOLD_BOUNCE",)


def test_unknown_setup_and_number_fail_closed():
    from strategy_catalog import family_for_setup, setup_id_for_number

    with pytest.raises(ValueError):
        family_for_setup("S99_UNKNOWN")
    with pytest.raises(ValueError):
        setup_id_for_number(99)


def test_family_lineage_preserves_legacy_setup():
    from strategy_catalog import CATALOG_VERSION, family_lineage

    lineage = family_lineage("S9_PULLBACK_SWING")
    assert lineage == {
        "strategy_family": "G04",
        "strategy_family_name": "TREND_PHASE",
        "primary_setup_id": "S9_PULLBACK_SWING",
        "matched_setup_ids": ["S9_PULLBACK_SWING"],
        "family_policy_version": CATALOG_VERSION,
    }


@pytest.mark.asyncio
async def test_claude_candidate_pool_catalog_includes_s16():
    import claude_analyst

    async def lrange(key, start, end):
        return ["016160"] if key == "candidates:s16:101" else []

    class RedisStub:
        pass

    rdb = RedisStub()
    rdb.lrange = lrange
    assert await claude_analyst._check_candidate_pools(rdb, "016160") == [
        "S16_ACCUMULATION_SHADOW"
    ]


@pytest.mark.asyncio
async def test_live_candidate_catalog_reorders_s16(monkeypatch):
    import candidates_builder

    writes = []

    class RedisStub:
        async def lrange(self, key, start, end):
            return ["111111", "016160"] if key == "candidates:s16:001" else []

        async def ttl(self, key):
            return 120

    async def capture(rdb, key, codes, ttl, **kwargs):
        writes.append((key, codes, ttl))

    monkeypatch.setattr(candidates_builder, "_lpush_with_ttl", capture)
    await candidates_builder._prioritize_existing_candidate_pools(
        RedisStub(), "001", {"016160": 10.0},
    )
    assert writes == [("candidates:s16:001", ["016160", "111111"], 120)]
