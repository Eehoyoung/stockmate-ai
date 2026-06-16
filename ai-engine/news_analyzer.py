from __future__ import annotations

"""
news_analyzer.py

수집한 뉴스 묶음을 Claude API로 분석하여 시장 심리, 매매 제어,
섹터/리스크 요약과 슬롯별 브리핑 재료를 JSON으로 반환한다.
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

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
NEWS_MAX_TOKENS = int(os.getenv("NEWS_MAX_TOKENS", "2400"))
NEWS_CLAUDE_TIMEOUT = int(os.getenv("NEWS_CLAUDE_TIMEOUT_SEC", "45"))
MAX_NEWS_CLAUDE_CALLS = int(os.getenv("MAX_NEWS_CLAUDE_CALLS", "5"))

_PROMPT_DIR = Path(__file__).parent / "prompts"
try:
    _NEWS_SYS_PROMPT = (_PROMPT_DIR / "news_analysis.txt").read_text(encoding="utf-8")
except Exception:
    _NEWS_SYS_PROMPT = (
        "Return JSON only. "
        '{"market_sentiment":"BULLISH|NEUTRAL|BEARISH",'
        '"recommended_sectors":[],"urgent_news":[],"risk_factors":[],'
        '"summary":"","confidence":"HIGH|MEDIUM|LOW"}'
    )

_NEWS_CALLS_KEY_PREFIX = "claude_news_calls:"
_SLOT_LABELS = {
    "MORNING": "08:00 오전 브리핑",
    "MIDMORNING": "10:30 장중 오전 브리핑",
    "MIDDAY": "12:30 장중 브리핑",
    "AFTERNOON": "14:00 장중 오후 브리핑",
    "CLOSE": "15:40 장마감 브리핑",
}
_LIST_KEYS = (
    "recommended_sectors",
    "urgent_news",
    "risk_factors",
    "us_market_points",
    "us_sector_points",
    "macro_points",
    "midday_sectors",
    "close_leaders",
)
_LIST_LIMITS = {
    "recommended_sectors": 8,
    "urgent_news": 8,
    "risk_factors": 6,
    "us_market_points": 5,
    "us_sector_points": 5,
    "macro_points": 5,
    "midday_sectors": 8,
    "close_leaders": 8,
}
_TEXT_KEYS = (
    "summary",
    "korea_outlook",
    "midday_index_commentary",
    "midday_recap",
    "afternoon_outlook",
    "close_flow",
    "tomorrow_watch",
)


def _build_news_prompt(news_list: List[Dict], slot_name: str) -> str:
    if not news_list:
        return "수집된 뉴스가 없습니다. 정보 부족 상태로 보수적으로 판단하세요."

    slot_label = _SLOT_LABELS.get(slot_name, slot_name)
    lines = [
        f"[수행 슬롯] {slot_label}",
        "[브리핑 스타일] 탑급 애널리스트 + 헤드 트레이더 + 초보자 교육형 진행자",
        f"[수집 뉴스 {len(news_list)}건 - 분석 요청]",
        "",
    ]
    for i, news in enumerate(news_list, 1):
        title = news.get("title", "")
        desc = news.get("description", "")
        src = news.get("source", "")
        line = f"{i}. [{src}] {title}"
        if desc:
            line += f" / {desc[:160]}"
        lines.append(line)

    lines.append("")
    lines.append(
        "슬롯별 핵심 필드를 우선 채우세요. "
        "오전은 전일 미국장, 미국 주도 섹터, 외부 변수, 오늘 국장 전망. "
        "장중은 코스피/코스닥 흐름, 오전장 복기, 오후장 전망. "
        "장마감은 마감시황, 주도 섹터, 내일 체크포인트. "
        "각 항목은 시장을 이해할 수 있도록 원인, 수급/가격 반응, 확인 조건을 함께 적으세요. "
        "짧은 키워드 나열을 피하고, 각 리스트 항목은 1~2문장의 구체적인 분석 문장으로 작성하세요."
    )
    lines.append("JSON만 반환하세요. 문자열 안에는 실제 줄바꿈을 넣지 말고 한 줄 문장으로 작성하세요.")
    return "\n".join(lines)


async def _check_daily_news_limit(rdb) -> bool:
    today = time.strftime("%Y%m%d")
    key = f"{_NEWS_CALLS_KEY_PREFIX}{today}"
    try:
        current = int(await rdb.get(key) or 0)
        if current >= MAX_NEWS_CLAUDE_CALLS:
            logger.warning("[NewsAnalyzer] daily limit exceeded %d/%d", current, MAX_NEWS_CLAUDE_CALLS)
            return False
        await rdb.incr(key)
        await rdb.expire(key, 90000)
        return True
    except Exception as e:
        logger.warning("[NewsAnalyzer] daily limit check failed: %s", e)
        return True


def _fallback_analysis() -> Dict:
    return {
        "market_sentiment": "NEUTRAL",
        "recommended_sectors": [],
        "urgent_news": [],
        "risk_factors": ["AI 뉴스 분석 실패 - 보수적으로 해석 필요"],
        "summary": "뉴스 분석이 충분하지 않아 기본 매매 모드로 유지합니다.",
        "confidence": "LOW",
        "us_market_points": [],
        "us_sector_points": [],
        "macro_points": [],
        "korea_outlook": "",
        "midday_sectors": [],
        "midday_index_commentary": "",
        "midday_recap": "",
        "afternoon_outlook": "",
        "close_flow": "",
        "close_leaders": [],
        "tomorrow_watch": "",
        "_fallback": True,
    }


def _normalize_result(result: Dict) -> Dict:
    defaults = _fallback_analysis()
    defaults.pop("_fallback", None)
    for key, value in defaults.items():
        result.setdefault(key, value)

    if result["market_sentiment"] not in ("BULLISH", "NEUTRAL", "BEARISH"):
        result["market_sentiment"] = "NEUTRAL"

    for key in _LIST_KEYS:
        value = result.get(key, [])
        if not isinstance(value, list):
            value = [str(value)] if value else []
        result[key] = [
            str(item).replace("\n", " ").strip()
            for item in value
            if str(item).strip()
        ][:_LIST_LIMITS.get(key, 5)]

    for key in _TEXT_KEYS:
        result[key] = str(result.get(key, "") or "").strip()

    result["confidence"] = str(result.get("confidence", "MEDIUM") or "MEDIUM").upper()
    if result["confidence"] not in ("HIGH", "MEDIUM", "LOW"):
        result["confidence"] = "MEDIUM"

    return result


async def analyze_news(news_list: List[Dict], rdb, slot_name: str = "MORNING") -> Dict:
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        logger.error("[NewsAnalyzer] CLAUDE_API_KEY missing")
        return _fallback_analysis()

    if not await _check_daily_news_limit(rdb):
        return _fallback_analysis()

    client = anthropic.AsyncAnthropic(api_key=api_key)
    user_message = _build_news_prompt(news_list, slot_name)
    raw_text = ""

    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=NEWS_MAX_TOKENS,
                system=_NEWS_SYS_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ),
            timeout=NEWS_CLAUDE_TIMEOUT,
        )
        raw_text = response.content[0].text.strip()
        stop_reason = getattr(response, "stop_reason", "")

        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}")
        if json_start >= 0 and json_end > json_start:
            raw_text = raw_text[json_start:json_end + 1]

        result = _normalize_result(json.loads(raw_text))
        logger.info(
            "[NewsAnalyzer] done slot=%s sentiment=%s sectors=%s confidence=%s stop_reason=%s",
            slot_name,
            result["market_sentiment"],
            result["recommended_sectors"],
            result["confidence"],
            stop_reason,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning("[NewsAnalyzer] Claude timeout (%ds)", NEWS_CLAUDE_TIMEOUT)
        return _fallback_analysis()
    except json.JSONDecodeError as e:
        logger.error("[NewsAnalyzer] JSON parse failed: %s / raw=%.300s", e, raw_text)
        return _fallback_analysis()
    except anthropic.APIError as e:
        logger.warning("[NewsAnalyzer] Claude API error: %s", e)
        return _fallback_analysis()
    except Exception as e:
        logger.warning("[NewsAnalyzer] unexpected error: %s", e)
        return _fallback_analysis()
