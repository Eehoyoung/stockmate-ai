from __future__ import annotations

"""
ai-engine/health_server.py

AI Engine HTTP health/status server.
"""

import asyncio
import json
import logging
import os
import time

from aiohttp import web

logger = logging.getLogger("health_server")


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


async def run_health_server(port: int, rdb) -> None:
    """
    Exposes /health, /candidates, /analyze/{stk_cd}, /score/{stk_cd}, /news/brief.
    """
    start_time = time.time()

    async def _health_handler(request):
        try:
            await rdb.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

        # ws:db_writer:event_mode
        try:
            ws_db_writer_event_mode = await rdb.get("ws:db_writer:event_mode") or "unknown"
        except Exception:
            ws_db_writer_event_mode = "error"

        # open_positions 크기 (set 타입 기준 scard)
        try:
            pos_type = await rdb.type("open_positions")
            if pos_type == "set":
                position_count = await rdb.scard("open_positions")
            elif pos_type == "hash":
                position_count = await rdb.hlen("open_positions")
            elif pos_type == "none":
                position_count = 0
            else:
                position_count = -1
        except Exception:
            position_count = -1

        # 큐 백로그
        queue_backlog: dict[str, int] = {}
        for _qkey in ("telegram_queue", "ai_scored_queue"):
            try:
                queue_backlog[_qkey] = await rdb.llen(_qkey)
            except Exception:
                queue_backlog[_qkey] = -1

        body = {
            "status": "UP" if redis_ok else "DEGRADED",
            "service": "stockmate-ai-engine",
            "redis_connected": redis_ok,
            "uptime_sec": int(time.time() - start_time),
            "claude_model": os.getenv("CLAUDE_MODEL", "N/A"),
            "session_controls": {
                "strategy_session_filter": _env_flag("ENABLE_STRATEGY_SESSION_FILTER"),
                "strategy_session_dry_run": _env_flag("STRATEGY_SESSION_DRY_RUN"),
                "strategy_session_fail_open": _env_flag("STRATEGY_SESSION_FAIL_OPEN", "true"),
                "session_enter_guard": _env_flag("SESSION_ENTER_GUARD_ENABLED"),
                "bypass_market_hours": _env_flag("BYPASS_MARKET_HOURS"),
            },
            "ws_db_writer_event_mode": ws_db_writer_event_mode,
            "position_count": position_count,
            "queue_backlog": queue_backlog,
        }
        return web.json_response(body, status=200 if redis_ok else 503)

    async def _candidates_handler(request):
        markets = ["001", "101"]
        strategies = [f"s{n}" for n in range(1, 16)]
        pool_status = {}
        try:
            for strategy in strategies:
                for market in markets:
                    key = f"candidates:{strategy}:{market}"
                    count = await rdb.llen(key)
                    if count > 0:
                        pool_status[key] = count
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

        return web.json_response({
            "total_candidates": sum(pool_status.values()),
            "pools": pool_status,
        })

    async def _analyze_handler(request):
        from claude_analyst import analyze_stock_for_user

        stk_cd = request.match_info.get("stk_cd", "").strip()
        if not stk_cd or not stk_cd.isdigit() or len(stk_cd) != 6:
            return web.json_response({"error": "6-digit stock code required"}, status=400)

        try:
            result = await analyze_stock_for_user(rdb, stk_cd)
            return web.json_response(result)
        except Exception as e:
            logger.error("[Health] /analyze/%s error: %s", stk_cd, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _score_handler(request):
        from stockScore import score_stock as score_stock_strategies

        stk_cd = request.match_info.get("stk_cd", "").strip()
        if not stk_cd or not stk_cd.isdigit() or len(stk_cd) != 6:
            return web.json_response({"error": "6-digit stock code required"}, status=400)

        enable_ai = request.rel_url.query.get("ai", "true").lower() != "false"
        try:
            result = await score_stock_strategies(stk_cd, rdb, enable_ai=enable_ai)
            return web.json_response(
                result,
                dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.error("[Health] /score/%s error: %s", stk_cd, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _news_brief_handler(request):
        from news_scheduler import build_live_brief

        slot = request.rel_url.query.get("slot")
        try:
            result = await build_live_brief(rdb, slot_name=slot, publish_queue=False)
            return web.json_response(
                result,
                dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.error("[Health] /news/brief error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/candidates", _candidates_handler)
    app.router.add_get("/analyze/{stk_cd}", _analyze_handler)
    app.router.add_get("/score/{stk_cd}", _score_handler)
    app.router.add_get("/news/brief", _news_brief_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("[Health] AI Engine health server started on http://localhost:%d/health", port)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
