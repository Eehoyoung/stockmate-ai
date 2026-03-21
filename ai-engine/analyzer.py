"""
analyzer.py
Claude API 를 호출하여 거래 신호를 최종 분석·판단하는 모듈.
전략별 압축 프롬프트 사용으로 토큰 비용 절감.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS      = 256   # 압축 프롬프트에 맞게 축소
CLAUDE_TIMEOUT  = 10    # seconds

# Claude 클라이언트 싱글턴 (모듈 로드 시 생성, 매 호출 시 재생성 방지)
_claude_client: anthropic.AsyncAnthropic | None = None

def _get_claude_client() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise RuntimeError("CLAUDE_API_KEY 환경 변수 미설정")
        _claude_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _claude_client

# 시스템 프롬프트 (공통)
_PROMPT_DIR = Path(__file__).parent / "prompts"
try:
    _SYS_PROMPT = (_PROMPT_DIR / "signal_analysis.txt").read_text(encoding="utf-8")
except Exception:
    _SYS_PROMPT = (
        "당신은 한국 주식 단기 매매 신호 분석 전문가입니다. "
        "주어진 지표를 바탕으로 JSON 형식으로만 답하세요: "
        '{"action":"ENTER|HOLD|CANCEL","ai_score":0~100,"confidence":"HIGH|MEDIUM|LOW",'
        '"reason":"2문장 이내","adjusted_target_pct":null,"adjusted_stop_pct":null}'
    )


# 전략별 압축 프롬프트 생성기
def _build_user_message(signal: dict, market_ctx: dict, rule_score: float) -> str:
    strategy = signal.get("strategy", "")
    stk_cd   = signal.get("stk_cd", "")
    stk_nm   = signal.get("stk_nm", "")
    tick     = market_ctx.get("tick", {})
    hoga     = market_ctx.get("hoga", {})
    strength = market_ctx.get("strength", 0)
    flu_rt   = tick.get("flu_rt", "N/A")

    bid  = hoga.get("total_buy_bid_req", "0")
    ask  = hoga.get("total_sel_bid_req", "1")
    try:
        bid_ratio = round(float(str(bid).replace(",", "")) /
                          max(float(str(ask).replace(",", "")), 1), 2)
    except Exception:
        bid_ratio = 0

    if strategy == "S1_GAP_OPEN":
        return (
            f"갭상승 매수 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 갭: {signal.get('gap_pct', 'N/A')}%, "
            f"호가비율: {bid_ratio}, 체결강도: {round(strength, 1)}, 등락: {flu_rt}%, "
            f"규칙점수: {rule_score}/100\n"
            f"매수 적합성을 JSON으로 답하세요."
        )
    elif strategy == "S2_VI_PULLBACK":
        return (
            f"VI 눌림목 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 눌림: {signal.get('pullback_pct', 'N/A')}%, "
            f"동적VI: {signal.get('is_dynamic', False)}, 체결강도: {round(strength, 1)}, "
            f"규칙점수: {rule_score}/100\n"
            f"진입 적합성을 JSON으로 답하세요."
        )
    elif strategy == "S3_INST_FRGN":
        amt = signal.get("net_buy_amt", 0)
        amt_str = f"{int(amt) // 100_000_000}억" if amt else "N/A"
        return (
            f"외인+기관 순매수 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 순매수: {amt_str}, "
            f"연속일: {signal.get('continuous_days', 'N/A')}일, "
            f"거래량비율: {signal.get('vol_ratio', 'N/A')}x, 규칙점수: {rule_score}/100\n"
            f"진입 적합성을 JSON으로 답하세요."
        )
    elif strategy == "S4_BIG_CANDLE":
        return (
            f"장대양봉 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 양봉비율: {signal.get('body_ratio', 'N/A')}, "
            f"거래량비율: {signal.get('vol_ratio', 'N/A')}배, "
            f"신고가: {signal.get('is_new_high', False)}, 규칙점수: {rule_score}/100\n"
            f"추가 상승 가능성을 JSON으로 답하세요."
        )
    elif strategy == "S5_PROG_FRGN":
        amt = signal.get("net_buy_amt", 0)
        amt_str = f"{int(amt) // 100_000_000}억" if amt else "N/A"
        return (
            f"프로그램+외인 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 순매수: {amt_str}, "
            f"체결강도: {round(strength, 1)}, 호가비율: {bid_ratio}, 규칙점수: {rule_score}/100\n"
            f"진입 적합성을 JSON으로 답하세요."
        )
    elif strategy == "S6_THEME_LAGGARD":
        return (
            f"테마 후발주 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 테마: {signal.get('theme_name', 'N/A')}, "
            f"등락: {signal.get('gap_pct', 'N/A')}%, 체결강도: {round(strength, 1)}, "
            f"호가비율: {bid_ratio}, 규칙점수: {rule_score}/100\n"
            f"후발주 진입 적합성을 JSON으로 답하세요."
        )
    elif strategy == "S7_AUCTION":
        return (
            f"동시호가 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 갭: {signal.get('gap_pct', 'N/A')}%, "
            f"호가비율: {bid_ratio}, 거래량순위: {signal.get('vol_rank', 'N/A')}, "
            f"규칙점수: {rule_score}/100\n"
            f"시초가 매수 적합성을 JSON으로 답하세요."
        )
    else:
        return (
            f"매매 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 전략: {strategy}, "
            f"등락: {flu_rt}%, 체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"진입 적합성을 JSON으로 답하세요."
        )


async def analyze_signal(signal: dict, market_ctx: dict, rule_score: float) -> dict:
    """
    Claude API 호출로 신호 최종 분석.
    타임아웃(10s) 또는 오류 시 규칙 스코어 폴백.
    반환: {"action": ..., "ai_score": ..., "confidence": ..., "reason": ...,
           "adjusted_target_pct": ..., "adjusted_stop_pct": ...}
    """
    client       = _get_claude_client()
    user_message = _build_user_message(signal, market_ctx, rule_score)

    raw_text = ""
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model      = CLAUDE_MODEL,
                max_tokens = MAX_TOKENS,
                system     = _SYS_PROMPT,
                messages   = [{"role": "user", "content": user_message}],
            ),
            timeout=CLAUDE_TIMEOUT,
        )
        raw_text = response.content[0].text.strip()

        # JSON 파싱 – Claude 가 JSON 앞뒤에 텍스트를 추가하는 경우 중괄호 범위 추출
        json_start = raw_text.find("{")
        json_end   = raw_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            raw_text = raw_text[json_start:json_end]
        result = json.loads(raw_text)
        logger.info(
            json.dumps({
                "ts": __import__("time").time(),
                "module": "analyzer",
                "strategy": signal.get("strategy"),
                "stk_cd": signal.get("stk_cd"),
                "action": result.get("action"),
                "ai_score": result.get("ai_score"),
            })
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("[AI] Claude 타임아웃 (%ds) [%s %s] – 규칙 폴백",
                       CLAUDE_TIMEOUT, signal.get("stk_cd"), signal.get("strategy"))
        return _fallback(rule_score)
    except json.JSONDecodeError as e:
        logger.error("[AI] JSON 파싱 실패: %s / raw=%.200s", e, raw_text)
        return _fallback(rule_score)
    except anthropic.APIError as e:
        logger.warning("[AI] Claude API 오류: %s – 규칙 폴백", e)
        return _fallback(rule_score)
    except Exception as e:
        logger.warning("[AI] 예기치 않은 오류: %s – 규칙 폴백", e)
        return _fallback(rule_score)


def _fallback(rule_score: float) -> dict:
    """Claude API 실패 시 규칙 스코어 기반 폴백"""
    action = "ENTER" if rule_score >= 70 else ("HOLD" if rule_score >= 50 else "CANCEL")
    return {
        "action":              action,
        "ai_score":            rule_score,
        "confidence":          "LOW",
        "reason":              "AI 분석 실패 – 규칙 스코어 기반 폴백 적용",
        "adjusted_target_pct": None,
        "adjusted_stop_pct":   None,
    }
