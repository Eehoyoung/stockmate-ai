"""
utils.py
ai-engine 공통 유틸리티 — 모듈 간 중복 제거용.

주요 용도:
  - Kiwoom REST/WS 응답 숫자 필드 안전 파싱
    (쉼표/부호/빈 문자열/NaN 방어)
"""
from __future__ import annotations

import re
from typing import Optional


def safe_float(v, default: float = 0.0) -> float:
    """Kiwoom 응답 숫자 필드 안전 변환. 쉼표·부호·NaN 방어.

    실패 시 default 반환. NaN 은 f != f 특성으로 필터링.
    """
    try:
        f = float(str(v).replace(",", "").replace("+", ""))
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def safe_float_opt(v) -> Optional[float]:
    """Optional 버전 — None/빈값/NaN 입력 시 None 반환."""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").replace("+", ""))
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def safe_int(v, default: int = 0) -> int:
    """정수 안전 변환. float 경유하여 소수 포함 문자열도 허용."""
    try:
        return int(float(str(v).replace(",", "").replace("+", "")))
    except (TypeError, ValueError):
        return default


def normalize_stock_code(stk_cd: str | None) -> str:
    """키움 접미사(_AL, _NX 등)를 제거한 6자리 기준 종목코드로 정규화."""
    if stk_cd is None:
        return ""
    text = str(stk_cd).strip()
    if not text:
        return ""
    base = text.split("_", 1)[0].strip()
    digits = "".join(re.findall(r"\d", base))
    if len(digits) >= 6:
        return digits[:6]
    return base


def bool_env(key: str, default: bool) -> bool:
    """환경변수를 bool 로 읽는 공통 헬퍼 (engine.py 반복 제거용)."""
    import os
    return os.getenv(key, str(default)).lower() == "true"
