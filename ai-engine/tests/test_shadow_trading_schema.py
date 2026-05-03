from pathlib import Path


def test_shadow_trades_migration_contains_reporting_contract():
    repo_root = Path(__file__).resolve().parents[2]
    migration = repo_root / "api-orchestrator" / "src" / "main" / "resources" / "db" / "migration" / "V42__create_shadow_trades.sql"
    sql = migration.read_text(encoding="utf-8").lower()

    for column in [
        "signal_id",
        "strategy",
        "entry_price",
        "tp1_price",
        "sl_price",
        "signal_time",
        "max_favorable_excursion",
        "max_adverse_excursion",
        "result",
        "realized_pnl_simulated",
        "exit_reason",
        "latency_ms",
        "data_quality",
    ]:
        assert column in sql

    assert "unique (signal_id)" in sql
    assert "references trading_signals(id)" in sql
