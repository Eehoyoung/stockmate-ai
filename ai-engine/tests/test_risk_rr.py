import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_calc_rr_includes_round_trip_fee():
    from risk.rr import calc_rr

    rr, skip = calc_rr(10000, 11000, 9700, 0.0035, 1.3)

    assert rr == 2.514
    assert skip is False


def test_invalid_rr_geometry_skips_entry():
    from risk.rr import calc_raw_rr, calc_rr, required_tp_for_rr

    assert calc_rr(10000, 9900, 9700, 0.0035, 1.3) == (0.0, True)
    assert calc_raw_rr(10000, 9900, 9700) is None
    assert required_tp_for_rr(10000, 10100, 0.0035, 1.3) is None


def test_slip_fee_uses_code_prefix():
    from risk.rr import slip_fee_for_stock

    assert slip_fee_for_stock("005930", kospi_fee=0.0035, kosdaq_fee=0.0045) == 0.0035
    assert slip_fee_for_stock("123456", kospi_fee=0.0035, kosdaq_fee=0.0045) == 0.0045
