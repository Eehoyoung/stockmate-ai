from __future__ import annotations
"""
news_collector.py

Korean market news collector used by the scheduled AI brief.
It fetches RSS feeds concurrently, removes duplicates, scores market relevance,
and returns the freshest high-signal items for downstream Claude analysis.
"""

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List

import feedparser
import httpx

logger = logging.getLogger(__name__)

NEWS_MAX_ITEMS = int(os.getenv("NEWS_MAX_ITEMS", "30"))
NEWS_MIN_RELEVANCE = int(os.getenv("NEWS_MIN_RELEVANCE", "2"))
NEWS_PER_SOURCE_LIMIT = int(os.getenv("NEWS_PER_SOURCE_LIMIT", "14"))

NEWS_SOURCES = [
    {
        "name": "hankyung",
        "url": "https://www.hankyung.com/feed/all-news",
        "type": "rss",
        "weight": 2,
    },
    {
        "name": "yonhap_economy",
        "url": "https://www.yna.co.kr/rss/economy.xml",
        "type": "rss",
        "weight": 3,
    },
    {
        "name": "mk_economy",
        "url": "https://www.mk.co.kr/rss/30000001/",
        "type": "rss",
        "weight": 2,
    },
]

_HTTP_TIMEOUT = 10.0
_DEDUP_TTL = 86400

_MARKET_KEYWORDS = {
    "증시": 5,
    "코스피": 6,
    "코스닥": 6,
    "코스피200": 6,
    "주식": 4,
    "주가": 4,
    "상장": 3,
    "IPO": 3,
    "실적": 4,
    "영업이익": 4,
    "매출": 2,
    "어닝": 4,
    "반도체": 5,
    "AI": 4,
    "인공지능": 4,
    "2차전지": 5,
    "배터리": 4,
    "바이오": 4,
    "제약": 4,
    "조선": 4,
    "방산": 4,
    "로봇": 4,
    "자동차": 3,
    "전기차": 4,
    "원전": 4,
    "금융": 3,
    "은행": 3,
    "보험": 3,
    "증권": 4,
    "원화": 4,
    "환율": 5,
    "달러": 4,
    "금리": 5,
    "국채": 4,
    "연준": 5,
    "Fed": 5,
    "FOMC": 5,
    "유가": 4,
    "WTI": 4,
    "브렌트": 4,
    "수출": 3,
    "무역": 3,
    "중국": 3,
    "미국": 3,
    "일본": 2,
    "관세": 4,
    "규제": 3,
    "지정학": 4,
    "전쟁": 4,
    "중동": 3,
    "우크라이나": 3,
    "북한": 4,
}

_NOISE_KEYWORDS = {
    "부고",
    "인사",
    "동정",
    "게시판",
    "날씨",
    "연예",
    "스포츠",
    "맛집",
    "여행",
    "패션",
    "결혼",
}

_WHITESPACE_RE = re.compile(r"\s+")
_HTML_RE = re.compile(r"<[^>]+>")
_BRACKET_RE = re.compile(r"^\s*[\[\(【][^\]\)】]{1,30}[\]\)】]\s*")


def _strip_html(text: str) -> str:
    text = _HTML_RE.sub("", text or "")
    return _WHITESPACE_RE.sub(" ", text).strip()


def _normalize_title(title: str) -> str:
    value = _strip_html(title)
    value = _BRACKET_RE.sub("", value)
    value = re.sub(r"[\"'“”‘’·,.\-_/\\:;!?()\[\]{}<>|]", "", value)
    return _WHITESPACE_RE.sub(" ", value).strip().lower()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _published_timestamp(news: Dict) -> float:
    published_dt = news.get("published_dt")
    if isinstance(published_dt, datetime):
        return published_dt.timestamp()
    return 0.0


def _news_hash(news: Dict) -> str:
    normalized = _normalize_title(news.get("title", ""))
    link = str(news.get("link", "")).split("?")[0].strip()
    base = normalized or link or str(news.get("title", ""))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]


def _relevance_score(news: Dict, source_weight: int = 1) -> int:
    title = str(news.get("title", ""))
    desc = str(news.get("description", ""))
    text = f"{title} {desc}"
    score = source_weight

    for keyword, weight in _MARKET_KEYWORDS.items():
        if keyword.lower() in text.lower():
            score += weight

    title_lower = title.lower()
    for keyword in _NOISE_KEYWORDS:
        if keyword.lower() in title_lower:
            score -= 8

    if len(title.strip()) < 8:
        score -= 4
    if not news.get("link"):
        score -= 1

    return score


def _parse_rss(xml_text: str, source: Dict) -> List[Dict]:
    source_name = str(source["name"])
    parsed = feedparser.parse(xml_text)
    if getattr(parsed, "bozo", False):
        logger.debug("[NewsCollector] RSS parse warning (%s): %s", source_name, getattr(parsed, "bozo_exception", ""))

    items: List[Dict] = []
    for entry in parsed.entries:
        title = _strip_html(entry.get("title", ""))
        if not title:
            continue

        description = _strip_html(
            entry.get("summary")
            or entry.get("description")
            or entry.get("subtitle")
            or ""
        )[:260]
        published_raw = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("created")
            or ""
        )
        published_dt = _parse_datetime(published_raw)
        link = str(entry.get("link") or "").strip()

        item = {
            "title": title,
            "description": description,
            "link": link,
            "published_at": published_dt.isoformat() if published_dt else published_raw,
            "published_ts": published_dt.timestamp() if published_dt else 0,
            "published_dt": published_dt,
            "source": source_name,
        }
        item["relevance_score"] = _relevance_score(item, int(source.get("weight", 1)))
        items.append(item)

    return items


async def _fetch_rss(client: httpx.AsyncClient, source: Dict) -> List[Dict]:
    try:
        resp = await client.get(source["url"], timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        items = _parse_rss(resp.text, source)
        logger.debug("[NewsCollector] source=%s fetched=%d", source["name"], len(items))
        return items
    except httpx.HTTPStatusError as e:
        logger.warning("[NewsCollector] HTTP error (%s): %s", source["name"], e.response.status_code)
        return []
    except Exception as e:
        logger.warning("[NewsCollector] fetch failed (%s): %s", source["name"], e)
        return []


def _rank_news(items: List[Dict]) -> List[Dict]:
    relevant = [item for item in items if int(item.get("relevance_score", 0)) >= NEWS_MIN_RELEVANCE]
    pool = relevant if relevant else items
    pool.sort(
        key=lambda item: (
            int(item.get("relevance_score", 0)),
            float(item.get("published_ts") or _published_timestamp(item)),
        ),
        reverse=True,
    )

    selected: List[Dict] = []
    source_counts: dict[str, int] = {}
    deferred: List[Dict] = []

    for item in pool:
        source = str(item.get("source", "unknown"))
        if source_counts.get(source, 0) >= NEWS_PER_SOURCE_LIMIT:
            deferred.append(item)
            continue
        selected.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) >= NEWS_MAX_ITEMS:
            break

    if len(selected) < NEWS_MAX_ITEMS:
        for item in deferred:
            selected.append(item)
            if len(selected) >= NEWS_MAX_ITEMS:
                break

    for item in selected:
        item.pop("published_dt", None)
    return selected


async def collect_news(rdb) -> List[Dict]:
    """
    Fetch RSS news, remove duplicates, rank by market relevance/freshness,
    and return at most NEWS_MAX_ITEMS records.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": "StockMate-AI/1.0 (news-collector)"},
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *[_fetch_rss(client, src) for src in NEWS_SOURCES],
            return_exceptions=True,
        )

    all_news: List[Dict] = []
    for result in results:
        if isinstance(result, list):
            all_news.extend(result)
        elif isinstance(result, Exception):
            logger.debug("[NewsCollector] source task failed: %s", result)

    if not all_news:
        logger.warning("[NewsCollector] no news collected (all sources failed)")
        return []

    unique_news: List[Dict] = []
    seen_hashes: set[str] = set()
    redis_duplicates = 0

    for news in all_news:
        h = _news_hash(news)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        try:
            if await rdb.exists(f"news:dedup:{h}"):
                redis_duplicates += 1
                continue
        except Exception:
            pass

        news["hash"] = h
        unique_news.append(news)

    ranked = _rank_news(unique_news)

    for item in ranked:
        try:
            await rdb.set(f"news:dedup:{item['hash']}", "1", ex=_DEDUP_TTL)
        except Exception:
            pass

    logger.info(
        "[NewsCollector] collected total=%d unique=%d redis_dups=%d returned=%d min_score=%s",
        len(all_news),
        len(unique_news),
        redis_duplicates,
        len(ranked),
        min((item.get("relevance_score", 0) for item in ranked), default="-"),
    )
    return ranked
