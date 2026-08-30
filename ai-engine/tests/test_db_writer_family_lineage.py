import json
from pathlib import Path

import pytest


FIXTURE = json.loads(
    (Path(__file__).parents[2] / "test-fixtures" / "strategy_family_lineage.json")
    .read_text(encoding="utf-8")
)


def test_queue_lineage_matches_shared_consumer_contract():
    from strategy_catalog import family_lineage

    lineage = family_lineage(FIXTURE["strategy"])
    for key in (
        "strategy_family", "strategy_family_name", "primary_setup_id",
        "matched_setup_ids", "confirmed_by_family_ids", "family_policy_version",
        "setup_version", "rule_score_version", "prompt_version",
    ):
        assert lineage[key] == FIXTURE[key]


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self):
        self.fetchrow_calls = []
        self.execute_calls = []

    def transaction(self):
        return _Transaction()

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return {"id": 321}

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        return "OK"


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self):
        self.conn = _Connection()

    def acquire(self):
        return _Acquire(self.conn)


@pytest.mark.asyncio
async def test_insert_python_signal_persists_additive_family_lineage():
    from db_writer import insert_python_signal

    pool = _Pool()
    signal_id = await insert_python_signal(
        pool,
        {
            **FIXTURE,
            "blocking_reasons": [],
            "degraded_reasons": ["TOSS_RISK_MISSING"],
            "final_score": 77.25,
            "cur_prc": 70000,
        },
        action="ENTER",
        confidence="HIGH",
        rule_score=78.0,
        ai_score=76.0,
        ai_reason="test",
        skip_entry=False,
    )

    assert signal_id == 321
    sql, args = pool.conn.fetchrow_calls[0]
    assert "strategy_family" in sql
    assert "$76" in sql
    assert len(args) == 80
    assert "reevaluation_of_signal_id" in sql
    assert "ON CONFLICT (correlation_id, strategy, stk_cd)" in sql
    assert args[60:68] == (
        "G04",
        "TREND_PHASE",
        "S9_PULLBACK_SWING",
        json.dumps(FIXTURE["matched_setup_ids"], ensure_ascii=False),
        "family_v1_2026_08_16",
        "[]",
        json.dumps(["TOSS_RISK_MISSING"], ensure_ascii=False),
        77.25,
    )
    assert args[68:76] == (
        json.dumps(FIXTURE["confirmed_by_family_ids"], ensure_ascii=False),
        "s9_pullback_swing_family_v1",
        "family_score_v1_2026_08_16",
        "family_prompt_v1_2026_08_16",
        json.dumps(FIXTURE["data_source"], ensure_ascii=False),
        json.dumps(FIXTURE["source_timestamp"], ensure_ascii=False),
        json.dumps(FIXTURE["source_age_ms"], ensure_ascii=False),
        "[]",
    )
