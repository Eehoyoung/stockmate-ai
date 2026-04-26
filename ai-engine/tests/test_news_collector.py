import asyncio
from datetime import datetime, timezone

import news_collector


class FakeRedis:
    def __init__(self, existing=None):
        self.existing = set(existing or [])
        self.set_calls = []

    async def exists(self, key):
        return key in self.existing

    async def set(self, key, value, ex=None):
        self.set_calls.append((key, value, ex))
        self.existing.add(key)


def _rss_item(title, pub_date, description=""):
    return f"""
    <item>
      <title>{title}</title>
      <description>{description}</description>
      <link>https://example.com/{abs(hash(title))}</link>
      <pubDate>{pub_date}</pubDate>
    </item>
    """


def test_parse_rss_extracts_score_and_timestamp():
    xml = f"""
    <rss><channel>
      {_rss_item("코스피 반도체 실적 개선에 상승", "Mon, 20 Apr 2026 09:10:00 +0900", "삼성전자와 AI 수요")}
    </channel></rss>
    """

    items = news_collector._parse_rss(xml, {"name": "test", "weight": 2})

    assert len(items) == 1
    assert items[0]["source"] == "test"
    assert items[0]["relevance_score"] >= 10
    assert items[0]["published_ts"] == datetime(2026, 4, 20, 0, 10, tzinfo=timezone.utc).timestamp()


def test_rank_news_prefers_relevance_then_freshness_and_filters_noise():
    items = [
        {
            "title": "스포츠 스타 결혼 소식",
            "description": "",
            "source": "a",
            "link": "https://example.com/noise",
            "published_ts": 9999999999,
            "relevance_score": -5,
            "hash": "noise",
        },
        {
            "title": "코스피 환율 부담에도 반도체 강세",
            "description": "",
            "source": "a",
            "link": "https://example.com/market",
            "published_ts": 1,
            "relevance_score": 15,
            "hash": "market",
        },
        {
            "title": "금리 안정에 증시 투자심리 회복",
            "description": "",
            "source": "b",
            "link": "https://example.com/fresh",
            "published_ts": 2,
            "relevance_score": 15,
            "hash": "fresh",
        },
    ]

    ranked = news_collector._rank_news(items)

    assert [item["hash"] for item in ranked] == ["fresh", "market"]


def test_collect_news_deduplicates_ranks_and_marks_returned_items(monkeypatch):
    async def fake_fetch(_client, source):
        return [
            {
                "title": "코스피 반도체 실적 개선에 상승",
                "description": "AI 수요 증가",
                "source": source["name"],
                "link": "https://example.com/a",
                "published_at": "2026-04-20T09:00:00+09:00",
                "published_ts": 1,
                "relevance_score": 16,
            },
            {
                "title": "코스피 반도체 실적 개선에 상승",
                "description": "중복 기사",
                "source": source["name"],
                "link": "https://example.com/b",
                "published_at": "2026-04-20T09:01:00+09:00",
                "published_ts": 2,
                "relevance_score": 16,
            },
            {
                "title": "회사 임원 인사",
                "description": "",
                "source": source["name"],
                "link": "https://example.com/c",
                "published_at": "2026-04-20T09:02:00+09:00",
                "published_ts": 3,
                "relevance_score": -4,
            },
        ]

    monkeypatch.setattr(news_collector, "_fetch_rss", fake_fetch)
    rdb = FakeRedis()

    result = asyncio.run(news_collector.collect_news(rdb))

    assert len(result) == 1
    assert result[0]["title"] == "코스피 반도체 실적 개선에 상승"
    assert result[0]["hash"]
    assert len(rdb.set_calls) == 1
