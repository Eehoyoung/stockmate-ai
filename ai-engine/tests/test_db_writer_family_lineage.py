import json

import pytest


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
            "stk_cd": "005930",
            "strategy": "S9_PULLBACK_SWING",
            "strategy_family": "G04",
            "strategy_family_name": "TREND_PHASE",
            "primary_setup_id": "S9_PULLBACK_SWING",
            "matched_setup_ids": ["S8_GOLDEN_CROSS", "S9_PULLBACK_SWING"],
            "family_policy_version": "family_v1_2026_08_16",
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
    assert "$68" in sql
    assert len(args) == 68
    assert args[60:68] == (
        "G04",
        "TREND_PHASE",
        "S9_PULLBACK_SWING",
        json.dumps(["S8_GOLDEN_CROSS", "S9_PULLBACK_SWING"], ensure_ascii=False),
        "family_v1_2026_08_16",
        "[]",
        json.dumps(["TOSS_RISK_MISSING"], ensure_ascii=False),
        77.25,
    )
