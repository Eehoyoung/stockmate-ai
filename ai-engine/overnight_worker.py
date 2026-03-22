"""
overnight_worker.py
14:50 강제청산 타임에 Java ForceCloseScheduler 가 overnight_eval_queue 에
발행한 종목을 Claude 가 최종 판단.

흐름:
  ForceCloseScheduler (Java)
    → LPUSH overnight_eval_queue {type, signal_id, stk_cd, strategy,
                                   overnight_score, entry_price, ...}
  overnight_worker (이 파일)
    → RPOP overnight_eval_queue
    → 실시간 시세(tick/hoga/strength) 조합 후 Claude 오버나잇 판단
    → hold=true  → LPUSH ai_scored_queue {type: OVERNIGHT_HOLD, ...}
    → hold=false → LPUSH ai_scored_queue {type: FORCE_CLOSE,    ...}
  Telegram Bot (Node.js)
    → RPOP ai_scored_queue → 메시지 발송
"""

import asyncio
import json
import logging
import os

import anthropic

from redis_reader import (
    get_tick_data,
    get_hoga_data,
    get_avg_cntr_strength,
    push_score_only_queue,
)

logger = logging.getLogger(__name__)

CLAUDE_MODEL  = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
POLL_INTERVAL = float(os.getenv("OVERNIGHT_POLL_SEC", "2.0"))
CLAUDE_TIMEOUT = 15  # 오버나잇 판단은 신호보다 여유 있게

_SYS_PROMPT = (
    "당신은 한국 주식 단기 매매 포지션의 오버나잇(장 마감 후 익일 보유) 여부를 판단하는 전문가입니다. "
    "규칙 기반 사전 점수, 전략 유형, 실시간 지표를 종합하여 오버나잇 보유가 유리한지 판단하세요. "
    "반드시 아래 JSON 형식으로만 답하세요: "
    '{"hold":true,"confidence":"HIGH|MEDIUM|LOW","reason":"2문장 이내"}'
)

# Claude 클라이언트 싱글턴
_claude_client: anthropic.AsyncAnthropic | None = None


def _get_claude_client() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise RuntimeError("CLAUDE_API_KEY 환경 변수 미설정")
        _claude_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _claude_client


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return default


def _build_prompt(item: dict, tick: dict, hoga: dict, strength: float) -> str:
    stk_cd   = item.get("stk_cd", "")
    stk_nm   = item.get("stk_nm", "")
    strategy = item.get("strategy", "")
    o_score  = item.get("overnight_score", 0)
    entry    = _safe_float(item.get("entry_price"))
    target   = item.get("target_price")
    stop     = item.get("stop_price")

    flu_rt  = _safe_float(tick.get("flu_rt"))
    cur_prc = _safe_float(tick.get("cur_prc"))

    bid = _safe_float(hoga.get("total_buy_bid_req"))
    ask = _safe_float(hoga.get("total_sel_bid_req", "1"))
    bid_ratio = round(bid / ask, 2) if ask > 0 else 0.0

    pnl_str = ""
    if entry > 0 and cur_prc > 0:
        pnl_pct = round((cur_prc - entry) / entry * 100, 2)
        pnl_str = f"{pnl_pct:+.2f}%"

    return (
        f"오버나잇 보유 판단 요청:\n"
        f"종목: {stk_nm}({stk_cd}), 전략: {strategy}\n"
        f"규칙 오버나잇 점수: {o_score}/100, 등락률: {flu_rt:+.2f}%\n"
        f"체결강도: {round(strength, 1)}, 호가비율: {bid_ratio}\n"
        f"현재가: {int(cur_prc):,}원, 미실현손익: {pnl_str}\n"
        f"진입가: {target}원, 목표가: {target}원, 손절가: {stop}원\n"
        f"오버나잇 보유가 유리한지 JSON으로 판단하세요."
    )


async def _call_claude(item: dict, tick: dict, hoga: dict, strength: float) -> dict:
    """Claude API 호출 → {"hold": bool, "confidence": str, "reason": str}"""
    prompt = _build_prompt(item, tick, hoga, strength)
    client = _get_claude_client()
    raw_text = ""
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=128,
                system=_SYS_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=CLAUDE_TIMEOUT,
        )
        raw_text = response.content[0].text.strip()
        j_start = raw_text.find("{")
        j_end   = raw_text.rfind("}") + 1
        if j_start >= 0 and j_end > j_start:
            raw_text = raw_text[j_start:j_end]
        return json.loads(raw_text)

    except asyncio.TimeoutError:
        logger.warning("[OvernightWorker] Claude 타임아웃 [%s] – 강제청산 처리",
                       item.get("stk_cd"))
        return {"hold": False, "confidence": "LOW",
                "reason": "Claude 타임아웃 – 안전을 위해 강제청산 처리"}
    except json.JSONDecodeError:
        logger.error("[OvernightWorker] JSON 파싱 실패 raw=%.100s", raw_text)
        return {"hold": False, "confidence": "LOW",
                "reason": "AI 응답 파싱 실패 – 강제청산 처리"}
    except anthropic.APIError as e:
        logger.warning("[OvernightWorker] Claude API 오류: %s", e)
        return {"hold": False, "confidence": "LOW",
                "reason": f"Claude API 오류 – 강제청산 처리"}
    except Exception as e:
        logger.error("[OvernightWorker] 예기치 않은 오류: %s", e)
        return {"hold": False, "confidence": "LOW",
                "reason": f"오류 발생 – 강제청산 처리: {e}"}


async def _process_one(rdb) -> bool:
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

    try:
        tick, hoga, strength = await asyncio.gather(
            get_tick_data(rdb, stk_cd),
            get_hoga_data(rdb, stk_cd),
            get_avg_cntr_strength(rdb, stk_cd, 5),
        )

        result = await _call_claude(item, tick, hoga, strength)
        hold   = result.get("hold", False)
        reason = result.get("reason", "")
        conf   = result.get("confidence", "LOW")

        stk_nm = item.get("stk_nm", "")

        if hold:
            payload = {
                **item,
                "type":       "OVERNIGHT_HOLD",
                "action":     "OVERNIGHT_HOLD",
                "confidence": conf,
                "ai_reason":  reason,
                "message":    (
                    f"🌙 오버나잇 홀딩 승인 [{strategy}] {stk_cd} {stk_nm}\n"
                    f"AI 확신도: {conf} | {reason}"
                ),
            }
            logger.info("[OvernightWorker] 홀딩 승인 [%s %s] conf=%s", stk_cd, strategy, conf)
        else:
            payload = {
                **item,
                "type":       "FORCE_CLOSE",
                "action":     "FORCE_CLOSE",
                "confidence": conf,
                "ai_reason":  reason,
                "message":    (
                    f"⚠️ 강제 청산 (AI 거부) [{strategy}] {stk_cd} {stk_nm}\n"
                    f"장마감 전 전량 시장가 청산 | {reason}"
                ),
            }
            logger.info("[OvernightWorker] 홀딩 거부→강제청산 [%s %s]", stk_cd, strategy)

        await push_score_only_queue(rdb, payload)

    except Exception as e:
        logger.error("[OvernightWorker] 처리 오류 [%s %s]: %s", stk_cd, strategy, e)
        fallback = {
            **item,
            "type":      "FORCE_CLOSE",
            "action":    "FORCE_CLOSE",
            "ai_reason": f"오버나잇 평가 중 오류 – 강제청산 처리: {e}",
            "message":   (
                f"⚠️ 강제 청산 (평가오류) [{strategy}] {stk_cd}\n"
                f"평가 중 오류로 안전하게 청산"
            ),
        }
        await push_score_only_queue(rdb, fallback)

    return True


async def run_overnight_worker(rdb):
    """overnight_eval_queue 폴링 루프"""
    logger.info("[OvernightWorker] 시작 (poll=%.1fs)", POLL_INTERVAL)
    consecutive_empty = 0

    while True:
        try:
            processed = await _process_one(rdb)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                wait = min(POLL_INTERVAL * (1 + consecutive_empty * 0.1), 10.0)
                await asyncio.sleep(wait)
        except Exception as e:
            logger.error("[OvernightWorker] 루프 오류: %s", e)
            await asyncio.sleep(5)
