"""
news_analyzer.py
수집된 뉴스를 Claude API에 배치로 전달하여 시장 심리, 섹터 추천,
매매 제어 여부를 분석하는 모듈.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL         = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
NEWS_MAX_TOKENS      = 512
NEWS_CLAUDE_TIMEOUT  = 30  # seconds (뉴스 배치 분석은 신호 분석보다 넉넉하게)
MAX_NEWS_CLAUDE_CALLS = int(os.getenv("MAX_NEWS_CLAUDE_CALLS", "48"))

_PROMPT_DIR = Path(__file__).parent / "prompts"
try:
    _NEWS_SYS_PROMPT = (_PROMPT_DIR / "news_analysis.txt").read_text(encoding="utf-8")
except Exception:
    _NEWS_SYS_PROMPT = (
        "당신은 한국 주식시장 뉴스 분석 전문가입니다. "
        "주어진 금융 뉴스를 분석하여 JSON 형식으로만 답하세요: "
        '{"market_sentiment":"BULLISH|NEUTRAL|BEARISH",'
        '"trading_control":"CONTINUE|CAUTIOUS|PAUSE",'
        '"recommended_sectors":[],"risk_factors":[],'
        '"summary":"요약","confidence":"HIGH|MEDIUM|LOW"}'
    )

_NEWS_CALLS_KEY_PREFIX = "claude_news_calls:"


def _build_news_prompt(news_list: List[Dict]) -> str:
    """뉴스 배치를 Claude 사용자 메시지로 변환"""
    if not news_list:
        return "수집된 뉴스가 없습니다. 뉴스 부재 상황으로 판단해주세요."

    lines = [f"[수집 뉴스 {len(news_list)}건 – 분석 요청]\n"]
    for i, news in enumerate(news_list, 1):
        title = news.get("title", "")
        desc  = news.get("description", "")
        src   = news.get("source", "")
        line  = f"{i}. [{src}] {title}"
        if desc:
            line += f" / {desc[:100]}"
        lines.append(line)

    lines.append("\n위 뉴스를 분석하여 JSON으로 답하세요.")
    return "\n".join(lines)


async def _check_daily_news_limit(rdb) -> bool:
    """일별 뉴스 분석 Claude 호출 상한 확인"""
    today = time.strftime("%Y%m%d")
    key   = f"{_NEWS_CALLS_KEY_PREFIX}{today}"
    try:
        count = await rdb.get(key)
        current = int(count) if count else 0
        if current >= MAX_NEWS_CLAUDE_CALLS:
            logger.warning("[NewsAnalyzer] 뉴스 Claude 호출 상한 초과 (%d/%d)",
                           current, MAX_NEWS_CLAUDE_CALLS)
            return False
        await rdb.incr(key)
        await rdb.expire(key, 90000)  # 25시간
        return True
    except Exception as e:
        logger.warning("[NewsAnalyzer] 호출 상한 체크 오류: %s – 계속 진행", e)
        return True


def _fallback_analysis() -> Dict:
    """Claude API 실패 시 기본 분석 결과 반환"""
    return {
        "market_sentiment":    "NEUTRAL",
        "trading_control":     "CONTINUE",
        "recommended_sectors": [],
        "risk_factors":        ["AI 분석 실패 – 뉴스 기반 제어 비활성화"],
        "summary":             "뉴스 분석을 수행할 수 없어 기본 매매 설정으로 운영합니다.",
        "confidence":          "LOW",
        "_fallback":           True,
    }


async def analyze_news(news_list: List[Dict], rdb) -> Dict:
    """
    Claude API로 뉴스 배치 분석.

    Args:
        news_list: collect_news()가 반환한 뉴스 목록
        rdb:       redis.asyncio 클라이언트 (호출 상한 카운팅용)

    Returns:
        {
            "market_sentiment": "BULLISH|NEUTRAL|BEARISH",
            "trading_control":  "CONTINUE|CAUTIOUS|PAUSE",
            "recommended_sectors": [...],
            "risk_factors":    [...],
            "summary":         "...",
            "confidence":      "HIGH|MEDIUM|LOW"
        }
    """
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        logger.error("[NewsAnalyzer] CLAUDE_API_KEY 미설정 – 폴백 반환")
        return _fallback_analysis()

    # 호출 상한 확인
    within_limit = await _check_daily_news_limit(rdb)
    if not within_limit:
        return _fallback_analysis()

    client       = anthropic.AsyncAnthropic(api_key=api_key)
    user_message = _build_news_prompt(news_list)
    raw_text     = ""

    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model      = CLAUDE_MODEL,
                max_tokens = NEWS_MAX_TOKENS,
                system     = _NEWS_SYS_PROMPT,
                messages   = [{"role": "user", "content": user_message}],
            ),
            timeout=NEWS_CLAUDE_TIMEOUT,
        )
        raw_text = response.content[0].text.strip()

        # JSON 추출 (마크다운 코드블록 처리)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        result = json.loads(raw_text)

        # 필수 필드 기본값 보정
        result.setdefault("market_sentiment",    "NEUTRAL")
        result.setdefault("trading_control",     "CONTINUE")
        result.setdefault("recommended_sectors", [])
        result.setdefault("risk_factors",        [])
        result.setdefault("summary",             "")
        result.setdefault("confidence",          "MEDIUM")

        # 유효값 검증
        if result["trading_control"] not in ("CONTINUE", "CAUTIOUS", "PAUSE"):
            result["trading_control"] = "CONTINUE"
        if result["market_sentiment"] not in ("BULLISH", "NEUTRAL", "BEARISH"):
            result["market_sentiment"] = "NEUTRAL"

        logger.info(
            "[NewsAnalyzer] 분석 완료 – control=%s sentiment=%s sectors=%s confidence=%s",
            result["trading_control"],
            result["market_sentiment"],
            result["recommended_sectors"],
            result["confidence"],
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("[NewsAnalyzer] Claude 타임아웃 (%ds) – 폴백 반환", NEWS_CLAUDE_TIMEOUT)
        return _fallback_analysis()
    except json.JSONDecodeError as e:
        logger.error("[NewsAnalyzer] JSON 파싱 실패: %s / raw=%.300s", e, raw_text)
        return _fallback_analysis()
    except anthropic.APIError as e:
        logger.warning("[NewsAnalyzer] Claude API 오류: %s – 폴백 반환", e)
        return _fallback_analysis()
    except Exception as e:
        logger.warning("[NewsAnalyzer] 예기치 않은 오류: %s – 폴백 반환", e)
        return _fallback_analysis()
