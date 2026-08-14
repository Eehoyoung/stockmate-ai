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
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
NEWS_MAX_TOKENS = int(os.getenv("NEWS_MAX_TOKENS", "4000"))
NEWS_CLAUDE_TIMEOUT = int(os.getenv("NEWS_CLAUDE_TIMEOUT_SEC", "180"))
MAX_NEWS_CLAUDE_CALLS = int(os.getenv("MAX_NEWS_CLAUDE_CALLS", "10"))
NEWS_RETRY_ON_MAX_TOKENS = os.getenv("NEWS_RETRY_ON_MAX_TOKENS", "true").lower() in {"1", "true", "yes", "on"}
NEWS_RETRY_MAX_TOKENS = int(os.getenv("NEWS_RETRY_MAX_TOKENS", "2000"))
NEWS_PROMPT_ITEM_LIMIT = int(os.getenv("NEWS_PROMPT_ITEM_LIMIT", "18"))
NEWS_PROMPT_DESC_CHARS = int(os.getenv("NEWS_PROMPT_DESC_CHARS", "90"))

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
_NEWS_API_BLOCK_KEY = "claude:news_api_blocked"
_MIN_API_BLOCK_TTL_SEC = 3600
_MAX_API_BLOCK_TTL_SEC = 172800
_SLOT_LABELS = {
    "MORNING": "07:50 오전 브리핑",
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
    "recommended_sectors": 4,
    "urgent_news": 4,
    "risk_factors": 3,
    "us_market_points": 3,
    "us_sector_points": 3,
    "macro_points": 3,
    "midday_sectors": 4,
    "close_leaders": 4,
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

_SLOT_NEWS_LIMITS = {
    "MORNING": 18,
    "MIDMORNING": 14,
    "MIDDAY": 14,
    "AFTERNOON": 12,
    "CLOSE": 14,
}


def _prompt_news_limit(slot_name: str) -> int:
    slot_limit = _SLOT_NEWS_LIMITS.get(str(slot_name or "").upper(), NEWS_PROMPT_ITEM_LIMIT)
    return max(1, min(NEWS_PROMPT_ITEM_LIMIT, slot_limit))


def _build_news_prompt(news_list: List[Dict], slot_name: str) -> str:
    if not news_list:
        return "수집된 뉴스가 없습니다. 정보 부족 상태로 보수적으로 판단하세요."

    slot_label = _SLOT_LABELS.get(slot_name, slot_name)
    prompt_items = news_list[:_prompt_news_limit(slot_name)]
    lines = [
        f"[수행 슬롯] {slot_label}",
        "[브리핑 스타일] 탑급 애널리스트 + 헤드 트레이더 + 초보자 교육형 진행자",
        f"[수집 뉴스 {len(news_list)}건 중 {len(prompt_items)}건 분석]",
        "",
    ]
    for i, news in enumerate(prompt_items, 1):
        title = news.get("title", "")
        desc = news.get("description", "")
        src = news.get("source", "")
        line = f"{i}. [{src}] {title}"
        if desc:
            line += f" / {desc[:NEWS_PROMPT_DESC_CHARS]}"
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
    lines.append("")
    lines.append("[OUTPUT BUDGET - mandatory]")
    lines.append("- Return valid JSON only. No markdown, no explanations outside JSON.")
    lines.append("- recommended_sectors max 4 items, urgent_news max 4 items, risk_factors max 3 items.")
    lines.append("- us_market_points/us_sector_points/macro_points max 3 items each.")
    lines.append("- midday_sectors/close_leaders max 4 items each.")
    lines.append("- Each list item must be one Korean sentence under 120 Korean characters.")
    lines.append("- summary must be 2-3 Korean sentences under 300 Korean characters.")
    lines.append("- korea_outlook/midday_index_commentary/midday_recap/afternoon_outlook/close_flow/tomorrow_watch must each be under 260 Korean characters.")
    return "\n".join(lines)


def _build_compact_retry_prompt(news_list: List[Dict], slot_name: str) -> str:
    slot_label = _SLOT_LABELS.get(slot_name, slot_name)
    lines = [
        f"[RETRY SLOT] {slot_label}",
        "The previous response was too long and was truncated. Re-analyze the news and return compact valid JSON only.",
        "Hard output limits:",
        "- recommended_sectors max 4, urgent_news max 4, risk_factors max 3.",
        "- us_market_points/us_sector_points/macro_points max 3 each.",
        "- midday_sectors/close_leaders max 4 each.",
        "- Each array item: one Korean sentence, under 130 Korean characters.",
        "- summary: 2-3 Korean sentences, under 320 Korean characters.",
        "- All other text fields: under 260 Korean characters.",
        "- No newline characters inside JSON strings.",
        "- Fill every key from the output schema, using empty arrays/strings when not relevant.",
        "",
        "[NEWS]",
    ]
    for i, news in enumerate(news_list[:20], 1):
        title = str(news.get("title", "") or "")
        desc = str(news.get("description", "") or "")
        src = str(news.get("source", "") or "")
        line = f"{i}. [{src}] {title}"
        if desc:
            line += f" / {desc[:90]}"
        lines.append(line)

    lines.extend([
        "",
        "[OUTPUT JSON SCHEMA]",
        "{",
        '  "market_sentiment":"BULLISH|NEUTRAL|BEARISH",',
        '  "recommended_sectors":[],',
        '  "urgent_news":[],',
        '  "risk_factors":[],',
        '  "summary":"",',
        '  "confidence":"HIGH|MEDIUM|LOW",',
        '  "us_market_points":[],',
        '  "us_sector_points":[],',
        '  "macro_points":[],',
        '  "korea_outlook":"",',
        '  "midday_sectors":[],',
        '  "midday_index_commentary":"",',
        '  "midday_recap":"",',
        '  "afternoon_outlook":"",',
        '  "close_flow":"",',
        '  "close_leaders":[],',
        '  "tomorrow_watch":""',
        "}",
    ])
    return "\n".join(lines)


async def _call_claude(client, user_message: str, max_tokens: int) -> tuple[str, str]:
    response = await asyncio.wait_for(
        client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=_NEWS_SYS_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ),
        timeout=NEWS_CLAUDE_TIMEOUT,
    )
    return response.content[0].text.strip(), getattr(response, "stop_reason", "")


def _parse_news_json(raw_text: str) -> Dict:
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(line for line in lines if not line.startswith("```")).strip()

    json_start = raw_text.find("{")
    json_end = raw_text.rfind("}")
    if json_start >= 0 and json_end > json_start:
        raw_text = raw_text[json_start:json_end + 1]

    return _normalize_result(json.loads(raw_text))


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


async def _is_api_blocked(rdb) -> bool:
    try:
        reason = await rdb.get(_NEWS_API_BLOCK_KEY)
        if reason:
            logger.warning("[NewsAnalyzer] API quota block active: %s", reason)
            return True
    except Exception as e:
        logger.debug("[NewsAnalyzer] API quota block check failed: %s", e)
    return False


def _is_usage_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    return "usage limit" in text or "usage limits" in text or "specified api usage limits" in text


def _api_limit_ttl_seconds(error: Exception) -> int:
    text = str(error)
    match = re.search(r"regain access on (\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}) UTC", text)
    if not match:
        return _MIN_API_BLOCK_TTL_SEC

    try:
        reset_at = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}:00+00:00")
        ttl = int((reset_at - datetime.now(timezone.utc)).total_seconds())
        return max(_MIN_API_BLOCK_TTL_SEC, min(ttl, _MAX_API_BLOCK_TTL_SEC))
    except Exception:
        return _MIN_API_BLOCK_TTL_SEC


async def _mark_api_blocked(rdb, error: Exception) -> None:
    ttl = _api_limit_ttl_seconds(error)
    try:
        await rdb.set(_NEWS_API_BLOCK_KEY, "api_quota_limited", ex=ttl)
        logger.warning("[NewsAnalyzer] API quota block set ttl=%ds", ttl)
    except Exception as e:
        logger.debug("[NewsAnalyzer] API quota block set failed: %s", e)


def _fallback_analysis(reason: str = "unknown") -> Dict:
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
        "_fallback_reason": reason,
    }


def _normalize_result(result: Dict) -> Dict:
    defaults = _fallback_analysis()
    defaults.pop("_fallback", None)
    defaults.pop("_fallback_reason", None)
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
        return _fallback_analysis("missing_api_key")

    if await _is_api_blocked(rdb):
        return _fallback_analysis("api_quota_limited")

    if not await _check_daily_news_limit(rdb):
        return _fallback_analysis("daily_limit_exceeded")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    user_message = _build_news_prompt(news_list, slot_name)
    raw_text = ""
    stop_reason = ""

    try:
        raw_text, stop_reason = await _call_claude(client, user_message, NEWS_MAX_TOKENS)
        try:
            result = _parse_news_json(raw_text)
        except json.JSONDecodeError:
            if stop_reason != "max_tokens" or not NEWS_RETRY_ON_MAX_TOKENS:
                raise
            if not await _check_daily_news_limit(rdb):
                return _fallback_analysis("retry_daily_limit_exceeded")
            logger.warning(
                "[NewsAnalyzer] primary response truncated; retrying compact JSON slot=%s max_tokens=%d",
                slot_name,
                NEWS_RETRY_MAX_TOKENS,
            )
            retry_prompt = _build_compact_retry_prompt(news_list, slot_name)
            raw_text, stop_reason = await _call_claude(client, retry_prompt, NEWS_RETRY_MAX_TOKENS)
            result = _parse_news_json(raw_text)
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
        return _fallback_analysis("timeout")
    except json.JSONDecodeError as e:
        logger.error("[NewsAnalyzer] JSON parse failed: %s stop_reason=%s / raw=%.300s", e, stop_reason, raw_text)
        return _fallback_analysis("json_parse_failed")
    except anthropic.APIError as e:
        if _is_usage_limit_error(e):
            await _mark_api_blocked(rdb, e)
            logger.warning("[NewsAnalyzer] Claude API quota limited: %s", e)
            return _fallback_analysis("api_quota_limited")
        logger.warning("[NewsAnalyzer] Claude API error: %s", e)
        return _fallback_analysis("api_error")
    except Exception as e:
        logger.warning("[NewsAnalyzer] unexpected error: %s", e)
        return _fallback_analysis("unexpected_error")
