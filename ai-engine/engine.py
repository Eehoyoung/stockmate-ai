from __future__ import annotations
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

import asyncpg
import redis.asyncio as aioredis

from health_server import run_health_server
from queue_worker import run_worker
from confirm_worker import run_confirm_worker
from strategy_runner import run_strategy_scanner
from news_scheduler import run_news_scheduler
from monitor_worker import run_monitor
from status_report_worker import run_status_report_worker
from position_monitor import run_position_monitor
from position_reassessment import run_position_reassessment
from overnight_worker import run_overnight_worker
from vi_watch_worker import run_vi_watch_worker
from candidates_builder import run_candidate_builder
from config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD,
    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD, PG_ENABLED,
)
from utils import bool_env

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


async def _init_pg_conn(conn: asyncpg.Connection) -> None:
    await conn.execute("SET TIME ZONE 'Asia/Seoul'")


async def main():
    logger.info("=" * 50)
    logger.info("  StockMate AI – AI Engine 시작")
    logger.info("  Claude 모델: %s", os.getenv("CLAUDE_MODEL", "N/A"))
    logger.info("=" * 50)

    # Claude API 키 확인 – 미설정 시 신호 처리 중 RuntimeError CRASH 발생하므로 기동 차단
    if not os.getenv("CLAUDE_API_KEY"):
        logger.critical("CLAUDE_API_KEY 미설정 – ai-engine 기동 불가. 환경변수를 확인하세요.")
        sys.exit(1)

    # 매도 신호 환경변수 검증
    for _bool_var in ("ENABLE_POSITION_MONITOR", "REVERSAL_CLAUDE_ENABLED"):
        _val = os.getenv(_bool_var, "true").lower()
        if _val not in ("true", "false"):
            logger.warning("%s 값이 'true'/'false'가 아님: '%s' – 기본값 true로 처리", _bool_var, _val)

    for _int_var, _default in (("POSITION_MONITOR_INTERVAL_SEC", "30"), ("REVERSAL_CLAUDE_COOLDOWN_SEC", "120")):
        _raw = os.getenv(_int_var, _default)
        try:
            int(_raw)
        except ValueError:
            logger.critical("%s 값이 정수가 아님: '%s'", _int_var, _raw)
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

    # PostgreSQL 연결 풀 (asyncpg)
    pg_pool = None
    if PG_ENABLED:
        try:
            pg_pool = await asyncpg.create_pool(
                host=PG_HOST, port=PG_PORT, database=PG_DB,
                user=PG_USER, password=PG_PASSWORD,
                min_size=2, max_size=8,
                command_timeout=10,
                init=_init_pg_conn,
            )
            logger.info("[PG] PostgreSQL 풀 생성 완료 → %s:%d/%s", PG_HOST, PG_PORT, PG_DB)
        except Exception as e:
            logger.warning("[PG] PostgreSQL 연결 실패 – DB 쓰기 비활성화: %s", e)
            pg_pool = None

    # 종료 시그널
    loop      = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig, frame=None):
        logger.info("[Engine] 종료 시그널 (%s)", sig)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    enable_confirm      = False
    enable_scanner      = bool_env("ENABLE_STRATEGY_SCANNER",   True)   # S8/S9/S11/S13 Python 전용
    enable_news         = bool_env("NEWS_ENABLED",              True)
    enable_monitor      = bool_env("ENABLE_MONITOR",            True)
    enable_status_report = bool_env("ENABLE_STATUS_REPORT",     True)
    enable_pos_monitor  = bool_env("ENABLE_POSITION_MONITOR",   True)
    enable_pos_reassess = bool_env("ENABLE_POSITION_REASSESSMENT", True)
    enable_overnight    = bool_env("ENABLE_OVERNIGHT_WORKER",   True)
    enable_vi_watch     = bool_env("ENABLE_VI_WATCH_WORKER",    True)   # S2 VI 눌림목 감시
    enable_cand_builder = bool_env("ENABLE_CANDIDATE_BUILDER",  True)   # 후보 풀 적재
    health_port      = int(os.getenv("AI_HEALTH_PORT", "8082"))
    logger.info("[Engine] AI Engine ready – telegram_queue 폴링 시작")
    if enable_confirm:
        logger.info("[Engine] Human Confirm Gate 활성화 (ENABLE_CONFIRM_GATE=true)")
    else:
        logger.warning("[Engine] Human Confirm Gate 비활성화 – Claude 직접 호출 모드")
    if enable_scanner:
        logger.info("[Engine] 전술 스캐너 활성화 (ENABLE_STRATEGY_SCANNER=true)")
    if enable_news:
        logger.info("[Engine] 뉴스 스케쥴러 활성화 (NEWS_ENABLED=true, 주기=%smin)",
                    os.getenv("NEWS_INTERVAL_MIN", "30"))
    if enable_monitor:
        logger.info("[Engine] 데이터 품질 모니터링 활성화 (ENABLE_MONITOR=true, 주기=%ss)",
                    os.getenv("MONITOR_INTERVAL_SEC", "60"))
    if enable_status_report:
        logger.info("[Engine] status report enabled (ENABLE_STATUS_REPORT=true, slots=%s KST)",
                    os.getenv("STATUS_REPORT_SLOTS", "08:30,12:00,15:40"))
    if enable_pos_monitor:
        logger.info("[Engine] 포지션 모니터 활성화 (ENABLE_POSITION_MONITOR=true, 주기=%ss)",
                    os.getenv("POSITION_MONITOR_INTERVAL_SEC", "30"))
    if enable_overnight:
        logger.info("[Engine] 오버나잇 평가 워커 활성화 (ENABLE_OVERNIGHT_WORKER=true)")
    if enable_vi_watch:
        logger.info("[Engine] VI 눌림목 감시 워커 활성화 (ENABLE_VI_WATCH_WORKER=true)")
    if enable_cand_builder:
        logger.info("[Engine] 후보 풀 빌더 활성화 (ENABLE_CANDIDATE_BUILDER=true, 주기=%ss)",
                    os.getenv("CANDIDATE_BUILD_INTERVAL_SEC", "600"))

    tasks = [
        asyncio.create_task(run_worker(rdb, pg_pool)),
        asyncio.create_task(stop_event.wait()),
        asyncio.create_task(run_health_server(health_port, rdb)),
    ]
    if enable_confirm:
        tasks.append(asyncio.create_task(run_confirm_worker(rdb, pg_pool)))
    if enable_scanner:
        tasks.append(asyncio.create_task(run_strategy_scanner(rdb)))
    if enable_news:
        tasks.append(asyncio.create_task(run_news_scheduler(rdb)))
    if enable_monitor:
        tasks.append(asyncio.create_task(run_monitor(rdb)))
    if enable_status_report:
        tasks.append(asyncio.create_task(run_status_report_worker(rdb)))
    if enable_pos_monitor:
        tasks.append(asyncio.create_task(run_position_monitor(rdb, pg_pool)))
    if enable_pos_reassess:
        tasks.append(asyncio.create_task(run_position_reassessment(rdb, pg_pool)))
    if enable_overnight:
        tasks.append(asyncio.create_task(run_overnight_worker(rdb, pg_pool)))
    if enable_vi_watch:
        tasks.append(asyncio.create_task(run_vi_watch_worker(rdb)))
    if enable_cand_builder:
        tasks.append(asyncio.create_task(run_candidate_builder(rdb)))

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()

    await rdb.aclose()
    if pg_pool:
        await pg_pool.close()
        logger.info("[PG] PostgreSQL 풀 종료")
    logger.info("[Engine] 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
