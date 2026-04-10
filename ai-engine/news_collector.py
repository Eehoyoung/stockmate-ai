"""
news_collector.py
한국 금융 뉴스를 RSS 피드에서 비동기 수집하는 모듈.
중복 뉴스는 Redis Set으로 제거하며 최신 N건만 반환한다.
"""

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Dict

import httpx

logger = logging.getLogger(__name__)

NEWS_MAX_ITEMS = int(os.getenv("NEWS_MAX_ITEMS", "30"))

# 수집 대상 RSS 피드 (우선순위 순)
# naver_finance(rss.naver.com)는 Docker 컨테이너 환경에서 DNS 해석 실패로 제거
NEWS_SOURCES = [
    {
        "name": "hankyung",
        "url": "https://www.hankyung.com/feed/all-news",
        "type": "rss",
    },
    {
        "name": "yonhap_economy",
        "url": "https://www.yna.co.kr/rss/economy.xml",
        "type": "rss",
    },
    {
        "name": "mk_economy",
        "url": "https://www.mk.co.kr/rss/30000001/",
        "type": "rss",
    },
]

_HTTP_TIMEOUT = 10.0
_DEDUP_TTL = 86400  # 24시간


def _parse_rss(xml_text: str, source_name: str) -> List[Dict]:
    """feedparser 없이 간단한 XML 파싱으로 RSS 항목 추출"""
    import xml.etree.ElementTree as ET
    items = []
    try:
        # XML 네임스페이스 처리를 위해 기본 파싱
        root = ET.fromstring(xml_text)

        # RSS 2.0 구조: rss/channel/item
        ns_map = {
            "media": "http://search.yahoo.com/mrss/",
            "dc":    "http://purl.org/dc/elements/1.1/",
        }

        # channel > item 탐색 (네임스페이스 무관)
        for item_el in root.iter("item"):
            title = _get_text(item_el, "title")
            desc  = _get_text(item_el, "description")
            link  = _get_text(item_el, "link")
            pub   = _get_text(item_el, "pubDate")

            if not title:
                continue

            # HTML 태그 제거 (간단한 방식)
            desc_clean = _strip_html(desc or "")[:200]

            items.append({
                "title":        title.strip(),
                "description":  desc_clean,
                "link":         link or "",
                "published_at": pub or "",
                "source":       source_name,
            })
    except Exception as e:
        logger.warning("[NewsCollector] RSS 파싱 오류 (%s): %s", source_name, e)

    return items


def _get_text(element, tag: str) -> str:
    found = element.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ""


def _strip_html(text: str) -> str:
    """간단한 HTML 태그 제거"""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _news_hash(title: str) -> str:
    return hashlib.md5(title.encode("utf-8")).hexdigest()[:16]


async def _fetch_rss(client: httpx.AsyncClient, source: Dict) -> List[Dict]:
    try:
        resp = await client.get(source["url"], timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        return _parse_rss(resp.text, source["name"])
    except httpx.HTTPStatusError as e:
        logger.warning("[NewsCollector] HTTP 오류 (%s): %s", source["name"], e.response.status_code)
        return []
    except Exception as e:
        logger.warning("[NewsCollector] 수집 실패 (%s): %s", source["name"], e)
        return []


async def collect_news(rdb) -> List[Dict]:
    """
    모든 RSS 소스에서 뉴스를 수집하고 중복 제거 후 반환.

    Args:
        rdb: redis.asyncio 클라이언트

    Returns:
        최신 뉴스 목록 (최대 NEWS_MAX_ITEMS건)
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": "StockMate-AI/1.0 (news-collector)"},
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *[_fetch_rss(client, src) for src in NEWS_SOURCES],
            return_exceptions=True,
        )

    all_news = []
    for r in results:
        if isinstance(r, list):
            all_news.extend(r)

    if not all_news:
        logger.warning("[NewsCollector] 수집된 뉴스 없음 (모든 소스 실패)")
        return []

    # 중복 제거 (Redis Set 기반 + 로컬 Set 기반)
    unique_news = []
    seen_hashes = set()

    for news in all_news:
        h = _news_hash(news["title"])
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        dedup_key = f"news:dedup:{h}"
        try:
            # Redis에 이미 있으면 중복 (이번 주기에 분석된 항목)
            if await rdb.exists(dedup_key):
                continue
        except Exception:
            pass  # Redis 오류 시 중복 체크 건너뜀

        news["hash"] = h
        unique_news.append(news)

    # 최대 건수 제한 후 실제 분석 대상에만 dedup 마크 설정
    result = unique_news[:NEWS_MAX_ITEMS]
    for item in result:
        try:
            await rdb.set(f"news:dedup:{item['hash']}", "1", ex=_DEDUP_TTL)
        except Exception:
            pass

    logger.info("[NewsCollector] 수집 완료 – 전체=%d건 신규=%d건 반환=%d건",
                len(all_news), len(unique_news), len(result))
    return result
