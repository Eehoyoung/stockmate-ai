"""
queue_worker.py
telegram_queue 를 폴링하여 신호를 꺼내고 AI 분석 후 재발행하는 워커.

흐름:
  Java SignalService
    → LPUSH telegram_queue {id, stk_cd, strategy, message, ...}
  AI Engine (이 파일)
    → RPOP telegram_queue
    → 규칙 1차 스코어링 (scorer.py)
    → Claude 분석 (analyzer.py)
    → LPUSH ai_scored_queue {원본 + ai_score, action, reason}
  Telegram Bot (Node.js)
    → RPOP ai_scored_queue
    → 조건 충족 시 텔레그램 메시지 발송
"""

import asyncio
import logging
import os

from analyzer import analyze_signal, _fallback
from redis_reader import (
    pop_telegram_queue,
    get_tick_data,
    get_hoga_data,
    get_avg_cntr_strength,
    get_vi_status,
    push_score_only_queue,
)
from scorer import rule_score, should_skip_ai, check_daily_limit

logger      = logging.getLogger(__name__)
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SEC", "2.0"))


async def _build_market_ctx(rdb, stk_cd: str) -> dict:
    tick, hoga, strength, vi = await asyncio.gather(
        get_tick_data(rdb, stk_cd),
        get_hoga_data(rdb, stk_cd),
        get_avg_cntr_strength(rdb, stk_cd, 5),
        get_vi_status(rdb, stk_cd),
    )
    return {"tick": tick, "hoga": hoga, "strength": strength, "vi": vi}


async def process_one(rdb) -> bool:
    """
    큐에서 항목 1개 처리.
    처리 항목이 있으면 True, 없으면 False 반환.
    """
    item = await pop_telegram_queue(rdb)
    if not item:
        return False

    # 특수 메시지 타입은 AI 분석 없이 바로 ai_scored_queue 로 전달
    item_type = item.get("type", "")
    if item_type in ("FORCE_CLOSE", "DAILY_REPORT"):
        await push_score_only_queue(rdb, item)
        logger.debug("[Worker] 특수 타입 통과 [%s]", item_type)
        return True

    stk_cd   = item.get("stk_cd", "")
    strategy = item.get("strategy", "")
    signal   = item  # signal 필드들이 item 안에 flat하게 있음

    try:
        # 0. 뉴스 기반 매매 중단 여부 확인 (PAUSE 시 즉시 CANCEL)
        try:
            news_control = await rdb.get("news:trading_control")
            if news_control and news_control.upper() == "PAUSE":
                reason = await rdb.get("news:analysis")
                pause_reason = "뉴스 분석 결과 매매 중단"
                try:
                    import json as _json
                    analysis = _json.loads(reason or "{}")
                    pause_reason = analysis.get("summary", pause_reason)
                except Exception:
                    pass
                result = {
                    "action":     "CANCEL",
                    "ai_score":   0.0,
                    "confidence": "HIGH",
                    "reason":     f"뉴스 기반 매매 중단 상태 – {pause_reason}",
                }
                await push_score_only_queue(rdb, {**item, **result, "rule_score": 0.0})
                logger.info("[Worker] 뉴스 PAUSE – 신호 취소 [%s %s]", stk_cd, strategy)
                return True
        except Exception as news_err:
            logger.debug("[Worker] 뉴스 제어 확인 실패 (무시): %s", news_err)

        # 1. 실시간 시세 수집
        ctx = await _build_market_ctx(rdb, stk_cd)

        # 2. 규칙 기반 1차 스코어링
        r_score = rule_score(signal, ctx)
        logger.info("[Worker] 1차 스코어 [%s %s]: %.1f", stk_cd, strategy, r_score)

        # 3. 전략별 임계값 미달 → Claude 호출 없이 CANCEL
        if should_skip_ai(r_score, strategy):
            result = {
                "action":     "CANCEL",
                "ai_score":   r_score,
                "confidence": "LOW",
                "reason":     f"1차 스코어 {r_score}점 미달 – 진입 취소",
            }
        else:
            # 4. 일별 호출 상한 확인
            within_limit = await check_daily_limit(rdb)
            if not within_limit:
                # 상한 초과 시 규칙 스코어만으로 발행
                result = _fallback(r_score)
                result["reason"] = "일별 Claude 호출 상한 초과 – 규칙 스코어 기반 처리"
            else:
                # 5. Claude API 분석
                try:
                    result = await analyze_signal(signal, ctx, r_score, rdb=rdb)
                except Exception as claude_err:
                    logger.warning("[Worker] Claude API 오류 [%s %s]: %s – 규칙 스코어로 대체",
                                   stk_cd, strategy, claude_err)
                    result = _fallback(r_score)
                    result["reason"] = f"Claude API 오류 – 규칙 스코어 기반 처리: {claude_err}"

        # 6. 결과 합산 후 ai_scored_queue 에 발행
        enriched = {
            **item,
            "rule_score":          r_score,
            "ai_score":            result.get("ai_score", r_score),
            "action":              result.get("action", "HOLD"),
            "confidence":          result.get("confidence", "LOW"),
            "ai_reason":           result.get("reason", ""),
            "adjusted_target_pct": result.get("adjusted_target_pct"),
            "adjusted_stop_pct":   result.get("adjusted_stop_pct"),
        }
        await push_score_only_queue(rdb, enriched)
        logger.info(
            "[Worker] 발행 완료 [%s %s] action=%s ai_score=%.1f",
            stk_cd, strategy, enriched["action"], enriched["ai_score"]
        )

    except Exception as e:
        logger.error("[Worker] 처리 오류 [%s %s]: %s", stk_cd, strategy, e)
        # 오류 신호 dead-letter queue 에 보관
        try:
            import json as _json
            dead_payload = _json.dumps({
                **item,
                "error": str(e),
                "error_ts": __import__("time").time(),
            }, ensure_ascii=False, default=str)
            await rdb.lpush("error_queue", dead_payload)
            await rdb.expire("error_queue", 86400)
        except Exception as dlq_err:
            logger.error("[Worker] error_queue 발행 실패: %s", dlq_err)
        # 원본 신호는 그대로 발행 (텔레그램 봇이 처리)
        await push_score_only_queue(rdb, {**item, "action": "HOLD", "ai_score": 0.0})

    return True


async def run_worker(rdb):
    """메인 폴링 루프"""
    logger.info("[Worker] 큐 워커 시작 (poll_interval=%.1fs)", POLL_INTERVAL)
    consecutive_empty = 0

    while True:
        try:
            processed = await process_one(rdb)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                # 연속 빈 큐 시 대기 시간 점진 증가 (최대 10초)
                wait = min(POLL_INTERVAL * (1 + consecutive_empty * 0.1), 10.0)
                await asyncio.sleep(wait)
        except Exception as e:
            logger.error("[Worker] 루프 오류: %s", e)
            await asyncio.sleep(5)
