from __future__ import annotations
"""
overnight_worker.py
14:50 강제청산 타임에 Java ForceCloseScheduler 가 overnight_eval_queue 에
발행한 종목을 규칙 기반 스코어링으로 최종 판단.

흐름:
  ForceCloseScheduler (Java)
    → LPUSH overnight_eval_queue {type, signal_id, stk_cd, strategy,
                                   overnight_score, entry_price, ...}
  overnight_worker (이 파일)
    → RPOP overnight_eval_queue
    → 실시간 시세(tick/hoga/strength) + 기술지표 캐시 → overnight_scorer 판단
    → hold=True  → LPUSH ai_scored_queue {type: OVERNIGHT_HOLD, ...}
    → hold=False → LPUSH ai_scored_queue {type: FORCE_CLOSE,    ...}
  Telegram Bot (Node.js)
    → RPOP ai_scored_queue → 메시지 발송
"""

import asyncio
import json
import logging
import os

from redis_reader import (
    get_tick_data,
    get_hoga_data,
    get_avg_cntr_strength,
    push_score_only_queue,
)
from db_reader import get_daily_indicators
from http_utils import fetch_stk_nm
from overnight_scorer import evaluate_overnight
from db_writer import insert_overnight_eval, record_overnight_eval

logger = logging.getLogger(__name__)
POLL_INTERVAL = float(os.getenv("OVERNIGHT_POLL_SEC", "2.0"))
REDIS_TOKEN_KEY = "kiwoom:token"


async def _process_one(rdb, pg_pool=None) -> bool:
    raw = await rdb.rpop("overnight_eval_queue")
    if not raw:
        return False

    try:
        item = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("[OvernightWorker] JSON 파싱 실패: %s / raw=%.80s", e, raw)
        return True

    stk_cd   = item.get("stk_cd", "")
    strategy = item.get("strategy", "")
    stk_nm   = item.get("stk_nm", "")
    if stk_cd and not stk_nm:
        try:
            token = await rdb.get(REDIS_TOKEN_KEY)
            if token:
                stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
                if stk_nm:
                    item["stk_nm"] = stk_nm
        except Exception as nm_err:
            logger.debug("[OvernightWorker] stk_nm 조회 실패 [%s %s]: %s", stk_cd, strategy, nm_err)

    try:
        tick, hoga, strength, indicators = await asyncio.gather(
            get_tick_data(rdb, stk_cd),
            get_hoga_data(rdb, stk_cd),
            get_avg_cntr_strength(rdb, stk_cd, 5),
            get_daily_indicators(pg_pool, stk_cd) if pg_pool else asyncio.sleep(0, result=None),
        )

        verdict = evaluate_overnight(item, tick, hoga, strength)
        bid_ratio = None
        try:
            if hoga:
                bid = float(str(hoga.get("total_buy_bid_req", "0")).replace(",", "").replace("+", "") or "0")
                ask = float(str(hoga.get("total_sel_bid_req", "0")).replace(",", "").replace("+", "") or "0")
                if ask > 0:
                    bid_ratio = bid / ask
        except Exception:
            bid_ratio = None

        if verdict.hold:
            payload = {
                **item,
                "type":            "OVERNIGHT_HOLD",
                "action":          "OVERNIGHT_HOLD",
                "confidence":      verdict.confidence,
                "ai_reason":       verdict.reason,
                "overnight_final": verdict.score,
                "message": (
                    f"🌙 오버나잇 홀딩 승인 [{strategy}] {stk_cd} {stk_nm}\n"
                    f"스코어: {verdict.score:.0f}점 ({verdict.confidence}) | {verdict.reason}"
                ),
            }
            logger.info(
                "[OvernightWorker] 홀딩 승인 [%s %s] score=%.0f conf=%s",
                stk_cd, strategy, verdict.score, verdict.confidence,
            )
        else:
            payload = {
                **item,
                "type":            "FORCE_CLOSE",
                "action":          "FORCE_CLOSE",
                "confidence":      verdict.confidence,
                "ai_reason":       verdict.reason,
                "overnight_final": verdict.score,
                "message": (
                    f"⚠️ 강제 청산 (스코어 미달) [{strategy}] {stk_cd} {stk_nm}\n"
                    f"스코어: {verdict.score:.0f}점 ({verdict.confidence}) | {verdict.reason}"
                ),
            }
            logger.info(
                "[OvernightWorker] 홀딩 거부→강제청산 [%s %s] score=%.0f conf=%s",
                stk_cd, strategy, verdict.score, verdict.confidence,
            )

        await push_score_only_queue(rdb, payload)

        # DB 기록 (signal_id 있을 때만)
        signal_id = item.get("id") or item.get("signal_id")
        if pg_pool and signal_id:
            try:
                await insert_overnight_eval(
                    pg_pool,
                    signal_id=signal_id,
                    position_id=item.get("position_id"),
                    stk_cd=stk_cd,
                    strategy=strategy,
                    java_overnight_score=item.get("overnight_score"),
                    verdict="HOLD" if verdict.hold else "FORCE_CLOSE",
                    final_score=verdict.score,
                    confidence=verdict.confidence,
                    reason=verdict.reason,
                    pnl_pct=item.get("pnl_pct"),
                    flu_rt=tick.get("flu_rt") if tick else None,
                    cntr_strength=strength,
                    rsi14=(verdict.detail or {}).get("rsi14") or (indicators or {}).get("rsi14"),
                    ma_alignment=(verdict.detail or {}).get("ma_alignment"),
                    bid_ratio=bid_ratio,
                    entry_price=item.get("entry_price"),
                    cur_price=tick.get("cur_prc") if tick else None,
                    score_components=verdict.detail,
                )
            except Exception as oe:
                logger.error("[OvernightWorker] overnight_evaluations 저장 실패 [%s %s]: %s", stk_cd, strategy, oe)

        if pg_pool and signal_id:
            await record_overnight_eval(
                pg_pool, signal_id,
                verdict="HOLD" if verdict.hold else "FORCE_CLOSE",
                overnight_score=verdict.score,
            )

    except Exception as e:
        logger.error("[OvernightWorker] 처리 오류 [%s %s]: %s", stk_cd, strategy, e)
        fallback = {
            **item,
            "type":      "FORCE_CLOSE",
            "action":    "FORCE_CLOSE",
            "ai_reason": f"오버나잇 평가 중 오류 – 강제청산 처리: {e}",
            "message": (
                f"⚠️ 강제 청산 (평가오류) [{strategy}] {stk_cd}\n"
                f"평가 중 오류로 안전하게 청산"
            ),
        }
        await push_score_only_queue(rdb, fallback)

    return True


async def run_overnight_worker(rdb, pg_pool=None):
    """overnight_eval_queue 폴링 루프"""
    logger.info("[OvernightWorker] 시작 (poll=%.1fs)", POLL_INTERVAL)
    consecutive_empty = 0

    while True:
        try:
            processed = await _process_one(rdb, pg_pool)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                wait = min(POLL_INTERVAL * (1 + consecutive_empty * 0.1), 10.0)
                await asyncio.sleep(wait)
        except Exception as e:
            logger.error("[OvernightWorker] 루프 오류: %s", e)
            await asyncio.sleep(5)
