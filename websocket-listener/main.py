"""
websocket-listener/main.py
──────────────────────────────────────────────────────────────
StockMate AI – 키움 WebSocket 리스너 (Python)

역할
  • Java api-orchestrator 와 협력하여 실시간 시세를 Redis 에 저장
  • Java GRP 1~4 와 충돌 방지: GRP 5~8 사용
  • 수신 타입: 0B 체결, 0H 예상체결, 0D 호가잔량, 1h VI 발동/해제
  • vi_watch_queue 에 VI 해제 종목 등록 (S2 전술 지원)

실행
  python main.py
"""

import asyncio
import os
import signal
import sys

import redis.asyncio as aioredis
from dotenv import load_dotenv

from health_server import run_health_server, set_redis
from logger import get_logger, setup_logging
from ws_client import run_ws_loop

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# ── JSON 구조화 로깅 초기화 ───────────────────────────────────
setup_logging(
    service="websocket-listener",
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_file="logs/websocket-listener.log",
)
logger = get_logger("main")

# ── Redis 설정 ────────────────────────────────────────────────
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
HEALTH_PORT    = int(os.getenv("HEALTH_PORT", "8081"))


async def main():
    logger.info("=" * 50)
    logger.info("  StockMate AI – WebSocket Listener 시작")
    logger.info("=" * 50)

    # Redis 연결
    rdb = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
        decode_responses=True, socket_connect_timeout=5,
        socket_timeout=5, retry_on_timeout=True,
    )
    try:
        await rdb.ping()
        logger.info("[Redis] 연결 성공 → %s:%d", REDIS_HOST, REDIS_PORT)
        set_redis(rdb)   # 헬스체크 서버에 Redis 클라이언트 주입
    except Exception as e:
        logger.critical("[Redis] 연결 실패: %s", e)
        sys.exit(1)

    # 종료 시그널 핸들러
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig, frame=None):
        logger.info("[Main] 종료 시그널 수신 (%s)", sig)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 헬스체크 서버 + WebSocket 루프 동시 실행
    ws_task     = asyncio.create_task(run_ws_loop(rdb))
    health_task = asyncio.create_task(run_health_server(HEALTH_PORT))
    stop_task   = asyncio.create_task(stop_event.wait())

    try:
        done, pending = await asyncio.wait(
            [ws_task, health_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        await rdb.aclose()
        logger.info("[Main] 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
