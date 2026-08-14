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
                "strategy_session_fail_open": _env_flag("STRATEGY_SESSION_FAIL_OPEN", "false"),
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
        strategies = [f"s{n}" for n in range(1, 17)]
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

    async def _strategy_run_handler(request):
        """관리자 대시보드의 '전략 수동 실행' 패널이 호출하는 엔드포인트.
        S8/S9/S11/S13~S16처럼 Java api-orchestrator에 대응 /run 엔드포인트가 없는
        Python 전용 전략을 즉시 1회 스캔한다. api-orchestrator가 서버사이드로 프록시한다."""
        from strategy_runner import run_manual_scan

        code = request.match_info.get("code", "").strip()
        try:
            result = await run_manual_scan(rdb, code)
        except Exception as e:
            logger.error("[Health] /strategy/%s/run error: %s", code, e)
            return web.json_response({"error": str(e)}, status=500)

        if "error" in result:
            return web.json_response(result, status=400)
        return web.json_response(result)

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
        from claude_analyst import analyze_stock_for_user

        stk_cd = request.match_info.get("stk_cd", "").strip()
        if not stk_cd or not stk_cd.isdigit() or len(stk_cd) != 6:
            return web.json_response({"error": "6-digit stock code required"}, status=400)

        enable_ai = request.rel_url.query.get("ai", "true").lower() != "false"
        refresh = request.rel_url.query.get("refresh", "false").lower() in {"1", "true", "yes", "on"}
        cache_ttl = int(os.getenv("SCORE_COMMAND_CACHE_TTL_SEC", "60"))
        claude_cache_key = f"score:command:claude:{stk_cd}"
        try:
            if enable_ai:
                claude_used_cache = False
                cached = None
                try:
                    if not refresh and cache_ttl > 0:
                        cached = await rdb.get(claude_cache_key)
                    if cached:
                        if isinstance(cached, bytes):
                            cached = cached.decode("utf-8")
                        loaded = json.loads(cached)
                        if isinstance(loaded, dict):
                            claude_result = loaded
                            claude_used_cache = True
                        else:
                            claude_result = None
                    else:
                        claude_result = None
                except Exception as exc:
                    logger.debug("[Health] /score/%s claude cache read failed: %s", stk_cd, exc)
                    cached = None
                    claude_used_cache = False
                    claude_result = None

                if claude_used_cache:
                    try:
                        score_result = await score_stock_strategies(stk_cd, rdb, enable_ai=enable_ai)
                    except Exception as exc:
                        score_result = exc
                else:
                    score_result, claude_result = await asyncio.gather(
                        score_stock_strategies(stk_cd, rdb, enable_ai=enable_ai),
                        analyze_stock_for_user(rdb, stk_cd),
                        return_exceptions=True,
                    )
            else:
                try:
                    score_result = await score_stock_strategies(stk_cd, rdb, enable_ai=False)
                except Exception as exc:
                    score_result = exc
                claude_result = {}
                claude_used_cache = False
            if isinstance(score_result, Exception):
                logger.error("[Health] /score/%s score error: %s", stk_cd, score_result)
                score_result = {"stk_cd": stk_cd, "results": [], "no_match": True, "error": str(score_result)}
            if isinstance(claude_result, Exception):
                logger.error("[Health] /score/%s claude error: %s", stk_cd, claude_result)
                claude_result = {"error": str(claude_result)}

            if enable_ai:
                score_result["claude_full"] = {
                    "action":            claude_result.get("action"),
                    "confidence":        claude_result.get("confidence"),
                    "reasons":           claude_result.get("reasons", []),
                    "risk_factors":      claude_result.get("risk_factors", []),
                    "action_guide":      claude_result.get("action_guide", []),
                    "tp_sl":             claude_result.get("tp_sl"),
                    "summary":           claude_result.get("summary"),
                    "claude_analysis":   claude_result.get("claude_analysis"),
                    "daily_indicators":  claude_result.get("daily_indicators"),
                    "minute_indicators": claude_result.get("minute_indicators"),
                    "strategies_in_pool":claude_result.get("strategies_in_pool", []),
                    "cur_prc":           claude_result.get("cur_prc"),
                    "flu_rt":            claude_result.get("flu_rt"),
                    "cntr_str":          claude_result.get("cntr_str"),
                    "hoga":              claude_result.get("hoga"),
                    "stk_nm":            claude_result.get("stk_nm"),
                    "error":             claude_result.get("error"),
                }
            else:
                score_result["claude_full"] = {"error": "skipped_fast_mode"}
            score_result["score_mode"] = "deep" if enable_ai else "fast"
            score_result["used_cache"] = claude_used_cache
            score_result["cache_scope"] = "claude_only" if enable_ai else "none"
            if enable_ai and cache_ttl > 0 and not score_result.get("error") and not claude_result.get("error") and not claude_used_cache:
                try:
                    await rdb.set(
                        claude_cache_key,
                        json.dumps(claude_result, ensure_ascii=False, default=str),
                        ex=cache_ttl,
                    )
                except Exception as cache_error:
                    logger.debug("[Health] /score/%s cache write failed: %s", stk_cd, cache_error)
            return web.json_response(
                score_result,
                dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.error("[Health] /score/%s error: %s", stk_cd, e)
            return web.json_response({"error": str(e)}, status=500)

    async def _news_brief_handler(request):
        from news_scheduler import build_live_brief

        slot = request.rel_url.query.get("slot")
        refresh = request.rel_url.query.get("refresh", "false").lower() in {"1", "true", "yes", "on"}
        allow_ai = request.rel_url.query.get("ai", "false").lower() in {"1", "true", "yes", "on", "deep"}
        try:
            result = await build_live_brief(rdb, slot_name=slot, publish_queue=False, force_refresh=refresh, allow_ai=allow_ai)
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
    app.router.add_post("/strategy/{code}/run", _strategy_run_handler)
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
