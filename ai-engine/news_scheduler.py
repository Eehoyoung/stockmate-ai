"""
news_scheduler.py
주기적으로 한국 금융 뉴스를 수집하고 Claude에게 분석을 요청한 후
결과를 Redis에 저장하는 asyncio 기반 스케쥴러.

Redis 저장 키:
  news:latest              – 수집된 뉴스 JSON 배열      (TTL 2h)
  news:analysis            – Claude 분석 전체 결과 JSON  (TTL 1h)
  news:trading_control     – CONTINUE|CAUTIOUS|PAUSE     (TTL 1h)
  news:sector_recommend    – 추천 섹터 JSON 배열          (TTL 1h)
  news:market_sentiment    – BULLISH|NEUTRAL|BEARISH      (TTL 1h)
  news:prev_control        – 이전 trading_control        (TTL 2h)
  news_alert_queue         – 텔레그램 알림 대기 큐        (TTL 12h)
"""

import asyncio
import json
import logging
import os
import time

from news_collector import collect_news
from news_analyzer  import analyze_news

logger = logging.getLogger(__name__)

NEWS_INTERVAL_MIN  = int(os.getenv("NEWS_INTERVAL_MIN",  "30"))
NEWS_MARKET_ONLY   = os.getenv("NEWS_MARKET_ONLY",  "false").lower() == "true"
NEWS_ENABLED       = os.getenv("NEWS_ENABLED",       "true").lower()  == "true"

_KEY_LATEST      = "news:latest"
_KEY_ANALYSIS    = "news:analysis"
_KEY_CONTROL     = "news:trading_control"
_KEY_SECTORS     = "news:sector_recommend"
_KEY_SENTIMENT   = "news:market_sentiment"
_KEY_PREV_CTRL   = "news:prev_control"
_KEY_ALERT_QUEUE  = "news_alert_queue"
_KEY_SCORED_QUEUE = "ai_scored_queue"

_TTL_LATEST    = 7200   # 2h
_TTL_ANALYSIS  = 3600   # 1h
_TTL_ALERT_Q   = 43200  # 12h


def _is_market_hours() -> bool:
    """현재 시간이 뉴스 분석 허용 시간대(월~금 08:30~16:00)인지 확인"""
    from datetime import datetime
    now = datetime.now()
    if now.weekday() >= 5:  # 토(5), 일(6) 제외
        return False
    return (8, 30) <= (now.hour, now.minute) < (16, 0)


async def _save_to_redis(rdb, news_list: list, analysis: dict) -> None:
    """분석 결과를 Redis에 저장"""
    try:
        # 뉴스 원본
        await rdb.set(_KEY_LATEST,   json.dumps(news_list, ensure_ascii=False), ex=_TTL_LATEST)
        # Claude 분석 전체
        await rdb.set(_KEY_ANALYSIS, json.dumps(analysis,  ensure_ascii=False), ex=_TTL_ANALYSIS)
        # 개별 키
        await rdb.set(_KEY_CONTROL,   analysis.get("trading_control",     "CONTINUE"), ex=_TTL_ANALYSIS)
        await rdb.set(_KEY_SENTIMENT, analysis.get("market_sentiment",    "NEUTRAL"),  ex=_TTL_ANALYSIS)
        await rdb.set(
            _KEY_SECTORS,
            json.dumps(analysis.get("recommended_sectors", []), ensure_ascii=False),
            ex=_TTL_ANALYSIS,
        )
        logger.info("[NewsScheduler] Redis 저장 완료 – control=%s sectors=%s",
                    analysis.get("trading_control"),
                    analysis.get("recommended_sectors"))
    except Exception as e:
        logger.error("[NewsScheduler] Redis 저장 실패: %s", e)


async def _check_and_alert(rdb, new_control: str, analysis: dict) -> None:
    """
    trading_control 상태 변경 시 알림 발행.
    - PAUSE 전환: 사용자 확인이 필요하므로 PAUSE_CONFIRM_REQUEST 를 ai_scored_queue 에 발행.
      Redis 키는 아직 변경하지 않음 (사용자 컨펌 후 Node.js 봇이 직접 API 호출).
    - CONTINUE / CAUTIOUS 전환: 기존대로 NEWS_ALERT 를 news_alert_queue 에 발행.
    """
    try:
        prev_control = await rdb.get(_KEY_PREV_CTRL) or "CONTINUE"
        if prev_control == new_control:
            return

        logger.info("[NewsScheduler] 매매 제어 변경 감지: %s → %s", prev_control, new_control)

        if new_control == "PAUSE":
            # PAUSE 는 사용자 컨펌 요청으로 대체 – Redis 키는 변경하지 않음
            confirm_req = {
                "type":             "PAUSE_CONFIRM_REQUEST",
                "prev_control":     prev_control,
                "market_sentiment": analysis.get("market_sentiment", "NEUTRAL"),
                "sectors":          analysis.get("recommended_sectors", []),
                "risk_factors":     analysis.get("risk_factors", []),
                "summary":          analysis.get("summary", ""),
                "confidence":       analysis.get("confidence", "LOW"),
                "ts":               time.time(),
            }
            await rdb.lpush(_KEY_SCORED_QUEUE, json.dumps(confirm_req, ensure_ascii=False))
            await rdb.expire(_KEY_SCORED_QUEUE, _TTL_ALERT_Q)
            # prev_control 을 PAUSE 로 업데이트하여 30분 뒤 중복 컨펌 요청 방지
            # (news:trading_control 은 사용자 컨펌 후 Node.js 봇이 API 호출로 변경)
            await rdb.set(_KEY_PREV_CTRL, "PAUSE", ex=_TTL_LATEST)
            logger.info("[NewsScheduler] PAUSE_CONFIRM_REQUEST 발행 (사용자 컨펌 대기 중)")
        else:
            # CONTINUE / CAUTIOUS 전환 – 즉시 적용
            alert = {
                "type":             "NEWS_ALERT",
                "trading_control":  new_control,
                "prev_control":     prev_control,
                "market_sentiment": analysis.get("market_sentiment", "NEUTRAL"),
                "sectors":          analysis.get("recommended_sectors", []),
                "risk_factors":     analysis.get("risk_factors", []),
                "summary":          analysis.get("summary", ""),
                "confidence":       analysis.get("confidence", "LOW"),
                "ts":               time.time(),
            }
            await rdb.lpush(_KEY_ALERT_QUEUE, json.dumps(alert, ensure_ascii=False))
            await rdb.expire(_KEY_ALERT_QUEUE, _TTL_ALERT_Q)
            await rdb.set(_KEY_PREV_CTRL, new_control, ex=_TTL_LATEST)
            logger.info("[NewsScheduler] NEWS_ALERT 발행 control=%s", new_control)

    except Exception as e:
        logger.warning("[NewsScheduler] 알림 발행 실패: %s", e)


async def run_once(rdb) -> None:
    """뉴스 수집 → Claude 분석 → Redis 저장을 1회 실행"""
    start = time.time()
    logger.info("[NewsScheduler] 뉴스 수집 시작")

    try:
        # 1. 뉴스 수집
        news_list = await collect_news(rdb)

        # 2. Claude 분석
        analysis = await analyze_news(news_list, rdb)
        analysis["news_count"] = len(news_list)
        analysis["analyzed_at"] = time.time()

        # 3. Redis 저장
        await _save_to_redis(rdb, news_list, analysis)

        # 4. 상태 변경 알림
        new_control = analysis.get("trading_control", "CONTINUE")
        await _check_and_alert(rdb, new_control, analysis)

        elapsed = time.time() - start
        logger.info("[NewsScheduler] 완료 (%.1fs) – news=%d control=%s sentiment=%s",
                    elapsed, len(news_list), new_control, analysis.get("market_sentiment"))

    except Exception as e:
        logger.error("[NewsScheduler] 실행 오류: %s", e)


async def run_news_scheduler(rdb) -> None:
    """
    뉴스 스케쥴러 메인 루프.
    NEWS_INTERVAL_MIN 간격으로 뉴스를 수집·분석한다.
    """
    if not NEWS_ENABLED:
        logger.info("[NewsScheduler] 비활성화 (NEWS_ENABLED=false)")
        return

    interval_sec = NEWS_INTERVAL_MIN * 60
    logger.info("[NewsScheduler] 시작 – 주기=%d분 허용시간=월~금 08:30~16:00",
                NEWS_INTERVAL_MIN)

    # 시작 시 즉시 1회 실행 (허용 시간대인 경우에만)
    if _is_market_hours():
        await run_once(rdb)
    else:
        logger.info("[NewsScheduler] 장외 시간 – 시작 시 실행 건너뜀")

    while True:
        await asyncio.sleep(interval_sec)

        if not _is_market_hours():
            logger.debug("[NewsScheduler] 장외 시간 – 건너뜀")
            continue

        await run_once(rdb)
