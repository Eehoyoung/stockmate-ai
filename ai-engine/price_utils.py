from __future__ import annotations

from typing import Any


def get_tick_size(price: int | float) -> int:
    price = int(float(price or 0))
    if price < 2000:
        return 1
    if price < 5000:
        return 5
    if price < 20000:
        return 10
    if price < 50000:
        return 50
    if price < 200000:
        return 100
    if price < 500000:
        return 500
    return 1000


def round_to_tick(price: int | float | None, direction: str = "nearest") -> int | None:
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return 0

    tick = get_tick_size(value)
    if direction == "down":
        return int(value // tick * tick)
    if direction == "up":
        return int(((value + tick - 1) // tick) * tick)
    return int(round(value / tick) * tick)


def normalize_signal_prices(signal: dict[str, Any]) -> dict[str, Any]:
    entry_ref_raw = signal.get("cur_prc")
    if not entry_ref_raw:
        entry_ref_raw = signal.get("entry_price")
    entry_ref = round_to_tick(entry_ref_raw, "nearest") if entry_ref_raw is not None else None

    for field in ("cur_prc", "entry_price", "peak_price", "exit_price", "target_price", "stop_price"):
        if field in signal and signal.get(field) is not None:
            signal[field] = round_to_tick(signal.get(field), "nearest")

    if entry_ref:
        for field in ("tp1_price", "tp2_price", "target_price", "claude_tp1", "claude_tp2"):
            value = signal.get(field)
            if value is None:
                continue
            rounded = round_to_tick(value, "nearest")
            if rounded is not None and rounded <= entry_ref:
                rounded = round_to_tick(value, "up")
            signal[field] = rounded

        for field in ("sl_price", "stop_price", "claude_sl"):
            value = signal.get(field)
            if value is None:
                continue
            rounded = round_to_tick(value, "nearest")
            if rounded is not None and rounded >= entry_ref:
                rounded = round_to_tick(value, "down")
            signal[field] = rounded
    else:
        for field in ("tp1_price", "tp2_price", "sl_price", "claude_tp1", "claude_tp2", "claude_sl"):
            if field in signal and signal.get(field) is not None:
                signal[field] = round_to_tick(signal.get(field), "nearest")

    return signal
