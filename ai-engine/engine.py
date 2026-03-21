"""
ai-engine/engine.py
──────────────────────────────────────────────────────────────
StockMate AI – AI Engine (Python + Claude API)

역할
  1. Java api-orchestrator 가 LPUSH 한 telegram_queue 를 폴링
  2. 규칙 기반 1차 스코어링 → Claude API 2차 분석
  3. 분석 결과를 ai_scored_queue 에 발행
  4. Telegram Bot (Node.js) 가 ai_scored_queue 를 폴링하여 메시지 발송

실행
  python engine.py
"""

import asyncio
import logging
import os
import signal
import sys

import redis.asyncio as aioredis
from dotenv import load_dotenv

from aiohttp import web
from queue_worker import run_worker
from strategy_runner import run_strategy_scanner

load_dotenv()

# ── 로깅 설정 ────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/ai-engine.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("engine")

# ── Redis 설정 ────────────────────────────────────────────────
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None


async def _run_health_server(port: int, rdb):
    """간단한 /health HTTP 엔드포인트 제공"""
    import time
    _start_time = time.time()

    async def _health_handler(request):
        try:
            await rdb.ping()
            redis_ok = True
        except Exception:
            redis_ok = False
        status_str = "UP" if redis_ok else "DEGRADED"
        body = {
            "status": status_str,
            "service": "stockmate-ai-engine",
            "redis_connected": redis_ok,
            "uptime_sec": int(time.time() - _start_time),
            "claude_model": os.getenv("CLAUDE_MODEL", "N/A"),
        }
        return web.json_response(body, status=200 if redis_ok else 503)

    app = web.Application()
    app.router.add_get("/health", _health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("[Health] AI Engine 헬스체크 서버 시작 → http://0.0.0.0:%d/health", port)


async def main():
    logger.info("=" * 50)
    logger.info("  StockMate AI – AI Engine 시작")
    logger.info("  Claude 모델: %s", os.getenv("CLAUDE_MODEL", "N/A"))
    logger.info("=" * 50)

    # Claude API 키 확인
    if not os.getenv("CLAUDE_API_KEY"):
        logger.critical("CLAUDE_API_KEY 환경변수 미설정 – 종료")
        sys.exit(1)

    # Redis 연결
    rdb = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
        decode_responses=True, socket_connect_timeout=5,
        socket_timeout=5, retry_on_timeout=True,
    )
    try:
        await rdb.ping()
        logger.info("[Redis] 연결 성공 → %s:%d", REDIS_HOST, REDIS_PORT)
    except Exception as e:
        logger.critical("[Redis] 연결 실패: %s", e)
        sys.exit(1)

    # 종료 시그널
    loop      = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig, frame=None):
        logger.info("[Engine] 종료 시그널 (%s)", sig)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    enable_scanner = os.getenv("ENABLE_STRATEGY_SCANNER", "false").lower() == "true"
    health_port = int(os.getenv("AI_HEALTH_PORT", "8082"))
    logger.info("[Engine] AI Engine ready – telegram_queue 폴링 시작")
    if enable_scanner:
        logger.info("[Engine] 전술 스캐너 활성화 (ENABLE_STRATEGY_SCANNER=true)")

    tasks = [
        asyncio.create_task(run_worker(rdb)),
        asyncio.create_task(stop_event.wait()),
        asyncio.create_task(_run_health_server(health_port, rdb)),
    ]
    if enable_scanner:
        tasks.append(asyncio.create_task(run_strategy_scanner(rdb)))

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()

    await rdb.aclose()
    logger.info("[Engine] 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
