from pathlib import Path


def test_audit_lineage_migration_is_additive_and_has_summary_producer():
    root = Path(__file__).resolve().parents[2]
    sql = (root / "api-orchestrator" / "src" / "main" / "resources" / "db" / "migration"
           / "V50__add_audit_lineage_and_summary_producer.sql").read_text(encoding="utf-8")

    for required in (
        "received_at",
        "raw_source_time",
        "source_time_parse_status",
        "correlation_id",
        "decision_at",
        "order_submit_at",
        "broker_ack_at",
        "first_fill_at",
        "official_snapshot",
        "refresh_ws_tick_summary_1m",
        "ON CONFLICT",
    ):
        assert required in sql

    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()
