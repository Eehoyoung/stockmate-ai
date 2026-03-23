"""
confirm_worker.py
인간 컨펌 완료 신호를 confirmed_queue 에서 꺼내 Claude API 분석 후
ai_scored_queue 에 발행하는 워커.
"""

import asyncio
import logging

from analyzer import analyze_signal, _fallback
from redis_reader import pop_confirmed_queue, push_score_only_queue
from scorer import check_daily_limit

logger = logging.getLogger(__name__)


async def process_confirmed(rdb) -> bool:
    """
    confirmed_queue 에서 항목 1개 처리.
    처리 항목이 있으면 True, 없으면 False 반환.
    """
    item = await pop_confirmed_queue(rdb)
    if not item:
        return False

    stk_cd   = item.get("stk_cd", "")
    strategy = item.get("strategy", "")
    r_score  = float(item.get("rule_score", 0))
    ctx      = item.get("market_ctx", {})

    logger.info("[ConfirmWorker] Claude 분석 시작 [%s %s] rule_score=%.1f", stk_cd, strategy, r_score)

    try:
        within_limit = await check_daily_limit(rdb)
        if not within_limit:
            result = _fallback(r_score)
            result["reason"] = "일별 Claude 호출 상한 초과 – 규칙 스코어 기반 처리"
        else:
            try:
                result = await analyze_signal(item, ctx, r_score, rdb=rdb)
            except Exception as claude_err:
                logger.warning(
                    "[ConfirmWorker] Claude 오류 [%s %s]: %s – 규칙 폴백",
                    stk_cd, strategy, claude_err
                )
                result = _fallback(r_score)
                result["reason"] = f"Claude API 오류 – 규칙 스코어 기반 처리: {claude_err}"

        enriched = {
            **item,
            "ai_score":            result.get("ai_score", r_score),
            "action":              result.get("action", "HOLD"),
            "confidence":          result.get("confidence", "LOW"),
            "ai_reason":           result.get("reason", ""),
            "adjusted_target_pct": result.get("adjusted_target_pct"),
            "adjusted_stop_pct":   result.get("adjusted_stop_pct"),
            "human_confirmed":     True,
        }
        # market_ctx 는 큰 데이터이므로 발행 전 제거
        enriched.pop("market_ctx", None)
        await push_score_only_queue(rdb, enriched)
        logger.info(
            "[ConfirmWorker] 발행 완료 [%s %s] action=%s ai_score=%.1f",
            stk_cd, strategy, enriched["action"], enriched["ai_score"]
        )

    except Exception as e:
        logger.error("[ConfirmWorker] 처리 오류 [%s %s]: %s", stk_cd, strategy, e)

    return True


async def run_confirm_worker(rdb):
    """confirmed_queue 폴링 루프"""
    logger.info("[ConfirmWorker] 시작")
    consecutive_empty = 0

    while True:
        try:
            processed = await process_confirmed(rdb)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                wait = min(1.0 * (1 + consecutive_empty * 0.1), 5.0)
                await asyncio.sleep(wait)
        except Exception as e:
            logger.error("[ConfirmWorker] 루프 오류: %s", e)
            await asyncio.sleep(5)
