import asyncio
import json
from datetime import datetime

from news_analyzer import NEWS_PROMPT_DESC_CHARS, _build_news_prompt
from news_scheduler import KST, _build_brief_message, _next_run_slot, _prefer_cached_on_fallback


class FakeRedis:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key):
        return self.values.get(key)


def test_next_run_slot_morning():
    info = _next_run_slot(datetime(2026, 4, 20, 7, 0, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MORNING"
    assert info["run_at"] == datetime(2026, 4, 20, 8, 0, 0, tzinfo=KST)


def test_next_run_slot_midday():
    info = _next_run_slot(datetime(2026, 4, 20, 8, 1, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MIDMORNING"
    assert info["run_at"] == datetime(2026, 4, 20, 10, 30, 0, tzinfo=KST)


def test_next_run_slot_close():
    info = _next_run_slot(datetime(2026, 4, 20, 12, 31, 0, tzinfo=KST))
    assert info["slot"]["name"] == "AFTERNOON"
    assert info["run_at"] == datetime(2026, 4, 20, 14, 0, 0, tzinfo=KST)


def test_next_run_slot_next_business_day():
    info = _next_run_slot(datetime(2026, 4, 17, 15, 41, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MORNING"
    assert info["run_at"] == datetime(2026, 4, 20, 8, 0, 0, tzinfo=KST)


def test_next_run_slot_keeps_kst_on_monday_premarket():
    info = _next_run_slot(datetime(2026, 4, 20, 7, 29, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MORNING"
    assert info["run_at"].tzinfo == KST
    assert info["run_at"] == datetime(2026, 4, 20, 8, 0, 0, tzinfo=KST)


def test_news_prompt_limits_items_and_description_length():
    news = [
        {
            "source": "src",
            "title": f"title-{i}",
            "description": "x" * (NEWS_PROMPT_DESC_CHARS + 50),
        }
        for i in range(25)
    ]

    prompt = _build_news_prompt(news, "AFTERNOON")

    assert "title-11" in prompt
    assert "title-12" not in prompt
    assert "x" * (NEWS_PROMPT_DESC_CHARS + 1) not in prompt


def test_ai_fallback_uses_cached_news_analysis():
    cached = {
        "market_sentiment": "BULLISH",
        "recommended_sectors": ["반도체"],
        "urgent_news": ["기존 정상 뉴스"],
        "summary": "기존 정상 브리핑",
        "confidence": "MEDIUM",
    }
    fallback = {
        "_fallback": True,
        "_fallback_reason": "api_quota_limited",
        "market_sentiment": "NEUTRAL",
        "recommended_sectors": [],
        "urgent_news": [],
        "summary": "fallback",
    }
    rdb = FakeRedis({"news:analysis": json.dumps(cached, ensure_ascii=False)})

    result = asyncio.run(_prefer_cached_on_fallback(rdb, fallback, "MIDDAY"))

    assert result["market_sentiment"] == "BULLISH"
    assert result["recommended_sectors"] == ["반도체"]
    assert result["_fallback"] is True
    assert result["_fallback_reason"] == "cached_due_to_api_quota_limited"
    assert result["brief_slot"] == "MIDDAY"


def test_live_brief_uses_fresh_cache_without_collecting(monkeypatch):
    import time
    import news_scheduler

    cached = {
        "market_sentiment": "NEUTRAL",
        "recommended_sectors": ["반도체"],
        "urgent_news": [],
        "risk_factors": [],
        "summary": "cached brief",
        "confidence": "MEDIUM",
        "brief_slot": "MIDDAY",
        "analyzed_at": time.time(),
    }
    rdb = FakeRedis({"news:analysis": json.dumps(cached, ensure_ascii=False)})

    async def fail_collect(_rdb):
        raise AssertionError("collect_news should not be called on fresh cache")

    monkeypatch.setattr(news_scheduler, "collect_news", fail_collect)
    result = asyncio.run(news_scheduler.build_live_brief(rdb, slot_name="MIDDAY"))

    assert result["used_cached_analysis"] is True
    assert result["analysis"]["summary"] == "cached brief"


def test_live_brief_no_ai_uses_cached_analysis_without_collecting(monkeypatch):
    import time
    import news_scheduler

    cached = {
        "market_sentiment": "NEUTRAL",
        "recommended_sectors": ["semiconductor"],
        "urgent_news": [],
        "risk_factors": [],
        "summary": "cached no-ai brief",
        "confidence": "MEDIUM",
        "brief_slot": "MIDDAY",
        "analyzed_at": time.time() - 3600,
    }
    rdb = FakeRedis({"news:analysis": json.dumps(cached, ensure_ascii=False)})

    async def fail_collect(_rdb):
        raise AssertionError("collect_news should not be called in no-ai live brief")

    async def fail_analyze(*_args, **_kwargs):
        raise AssertionError("analyze_news should not be called in no-ai live brief")

    monkeypatch.setattr(news_scheduler, "collect_news", fail_collect)
    monkeypatch.setattr(news_scheduler, "analyze_news", fail_analyze)
    result = asyncio.run(news_scheduler.build_live_brief(rdb, slot_name="MIDDAY", force_refresh=True, allow_ai=False))

    assert result["used_cached_analysis"] is True
    assert result["ai_used"] is False
    assert result["analysis"]["summary"] == "cached no-ai brief"


def test_build_morning_message_contains_required_sections():
    analysis = {
        "market_sentiment": "NEUTRAL",
        "recommended_sectors": ["반도체", "방산"],
        "risk_factors": ["환율 변동성", "장초반 변동성"],
        "summary": "갭보다 수급 지속성 확인이 우선입니다.",
        "us_market_points": ["S&P500은 기술주 강세 속 상승 마감"],
        "us_sector_points": ["반도체 강세, 에너지 혼조"],
        "macro_points": ["달러 강세 진정 여부 체크"],
        "korea_outlook": "국장은 장초반 반도체 중심 시도 후 수급 확인 과정이 예상됩니다.",
    }
    msg = _build_brief_message(analysis, "MORNING")
    assert "전일 미 3대지수" in msg
    assert "외부 변수" in msg
    assert "오늘 국장 예상 흐름" in msg


def test_build_midday_message_contains_required_sections():
    analysis = {
        "market_sentiment": "BULLISH",
        "midday_sectors": ["반도체", "로봇"],
        "midday_index_commentary": "코스피는 강보합, 코스닥은 주도 섹터 중심으로 상대 강세입니다.",
        "midday_recap": "오전장은 반도체와 로봇으로 수급이 집중됐습니다.",
        "afternoon_outlook": "오후장은 순환매 확산 여부가 핵심입니다.",
        "summary": "추격보다 눌림 확인이 유리합니다.",
    }
    msg = _build_brief_message(analysis, "MIDDAY")
    assert "오전장 주도 섹터" in msg
    assert "코스피 / 코스닥 흐름" in msg
    assert "오후장 예상" in msg


def test_build_close_message_contains_required_sections():
    analysis = {
        "market_sentiment": "BULLISH",
        "close_flow": "마감까지 반도체와 방산이 지수 버팀목 역할을 했습니다.",
        "close_leaders": ["반도체", "방산"],
        "tomorrow_watch": "미국 기술주 흐름과 환율 안정 여부를 먼저 확인해야 합니다.",
        "summary": "강한 종목은 남기고 약한 종목은 정리한 하루였습니다.",
    }
    msg = _build_brief_message(analysis, "CLOSE")
    assert "마감시황" in msg
    assert "오늘 시장 주도 축" in msg
    assert "내일 체크포인트" in msg


def test_build_morning_message_formats_sector_and_summary_as_bullets():
    analysis = {
        "market_sentiment": "BEARISH",
        "recommended_sectors": [
            "은행·보험주: 금리 상승 수혜와 방어 성격을 함께 확인한다.",
            "반도체: 눌림 이후 외국인 수급 복귀 여부를 본다.",
        ],
        "korea_outlook": "코스피는 약세 출발 가능성이 높다. 장중 환율 1,520원 돌파 여부를 확인해야 한다.",
        "summary": "추격 매수보다 눌림 확인이 우선이다. 방어 섹터 중심으로 비중을 조절한다.",
    }

    msg = _build_brief_message(analysis, "MORNING")

    assert "<b>5) 오늘 볼 섹터</b>\n• 은행·보험주" in msg
    assert ", 반도체:" not in msg
    assert "<b>4) 오늘 국장 예상 흐름</b>\n• 코스피는 약세 출발 가능성이 높다." in msg
    assert "<b>한 줄 결론</b>\n• 추격 매수보다 눌림 확인이 우선이다." in msg
