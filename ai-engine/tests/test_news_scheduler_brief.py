from datetime import datetime

from news_scheduler import KST, _build_brief_message, _next_run_slot


def test_next_run_slot_morning():
    info = _next_run_slot(datetime(2026, 4, 20, 7, 0, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MORNING"
    assert info["run_at"] == datetime(2026, 4, 20, 8, 0, 0, tzinfo=KST)


def test_next_run_slot_midday():
    info = _next_run_slot(datetime(2026, 4, 20, 8, 1, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MIDDAY"
    assert info["run_at"] == datetime(2026, 4, 20, 12, 30, 0, tzinfo=KST)


def test_next_run_slot_close():
    info = _next_run_slot(datetime(2026, 4, 20, 12, 31, 0, tzinfo=KST))
    assert info["slot"]["name"] == "CLOSE"
    assert info["run_at"] == datetime(2026, 4, 20, 15, 40, 0, tzinfo=KST)


def test_next_run_slot_next_business_day():
    info = _next_run_slot(datetime(2026, 4, 17, 15, 41, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MORNING"
    assert info["run_at"] == datetime(2026, 4, 20, 8, 0, 0, tzinfo=KST)


def test_next_run_slot_keeps_kst_on_monday_premarket():
    info = _next_run_slot(datetime(2026, 4, 20, 7, 29, 0, tzinfo=KST))
    assert info["slot"]["name"] == "MORNING"
    assert info["run_at"].tzinfo == KST
    assert info["run_at"] == datetime(2026, 4, 20, 8, 0, 0, tzinfo=KST)


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
