"""
health_server.py
경량 aiohttp 서버 – 도커 헬스체크용 GET /health 제공.

A2 헬스체크 정밀화:
  - Redis ping latency, 큐 lag(ai_scored_queue / telegram_queue), last_message_time
  - ws_connected=false 시 disconnect_reason 원인코드 노출
  - 텔레그램 전송기 최근 성공/실패 시각 노출
  - status: UP / DEGRADED / DOWN 3단계 구분
"""

import asyncio
import time
import logging

from aiohttp import web

logger = logging.getLogger(__name__)

# ── 공유 상태 (다른 모듈에서 setter 로 갱신) ─────────────────────

_ws_connected: bool            = False
_disconnect_reason: str        = ""        # 예: "ConnectionClosed:1001", "OSError", "LoginFailed"
_last_message_time: float | None = None    # monotonic timestamp
_start_time: float | None      = None

# Redis 인스턴스 참조 (main.py 가 주입)
_rdb = None

# 텔레그램 전송기 상태
_tg_last_success_at: float | None = None   # monotonic
_tg_last_error_at:   float | None = None
_tg_last_error_msg:  str          = ""


# ── Public setter API ────────────────────────────────────────

def set_ws_connected(value: bool, reason: str = "") -> None:
    """WS 연결 상태 갱신. 연결 해제 시 reason 원인코드 전달."""
    global _ws_connected, _disconnect_reason
    _ws_connected = value
    if not value and reason:
        _disconnect_reason = reason
    elif value:
        _disconnect_reason = ""


def record_message_received() -> None:
    """실시간 메시지 수신 시 호출 – last_message_time 갱신."""
    global _last_message_time
    _last_message_time = time.monotonic()


def set_redis(rdb) -> None:
    """Redis 클라이언트 주입 (main.py 에서 호출)."""
    global _rdb
    _rdb = rdb


def record_tg_success() -> None:
    """텔레그램 전송 성공 시 호출."""
    global _tg_last_success_at
    _tg_last_success_at = time.monotonic()


def record_tg_error(msg: str = "") -> None:
    """텔레그램 전송 실패 시 호출."""
    global _tg_last_error_at, _tg_last_error_msg
    _tg_last_error_at  = time.monotonic()
    _tg_last_error_msg = msg


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _mono_to_ago_sec(ts: float | None) -> float | None:
    """monotonic timestamp → '몇 초 전' 변환. None 이면 None 반환."""
    if ts is None:
        return None
    return round(time.monotonic() - ts, 1)


async def _check_redis() -> dict:
    """Redis ping latency 및 큐 lag 측정."""
    if _rdb is None:
        return {"ok": False, "ping_ms": None, "reason": "rdb_not_injected"}
    try:
        t0 = time.monotonic()
        await _rdb.ping()
        ping_ms = round((time.monotonic() - t0) * 1000, 1)

        # 큐 길이 (lag)
        ai_lag  = await _rdb.llen("ai_scored_queue")
        tg_lag  = await _rdb.llen("telegram_queue")

        return {
            "ok":             True,
            "ping_ms":        ping_ms,
            "ai_scored_queue_lag": int(ai_lag),
            "telegram_queue_lag":  int(tg_lag),
        }
    except Exception as e:
        return {"ok": False, "ping_ms": None, "reason": str(e)}


# ── /health 핸들러 ───────────────────────────────────────────

async def _health_handler(request):
    uptime = int(time.monotonic() - _start_time) if _start_time is not None else 0
    redis_info = await _check_redis()

    # last_message_time
    last_msg_ago = _mono_to_ago_sec(_last_message_time)

    # 텔레그램 전송기 상태
    tg_info = {
        "last_success_ago_sec": _mono_to_ago_sec(_tg_last_success_at),
        "last_error_ago_sec":   _mono_to_ago_sec(_tg_last_error_at),
        "last_error_msg":       _tg_last_error_msg or None,
    }

    # WS 연결 상태
    ws_info: dict = {"connected": _ws_connected}
    if not _ws_connected and _disconnect_reason:
        ws_info["disconnect_reason"] = _disconnect_reason

    # 전체 상태 판단
    # UP       : WS 연결 + Redis OK
    # DEGRADED : WS 연결 + Redis 이상 | WS 끊김 + Redis OK
    # DOWN     : WS 끊김 + Redis 이상
    if _ws_connected and redis_info["ok"]:
        overall = "UP"
    elif not _ws_connected and not redis_info["ok"]:
        overall = "DOWN"
    else:
        overall = "DEGRADED"

    body = {
        "status":             overall,
        "service":            "stockmate-websocket-listener",
        "uptime_sec":         uptime,
        "websocket":          ws_info,
        "redis":              redis_info,
        "last_message_ago_sec": last_msg_ago,
        "telegram_sender":    tg_info,
    }

    # HTTP 상태코드: UP=200, DEGRADED=200(운영 판단 가능), DOWN=503
    http_status = 503 if overall == "DOWN" else 200
    return web.json_response(body, status=http_status)


# ── 서버 실행 ────────────────────────────────────────────────

async def run_health_server(port: int = 8081):
    """백그라운드로 실행되는 헬스체크 HTTP 서버 (종료 시그널까지 블로킹)."""
    global _start_time
    _start_time = time.monotonic()

    app = web.Application()
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("[Health] 헬스체크 서버 시작 → http://localhost:%d/health", port)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
