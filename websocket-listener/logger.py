"""
logger.py
StockMate AI 공통 JSON 구조화 로거 – websocket-listener 모듈용.

출력 형식 (JSON Lines, 1줄 = 1 로그):
  {"ts":"2026-03-24T01:53:00.123+09:00","level":"INFO","service":"websocket-listener",
   "module":"ws_client","request_id":"...","signal_id":"...","msg":"..."}

사용법:
  from logger import setup_logging, get_logger
  setup_logging(level="INFO", log_file="logs/websocket-listener.log")
  logger = get_logger(__name__)
  logger.info("연결 성공", extra={"request_id": rid, "stk_cd": "005930"})
"""

import glob
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9))

# 모듈 전역 SERVICE_NAME (setup_logging() 에서 덮어씀)
_SERVICE_NAME = os.getenv("SERVICE_NAME", "websocket-listener")

# LogRecord 기본 속성 — extra 추출 시 제외
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
      level       로그 레벨 (DEBUG/INFO/WARN/ERROR/CRITICAL)
      service     서비스 이름 (websocket-listener)
      module      Python 모듈명 (logger.name)
      request_id  요청 추적 ID (extra 로 전달, 없으면 생략)
      signal_id   신호 추적 ID (extra 로 전달, 없으면 생략)
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

        # 추적 키 — extra={} 로 전달된 경우에만 포함
        for key in ("request_id", "signal_id", "stk_cd", "error_code"):
            val = getattr(record, key, None)
            if val is not None:
                doc[key] = val

        # 사용자 정의 extra 필드 (빌트인 키 제외)
        for k, v in record.__dict__.items():
            if k not in _BUILTIN_KEYS and k not in doc and not k.startswith("_"):
                doc[k] = v

        # 예외 스택트레이스
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)

        return json.dumps(doc, ensure_ascii=False, default=str)


class _DailyKSTFileHandler(logging.Handler):
    """KST 자정 기준 일별 로테이션 핸들러 — <log_dir>/<name>_YYMMDD.log"""

    def __init__(self, log_dir: str, name: str, backup_count: int = 30, encoding: str = "utf-8"):
        super().__init__()
        self._log_dir = log_dir
        self._name = name
        self._backup_count = backup_count
        self._encoding = encoding
        self._current_date: str = ""
        self._stream = None
        os.makedirs(log_dir, exist_ok=True)
        self._open_new()

    def _today(self) -> str:
        return datetime.now(tz=KST).strftime("%y%m%d")

    def _open_new(self) -> None:
        if self._stream:
            self._stream.flush()
            self._stream.close()
        self._current_date = self._today()
        fpath = os.path.join(self._log_dir, f"{self._name}_{self._current_date}.log")
        self._stream = open(fpath, "a", encoding=self._encoding)
        if self._backup_count > 0:
            files = sorted(glob.glob(os.path.join(self._log_dir, f"{self._name}_??????.log")))
            for old in files[:-self._backup_count]:
                try:
                    os.remove(old)
                except OSError:
                    pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._today() != self._current_date:
                self._open_new()
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self.acquire()
        try:
            if self._stream:
                self._stream.flush()
                self._stream.close()
                self._stream = None
        finally:
            self.release()
        super().close()


def setup_logging(
    service: Optional[str] = None,
    level: str = "INFO",
    log_file: Optional[str] = None,
) -> None:
    """전역 JSON 로깅 초기화 – main() 최초 1회 호출.

    Args:
        service:  서비스 이름 (기본: 환경변수 SERVICE_NAME 또는 "websocket-listener")
        level:    로그 레벨 문자열 (DEBUG / INFO / WARNING / ERROR / CRITICAL)
        log_file: 파일 출력 기준 경로 (None 이면 stdout 만). 디렉터리와 서비스명을
                  자동 추출해 <dir>/<name>_YYMMDD.log 형식으로 일별 로테이션.
    """
    global _SERVICE_NAME
    if service:
        _SERVICE_NAME = service

    fmt = JsonLineFormatter()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_dir = os.path.dirname(log_file) or "."
        name = os.path.splitext(os.path.basename(log_file))[0]
        file_handler = _DailyKSTFileHandler(log_dir, name)
        handlers.append(file_handler)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def get_logger(name: str) -> logging.Logger:
    """모듈별 logger 반환."""
    return logging.getLogger(name)
