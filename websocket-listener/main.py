"""
Entrypoint for websocket-listener.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import asyncpg
import redis.asyncio as aioredis
from dotenv import load_dotenv

from health_server import run_health_server, set_redis
from logger import get_logger, setup_logging
from ws_client import run_ws_loop

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

setup_logging(
    service="websocket-listener",
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_file="logs/websocket-listener.log",
)
logger = get_logger("main")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8081"))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "stockmate")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
PG_WRITER_ENABLED = os.getenv("PG_WRITER_ENABLED", "true").lower() in ("1", "true", "yes")


async def _init_pg_conn(conn: asyncpg.Connection):
    await conn.execute("SET TIME ZONE 'Asia/Seoul'")


async def _create_pg_pool():
    if not PG_WRITER_ENABLED:
        logger.info("[Postgres] direct event writer disabled")
        return None
    try:
        pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            min_size=1,
            max_size=4,
            command_timeout=5,
            init=_init_pg_conn,
        )
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        logger.info("[Postgres] connected for event persistence %s:%d/%s", POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)
        return pool
    except Exception as e:
        logger.warning("[Postgres] direct event writer unavailable: %s", e)
        return None


async def main():
    logger.info("=" * 50)
    logger.info("  StockMate AI WebSocket Listener start")
    logger.info("=" * 50)

    rdb = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    try:
        await rdb.ping()
        logger.info("[Redis] connected %s:%d", REDIS_HOST, REDIS_PORT)
        set_redis(rdb)
    except Exception as e:
        logger.critical("[Redis] connection failed: %s", e)
        sys.exit(1)

    pg_pool = await _create_pg_pool()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig, frame=None):
        logger.info("[Main] shutdown signal received (%s)", sig)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    ws_task = asyncio.create_task(run_ws_loop(rdb, pg_pool))
    health_task = asyncio.create_task(run_health_server(HEALTH_PORT))
    stop_task = asyncio.create_task(stop_event.wait())

    try:
        done, pending = await asyncio.wait(
            [ws_task, health_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                raise task.exception()
    finally:
        if pg_pool is not None:
            await pg_pool.close()
        await rdb.aclose()
        logger.info("[Main] shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
