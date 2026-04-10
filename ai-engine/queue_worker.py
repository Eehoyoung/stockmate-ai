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

from redis_reader import (
    pop_telegram_queue,
    get_tick_data,
    get_hoga_data,
    get_avg_cntr_strength,
    get_vi_status,
    push_score_only_queue,
)
from scorer import rule_score, should_skip_ai, get_claude_threshold
from db_writer import update_signal_score, insert_score_components, insert_python_signal

logger        = logging.getLogger(__name__)
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SEC", "2.0"))


async def _build_market_ctx(rdb, stk_cd: str) -> dict:
    tick, hoga, strength, vi = await asyncio.gather(
        get_tick_data(rdb, stk_cd),
        get_hoga_data(rdb, stk_cd),
        get_avg_cntr_strength(rdb, stk_cd, 5),
        get_vi_status(rdb, stk_cd),
    )
    return {"tick": tick, "hoga": hoga, "strength": strength, "vi": vi}


async def process_one(rdb, pg_pool=None) -> bool:
    """
    큐에서 항목 1개 처리.
    처리 항목이 있으면 True, 없으면 False 반환.
    pg_pool: asyncpg 풀 (None이면 DB 쓰기 스킵)
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

    stk_cd    = item.get("stk_cd", "")
    strategy  = item.get("strategy", "")
    signal_id = item.get("id")    # Java DB에서 생성된 signal_id (None 가능)
    signal    = item              # signal 필드들이 item 안에 flat하게 있음

    try:
        # 0. 뉴스 기반 매매 중단 여부 확인 (PAUSE 시 즉시 CANCEL)
        news_ctrl_val = None
        news_sentiment_val = None
        try:
            news_control = await rdb.get("news:trading_control")
            news_ctrl_val = news_control
            if news_control and news_control.upper() == "PAUSE":
                reason = await rdb.get("news:analysis")
                pause_reason = "뉴스 분석 결과 매매 중단"
                try:
                    import json as _json
                    analysis = _json.loads(reason or "{}")
                    pause_reason = analysis.get("summary", pause_reason)
                    news_sentiment_val = analysis.get("sentiment")
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
                if pg_pool and signal_id:
                    await update_signal_score(
                        pg_pool, signal_id,
                        rule_score=0.0, ai_score=0.0, rr_ratio=None,
                        action="CANCEL", confidence="HIGH",
                        ai_reason=pause_reason,
                        tp_method=None, sl_method=None, skip_entry=True,
                        news_sentiment=news_sentiment_val, news_ctrl=news_ctrl_val,
                    )
                return True
        except Exception as news_err:
            logger.debug("[Worker] 뉴스 제어 확인 실패 (무시): %s", news_err)

        # 1. WS 온라인 여부 확인 (ws:py_heartbeat TTL 기반)
        try:
            hb = await rdb.hgetall("ws:py_heartbeat")
            ws_online = bool(hb and hb.get("updated_at"))
        except Exception:
            ws_online = False
        if not ws_online:
            logger.warning("[Worker] WS 오프라인 – 실시간 데이터 없음 [%s %s]", stk_cd, strategy)

        # 2. 실시간 시세 수집
        ctx = await _build_market_ctx(rdb, stk_cd)
        ctx["ws_online"] = ws_online

        # 3. 규칙 기반 1차 스코어링 → (float, dict) 튜플
        r_score, components = rule_score(signal, ctx)
        logger.info("[Worker] 1차 스코어 [%s %s]: %.1f", stk_cd, strategy, r_score)

        # 4. 전략별 임계값 미달 → CANCEL
        threshold = get_claude_threshold(strategy)
        if should_skip_ai(r_score, strategy):
            action     = "CANCEL"
            confidence = "LOW"
            reason     = f"1차 스코어 {r_score:.1f}점 미달 – 진입 취소"
        else:
            # 5. 임계값 통과 → R:R 확인 후 ENTER / CANCEL
            if signal.get("skip_entry"):
                # TP/SL 계산 시 R:R < MIN_RR_RATIO → 진입 취소
                rr_val     = signal.get("rr_ratio", 0.0)
                action     = "CANCEL"
                confidence = "LOW"
                reason     = (
                    f"1차 스코어 {r_score:.1f}점 통과 – "
                    f"R:R {float(rr_val):.2f} 미달 (최소 1.3) – 진입 취소"
                )
            else:
                action     = "ENTER"
                confidence = "HIGH"
                reason     = f"1차 스코어 {r_score:.1f}점 통과 – 즉시 발송"

        enriched = {
            **item,
            "rule_score":          r_score,
            "ai_score":            r_score,
            "action":              action,
            "confidence":          confidence,
            "ai_reason":           reason,
            "adjusted_target_pct": None,
            "adjusted_stop_pct":   None,
        }
        await push_score_only_queue(rdb, enriched)
        logger.info(
            "[Worker] 발행 완료 [%s %s] action=%s score=%.1f",
            stk_cd, strategy, action, r_score
        )

        # 6. PostgreSQL 기록
        if pg_pool:
            db_id = signal_id
            if not db_id:
                # Python 단독 신호(Java id 없음) → 신규 INSERT
                db_id = await insert_python_signal(
                    pg_pool, signal,
                    action=action, confidence=confidence,
                    rule_score=r_score, ai_score=r_score,
                    ai_reason=reason, skip_entry=(action == "CANCEL"),
                )
            if db_id:
                await update_signal_score(
                    pg_pool, db_id,
                    rule_score=r_score, ai_score=r_score, rr_ratio=None,
                    action=action, confidence=confidence, ai_reason=reason,
                    tp_method=signal.get("tp_method"),
                    sl_method=signal.get("sl_method"),
                    skip_entry=(action == "CANCEL"),
                    ma5=signal.get("ma5"),   ma20=signal.get("ma20"),
                    ma60=signal.get("ma60"), rsi14=signal.get("rsi"),
                    bb_upper=signal.get("bb_upper"), bb_lower=signal.get("bb_lower"),
                    atr=signal.get("atr"),
                    market_flu_rt=None,
                    news_sentiment=news_sentiment_val,
                    news_ctrl=news_ctrl_val,
                )
                await insert_score_components(
                    pg_pool, db_id, strategy, components,
                    total_score=r_score, threshold=threshold,
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


async def run_worker(rdb, pg_pool=None):
    """메인 폴링 루프"""
    logger.info("[Worker] 큐 워커 시작 (poll_interval=%.1fs)", POLL_INTERVAL)
    consecutive_empty = 0

    while True:
        try:
            processed = await process_one(rdb, pg_pool)
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
