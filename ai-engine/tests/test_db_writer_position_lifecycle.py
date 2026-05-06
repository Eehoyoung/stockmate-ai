from db_writer import _is_monitorable_position


def _row(signal_status="EXECUTED", position_status="ACTIVE", exit_type=None):
    return {
        "signal_status": signal_status,
        "position_status": position_status,
        "exit_type": exit_type,
    }


def test_expired_active_position_remains_monitorable():
    assert _is_monitorable_position(_row(signal_status="EXPIRED")) is True


def test_closed_expired_position_is_not_monitorable():
    assert _is_monitorable_position(_row(signal_status="EXPIRED", position_status="CLOSED")) is False


def test_position_with_exit_type_is_not_monitorable():
    assert _is_monitorable_position(_row(signal_status="EXECUTED", exit_type="TP1_HIT")) is False
