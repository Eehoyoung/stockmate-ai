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
from dotenv import load_dotenv

from aiohttp import web
from queue_worker import run_worker
from confirm_worker import run_confirm_worker
from strategy_runner import run_strategy_scanner
from news_scheduler import run_news_scheduler
from monitor_worker import run_monitor
from overnight_worker import run_overnight_worker
from vi_watch_worker import run_vi_watch_worker
from candidates_builder import run_candidate_builder
from claude_analyst import analyze_stock_for_user
from stockScore import score_stock as score_stock_strategies

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

# ── Redis 설정 ─────────────────────────────────────────────────
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None

# ── PostgreSQL 설정 ─────────────────────────────────────────────
PG_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
PG_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB       = os.getenv("POSTGRES_DB",       "SMA")
PG_USER     = os.getenv("POSTGRES_USER",     "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
PG_ENABLED  = os.getenv("PG_WRITER_ENABLED", "true").lower() == "true"


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

    async def _candidates_handler(request):
        """
        /candidates — 전략별 Redis 후보 풀 현황 반환
        candidates:s{N}:{market} 키 목록과 종목 수를 JSON으로 응답.
        """
        MARKETS = ["001", "101"]
        STRATEGIES = [f"s{n}" for n in range(1, 16)]
        pool_status = {}
        try:
            for s in STRATEGIES:
                for mkt in MARKETS:
                    key = f"candidates:{s}:{mkt}"
                    count = await rdb.llen(key)
                    if count > 0:
                        pool_status[key] = count
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

        total = sum(pool_status.values())
        return web.json_response({
            "total_candidates": total,
            "pools": pool_status,
        })

    async def _analyze_handler(request):
        """
        /analyze/{stk_cd} — /claude 텔레그램 명령어 전용 종목 종합 분석
        Claude API 를 호출하여 기술적 분석 + 전략 후보 풀 정보 반환.
        """
        stk_cd = request.match_info.get("stk_cd", "").strip()
        if not stk_cd or not stk_cd.isdigit() or len(stk_cd) != 6:
            return web.json_response({"error": "6자리 숫자 종목코드 필요"}, status=400)
        try:
            result = await analyze_stock_for_user(rdb, stk_cd)
            return web.json_response(result)
        except Exception as e:
            logger.error("[Health] /analyze/%s 오류: %s", stk_cd, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _score_handler(request):
        """
        /score/{stk_cd} — /score 텔레그램 명령어 전용 15전략 심사 + AI 스코어링.
        S1~S15 전략 조건 경량 심사 → 매칭 전략 규칙/AI 점수 반환.
        Query param: ai=false 로 AI 스코어링 비활성화 (빠른 규칙 점수만).
        """
        stk_cd = request.match_info.get("stk_cd", "").strip()
        if not stk_cd or not stk_cd.isdigit() or len(stk_cd) != 6:
            return web.json_response({"error": "6자리 숫자 종목코드 필요"}, status=400)
        enable_ai = request.rel_url.query.get("ai", "true").lower() != "false"
        try:
            result = await score_stock_strategies(stk_cd, rdb, enable_ai=enable_ai)
            return web.json_response(result, dumps=lambda o: __import__("json").dumps(o, ensure_ascii=False, default=str))
        except Exception as e:
            logger.error("[Health] /score/%s 오류: %s", stk_cd, e)
            return web.json_response({"error": str(e)}, status=500)

    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/candidates", _candidates_handler)
    app.router.add_get("/analyze/{stk_cd}", _analyze_handler)
    app.router.add_get("/score/{stk_cd}", _score_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("[Health] AI Engine 헬스체크 서버 시작 → http://localhost:%d/health", port)

    # 서버를 계속 실행 (태스크 취소 시 자동 종료)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def main():
    logger.info("=" * 50)
    logger.info("  StockMate AI – AI Engine 시작")
    logger.info("  Claude 모델: %s", os.getenv("CLAUDE_MODEL", "N/A"))
    logger.info("=" * 50)

    # Claude API 키 확인 (미설정 시 rule_score 단독 모드로 계속 실행)
    if not os.getenv("CLAUDE_API_KEY"):
        logger.warning(
            "CLAUDE_API_KEY 미설정 – news_scheduler/confirm_gate 기능 제한됨. "
            "규칙 기반 신호 흐름(rule_score)은 정상 동작."
        )

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

    enable_confirm   = os.getenv("ENABLE_CONFIRM_GATE",      "false").lower() == "true"
    enable_scanner   = os.getenv("ENABLE_STRATEGY_SCANNER", "true").lower()  == "true"  # S8/S9/S11/S13 Python 전용
    enable_news      = os.getenv("NEWS_ENABLED",            "true").lower()  == "true"
    enable_monitor   = os.getenv("ENABLE_MONITOR",          "true").lower()  == "true"
    enable_overnight = os.getenv("ENABLE_OVERNIGHT_WORKER", "true").lower()  == "true"
    enable_vi_watch       = os.getenv("ENABLE_VI_WATCH_WORKER",  "true").lower()  == "true"  # S2 VI 눌림목 감시
    enable_cand_builder   = os.getenv("ENABLE_CANDIDATE_BUILDER", "true").lower()  == "true"  # 후보 풀 적재
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
        asyncio.create_task(_run_health_server(health_port, rdb)),
    ]
    if enable_confirm:
        tasks.append(asyncio.create_task(run_confirm_worker(rdb)))
    if enable_scanner:
        tasks.append(asyncio.create_task(run_strategy_scanner(rdb)))
    if enable_news:
        tasks.append(asyncio.create_task(run_news_scheduler(rdb)))
    if enable_monitor:
        tasks.append(asyncio.create_task(run_monitor(rdb)))
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
