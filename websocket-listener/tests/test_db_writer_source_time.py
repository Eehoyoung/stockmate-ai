from datetime import datetime

from db_writer import _parse_source_time


def test_parse_source_time_preserves_raw_and_reports_skew():
    source_at, raw, status, skew_ms = _parse_source_time({"20": "091530"})

    assert isinstance(source_at, datetime)
    assert raw == "091530"
    assert status == "PARSED"
    assert isinstance(skew_ms, int)


def test_parse_source_time_classifies_missing_and_invalid():
    assert _parse_source_time({}) == (None, None, "MISSING", None)
    assert _parse_source_time({"20": "bad"}) == (None, "bad", "INVALID_FORMAT", None)
    assert _parse_source_time({"20": "296199"}) == (None, "296199", "INVALID_VALUE", None)
