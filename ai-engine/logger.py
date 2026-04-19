from __future__ import annotations
"""
logger.py
StockMate AI 공통 JSON 구조화 로거 – ai-engine 모듈용.

출력 형식 (JSON Lines, 1줄 = 1 로그):
  {"ts":"2026-03-24T01:53:00.123+09:00","level":"INFO","service":"ai-engine",
   "module":"engine","request_id":"...","signal_id":"...","stk_cd":"...","msg":"..."}

사용법:
  from logger import setup_logging, get_logger
  setup_logging(level="INFO", log_file="logs/ai-engine.log")
  logger = get_logger(__name__)
  logger.info("신호 처리 완료", extra={"signal_id": sid, "stk_cd": "005930", "score": 82})
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9))

_SERVICE_NAME = os.getenv("SERVICE_NAME", "ai-engine")

_BUILTIN_KEYS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class JsonLineFormatter(logging.Formatter):
    """Python logging.LogRecord → JSON Lines 변환 포매터.

    공통 필드:
      ts          KST ISO-8601 타임스탬프 (ms 단위)
      level       로그 레벨 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
      service     서비스 이름 (ai-engine)
      module      Python 모듈명
      request_id  요청 추적 ID
      signal_id   신호 추적 ID
      stk_cd      종목 코드
      error_code  오류 코드 (에러 시)
      msg         로그 메시지
      exc         예외 스택트레이스 (예외 발생 시)
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=KST).isoformat(timespec="milliseconds")

        doc: dict = {
            "ts":      ts,
            "level":   record.levelname,
            "service": _SERVICE_NAME,
            "module":  record.name,
            "msg":     record.getMessage(),
        }

        for key in ("request_id", "signal_id", "stk_cd", "error_code", "strategy", "score"):
            val = getattr(record, key, None)
            if val is not None:
                doc[key] = val

        for k, v in record.__dict__.items():
            if k not in _BUILTIN_KEYS and k not in doc and not k.startswith("_"):
                doc[k] = v

        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)

        return json.dumps(doc, ensure_ascii=False, default=str)


def setup_logging(
    service: Optional[str] = None,
    level: str = "INFO",
    log_file: Optional[str] = None,
) -> None:
    """전역 JSON 로깅 초기화 – main 진입점에서 최초 1회 호출."""
    global _SERVICE_NAME
    if service:
        _SERVICE_NAME = service

    fmt = JsonLineFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def get_logger(name: str) -> logging.Logger:
    """모듈별 logger 반환."""
    return logging.getLogger(name)
