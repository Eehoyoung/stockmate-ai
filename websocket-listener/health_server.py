"""
health_server.py
경량 aiohttp 서버 – 도커 헬스체크용 GET /health 제공.
"""

import asyncio
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

_ws_connected = False
_start_time   = None


def set_ws_connected(value: bool):
    global _ws_connected
    _ws_connected = value


async def _health_handler(request):
    import time
    uptime = int(time.time() - _start_time) if _start_time is not None else 0
    body = {
        "status":       "UP" if _ws_connected else "DEGRADED",
        "ws_connected": _ws_connected,
        "uptime_sec":   uptime,
        "service":      "stockmate-websocket-listener",
    }
    status_code = 200 if _ws_connected else 503
    return web.json_response(body, status=status_code)


async def run_health_server(port: int = 8081):
    """백그라운드로 실행되는 헬스체크 HTTP 서버 (종료 시그널까지 블로킹)"""
    import asyncio
    import time
    global _start_time
    _start_time = time.time()

    app = web.Application()
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("[Health] 헬스체크 서버 시작 → http://0.0.0.0:%d/health", port)

    # 서버를 계속 실행 (태스크 취소 시 자동 종료)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
