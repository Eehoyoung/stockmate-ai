from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

POSITION_META_KEY = "position_lifecycle"
ACTIVE_POSITION_STATES = {"ACTIVE", "PARTIAL_TP", "OVERNIGHT"}
ACTIVE_SIGNAL_STATUSES = {"PENDING", "SENT", "EXECUTED", "OVERNIGHT_HOLD"}
TERMINAL_SIGNAL_STATUSES = {"CANCELLED", "WIN", "LOSS", "EXPIRED"}


def parse_extra_info(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return deepcopy(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"legacy_text": raw}
    return {}


def get_position_meta(extra_info: Any) -> dict:
    parsed = parse_extra_info(extra_info)
    meta = parsed.get(POSITION_META_KEY)
    return deepcopy(meta) if isinstance(meta, dict) else {}


def set_position_meta(extra_info: Any, meta: dict) -> str:
    parsed = parse_extra_info(extra_info)
    parsed[POSITION_META_KEY] = deepcopy(meta)
    return json.dumps(parsed, ensure_ascii=False, default=str)
