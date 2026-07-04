from __future__ import annotations


def calc_rr(
    cur_prc: float,
    tp_price: float,
    sl_price: float,
    slip_fee: float,
    min_rr: float,
) -> tuple[float, bool]:
    """Calculate effective reward:risk after round-trip slippage/fee."""
    if cur_prc <= 0 or sl_price <= 0 or tp_price <= cur_prc or sl_price >= cur_prc:
        return 0.0, True

    round_trip_fee = 2 * slip_fee
    reward = (tp_price - cur_prc) / cur_prc - round_trip_fee
    risk = (cur_prc - sl_price) / cur_prc + round_trip_fee

    if risk <= 0:
        return 0.0, True

    rr = reward / risk
    return round(rr, 3), rr < min_rr


def calc_raw_rr(cur_prc: float, tp_price: float, sl_price: float) -> float | None:
    if cur_prc <= 0 or tp_price <= cur_prc or sl_price >= cur_prc:
        return None
    risk = cur_prc - sl_price
    if risk <= 0:
        return None
    return round((tp_price - cur_prc) / risk, 3)


def required_tp_for_rr(cur_prc: float, sl_price: float, slip_fee: float, min_rr: float) -> int | None:
    if cur_prc <= 0 or sl_price <= 0 or sl_price >= cur_prc:
        return None
    round_trip_fee = 2 * slip_fee
    risk = (cur_prc - sl_price) / cur_prc + round_trip_fee
    if risk <= 0:
        return None
    required_reward = min_rr * risk + round_trip_fee
    return int(cur_prc * (1.0 + required_reward)) + 1


def slip_fee_for_stock(stk_cd: str, *, kospi_fee: float, kosdaq_fee: float) -> float:
    return kospi_fee if str(stk_cd).startswith("0") else kosdaq_fee

