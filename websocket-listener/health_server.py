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
    uptime = int(time.time() - _start_time) if _start_time else 0
    body = {
        "status":       "UP" if _ws_connected else "DEGRADED",
        "ws_connected": _ws_connected,
        "uptime_sec":   uptime,
        "service":      "stockmate-websocket-listener",
    }
    status = 200 if _ws_connected else 503
    return web.json_response(body, status=status)


async def run_health_server(port: int = 8081):
    """백그라운드로 실행되는 헬스체크 HTTP 서버"""
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
