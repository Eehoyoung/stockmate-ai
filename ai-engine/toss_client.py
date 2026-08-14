from __future__ import annotations
"""
toss_client.py
토스증권 Open API(조회 전용) 클라이언트 — ai-engine 측 사용처:
  - 종목검색(Ranking): S4/S13 후보풀 보강 (candidates_builder.py)
  - 종목별 공매도/신용거래/대차거래: Claude 프롬프트 참고정보 + 일부 전략 rule bonus (analyzer.py, scorer.py)

source of truth: docs/toss_invest_openapi_claude_required.md
계좌/자산/주문/조건주문 API는 이 모듈에서 절대 구현하지 않는다 (문서 0장 규칙).

토큰 발급 주체는 api-orchestrator(Java) 단독이다 — 토스는 client당 유효 토큰이
1개이며 재발급 시 이전 토큰이 즉시 무효화되므로, 이 모듈은 Redis "toss:token"을
읽기만 하고 절대 자체 발급하지 않는다 (Kiwoom "kiwoom:token"과 동일 패턴).
"""

import asyncio
import json
import logging
import os
import time as _time
from datetime import timedelta, timezone

import httpx

from http_utils import coalesce_request
from utils import normalize_stock_code

logger = logging.getLogger(__name__)
_KST = timezone(timedelta(hours=9))

TOSS_BASE_URL = os.getenv("TOSS_BASE_URL", "https://openapi.tossinvest.com")
REDIS_TOSS_TOKEN_KEY = "toss:token"


def toss_enabled() -> bool:
    return str(os.getenv("TOSS_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}


class _TossRateLimiter:
    """단순 로컬 페이싱 — Toss group 한도(STOCK_TRADING_TREND 10/s, RANKING 5/s,
    MARKET_INDICATOR 10/s)에 비해 ai-engine 호출량이 훨씬 적어(스캔당 수십 건)
    Kiwoom처럼 Redis 교차프로세스 코디네이션까지는 불필요하다."""

    def __init__(self, rate_per_sec: float = 4.0):
        self._interval = 1.0 / max(rate_per_sec, 0.001)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = _time.monotonic()
            wait = self._interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = _time.monotonic()


_rate_limiter = _TossRateLimiter()


async def _get_toss_token(rdb) -> str | None:
    if rdb is None:
        return None
    try:
        token = await rdb.get(REDIS_TOSS_TOKEN_KEY)
        if isinstance(token, bytes):
            token = token.decode("utf-8", errors="ignore")
        return token or None
    except Exception as e:
        logger.debug("[toss_client] toss:token 조회 실패: %s", e)
        return None


async def _get(path: str, params: dict, token: str, *, api_label: str, timeout: float = 8.0) -> tuple[dict | None, dict]:
    meta: dict = {"source": "rest", "api": api_label, "latency_ms": 0, "error": None}
    t0 = _time.monotonic()
    await _rate_limiter.acquire()
    try:
        async with httpx.AsyncClient(base_url=TOSS_BASE_URL, timeout=timeout) as client:
            resp = await client.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            meta["error"] = f"429 rate_limit retry_after={retry_after}"
            logger.warning("[toss_client] 429 %s retry_after=%s — 이번 호출 스킵", api_label, retry_after)
            return None, meta
        if resp.status_code >= 400:
            meta["error"] = f"http_{resp.status_code}: {resp.text[:200]}"
            logger.debug("[toss_client] %s 오류 status=%s", api_label, resp.status_code)
            return None, meta
        return resp.json(), meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[toss_client] %s 요청 실패: %s", api_label, e)
        return None, meta


# ── 종목검색(Ranking) ──────────────────────────────────────────────────

async def fetch_market_ranking(
    rdb,
    *,
    type_: str = "MARKET_TRADING_AMOUNT",
    market_country: str = "KR",
    duration: str = "realtime",
    count: int = 100,
    exclude_investment_caution: bool = True,
) -> list[dict]:
    """GET /api/v1/rankings. 실패/미설정 시 빈 리스트."""
    if not toss_enabled():
        return []
    token = await _get_toss_token(rdb)
    if not token:
        return []

    async def _fetch():
        data, meta = await _get(
            "/api/v1/rankings",
            {
                "type": type_,
                "marketCountry": market_country,
                "duration": duration,
                "count": count,
                "excludeInvestmentCaution": str(exclude_investment_caution).lower(),
            },
            token,
            api_label=f"rankings:{type_}:{duration}",
        )
        if not data:
            return []
        return (data.get("result") or {}).get("rankings") or []

    return await coalesce_request(
        ("toss:rankings", type_, market_country, duration, count),
        _fetch,
    )


# ── 종목별 캔들(OHLCV, MARKET_DATA_CHART group) ──────────────────────────
# 최대 200봉. Kiwoom ka10081(일봉)이 공유 글로벌 리미터 혼잡으로 실패/부족할 때
# ma_utils.py의 폴백 소스로 사용 — Toss가 primary가 아니라 Kiwoom 안전망이 부족할
# 때만 보충하는 역할(장세 데이터의 "write-order fallback"과 같은 방향).

async def fetch_stock_candles(
    rdb, stk_cd: str, *, interval: str = "1d", count: int = 200,
) -> list[dict]:
    """GET /api/v1/candles. interval은 "1m" 또는 "1d"만 허용. 실패/미설정 시 빈 리스트.
    응답은 최신봉이 index 0(Kiwoom ka10081과 동일 순서)."""
    stk_cd = normalize_stock_code(stk_cd)
    if not toss_enabled() or not stk_cd:
        return []
    token = await _get_toss_token(rdb)
    if not token:
        return []

    async def _fetch():
        data, meta = await _get(
            "/api/v1/candles",
            {"symbol": stk_cd, "interval": interval, "count": min(count, 200)},
            token,
            api_label=f"candles:{interval}",
        )
        if not data:
            return []
        return (data.get("result") or {}).get("candles") or []

    return await coalesce_request(
        ("toss:candles", stk_cd, interval, count),
        _fetch,
    )


# ── 종목별 공매도/신용거래/대차거래 (STOCK_TRADING_TREND group) ─────────
# 세 API 모두 일별 확정치이며 갱신이 느리다(공매도/대차 당일 저녁, 신용 T+1
# 새벽) — 장중에는 최신 레코드가 통상 전일자다. 실시간 트리거가 아니라
# 완만한 리스크 컨텍스트로만 사용한다.

async def _fetch_trend(path: str, stk_cd: str, count: int, token: str, api_label: str) -> dict | None:
    data, meta = await _get(
        path, {"count": count}, token, api_label=api_label,
    )
    if not data:
        return None
    result = data.get("result") or {}
    records = result.get("records") or []
    return records[0] if records else None


async def _fetch_trend_cached(
    rdb, stk_cd: str, *, redis_prefix: str, path_suffix: str, api_label: str,
    count: int, ttl_sec: int,
) -> dict | None:
    stk_cd = normalize_stock_code(stk_cd)
    if not toss_enabled() or not stk_cd:
        return None
    token = await _get_toss_token(rdb)
    if not token:
        return None

    cache_key = f"toss:{redis_prefix}:{stk_cd}"
    if rdb:
        try:
            cached = await rdb.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    record = await coalesce_request(
        (f"toss:{redis_prefix}", stk_cd),
        lambda: _fetch_trend(f"/api/v1/stocks/{stk_cd}/{path_suffix}", stk_cd, count, token, api_label),
    )
    if record and rdb:
        try:
            await rdb.set(cache_key, json.dumps(record, ensure_ascii=False), ex=ttl_sec)
        except Exception:
            pass
    return record


async def fetch_short_selling(rdb, stk_cd: str, *, count: int = 1, ttl_sec: int = 1800) -> dict | None:
    """공매도 동향 — 당일 확정치는 저녁 반영, 장중 최신 레코드는 통상 전일자."""
    return await _fetch_trend_cached(
        rdb, stk_cd, redis_prefix="short_selling", path_suffix="short-selling",
        api_label="short-selling", count=count, ttl_sec=ttl_sec,
    )


async def fetch_credit_trades(rdb, stk_cd: str, *, count: int = 1, ttl_sec: int = 1800) -> dict | None:
    """신용거래(융자/대주) 동향 — T+1 새벽 반영, 장중 최신 레코드는 전전일자일 수 있음."""
    return await _fetch_trend_cached(
        rdb, stk_cd, redis_prefix="credit_trades", path_suffix="credit-trades",
        api_label="credit-trades", count=count, ttl_sec=ttl_sec,
    )


async def fetch_securities_lending(rdb, stk_cd: str, *, count: int = 1, ttl_sec: int = 1800) -> dict | None:
    """대차거래 동향 — 당일 확정치는 저녁 반영, 장중 최신 레코드는 통상 전일자."""
    return await _fetch_trend_cached(
        rdb, stk_cd, redis_prefix="securities_lending", path_suffix="securities-lending",
        api_label="securities-lending", count=count, ttl_sec=ttl_sec,
    )



# ── 매수 유의사항(관리종목/투자경고/투자위험/단기과열/VI 등) ────────────
# 정리매매/투자경고/투자위험은 거래소 공시 기준 일배치, VI는 수 초 내 반영.
# S2의 실시간 VI 감시(Kiwoom WS)를 대체하지 않는 보조 신호 — 캐시 TTL을
# 짧게(600s) 두어 VI_STATIC/VI_DYNAMIC 상태가 과도하게 stale해지지 않게 한다.

WARNING_SEVERE_TYPES = frozenset({
    "LIQUIDATION_TRADING",   # 정리매매 — 상장폐지 절차 진행 중
    "INVESTMENT_WARNING",    # 투자경고종목
    "INVESTMENT_RISK",       # 투자위험종목
})
WARNING_CAUTION_TYPES = frozenset({
    "OVERHEATED",             # 단기과열종목
    "VI_STATIC",
    "VI_DYNAMIC",
    "VI_STATIC_AND_DYNAMIC",
})


async def _fetch_warnings_raw(stk_cd: str, token: str) -> list[dict]:
    data, meta = await _get(
        f"/api/v1/stocks/{stk_cd}/warnings", {}, token, api_label="warnings",
    )
    if data is None:
        return []
    return data.get("result") or []


async def fetch_stock_warnings(rdb, stk_cd: str, *, ttl_sec: int = 600) -> list[dict]:
    """활성 매수 유의사항 목록 — 실패/미설정/유의사항 없음 시 빈 리스트."""
    stk_cd = normalize_stock_code(stk_cd)
    if not toss_enabled() or not stk_cd:
        return []
    token = await _get_toss_token(rdb)
    if not token:
        return []

    cache_key = f"toss:warnings:{stk_cd}"
    if rdb:
        try:
            cached = await rdb.get(cache_key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass

    items = await coalesce_request(
        ("toss:warnings", stk_cd),
        lambda: _fetch_warnings_raw(stk_cd, token),
    )
    if rdb:
        try:
            await rdb.set(cache_key, json.dumps(items, ensure_ascii=False), ex=ttl_sec)
        except Exception:
            pass
    return items


async def fetch_stock_risk_context(rdb, stk_cd: str, *, timeout: float = 3.0) -> dict:
    """공매도/신용거래/대차거래/매수유의사항을 한 번에 조회 — queue_worker(rule
    scoring)와 analyzer(Claude 프롬프트)가 공유하는 단일 진입점. 네 호출 모두
    Redis 캐시를 거치므로 같은 종목에 대한 중복 호출은 거의 발생하지 않는다.
    실패/타임아웃/미설정 시 빈 dict — 호출부의 rule scoring이나 Claude 분석
    흐름을 절대 막지 않는다."""
    if not toss_enabled() or not rdb or not stk_cd:
        return {}
    try:
        short_sell, credit, lending, warnings = await asyncio.wait_for(
            asyncio.gather(
                fetch_short_selling(rdb, stk_cd),
                fetch_credit_trades(rdb, stk_cd),
                fetch_securities_lending(rdb, stk_cd),
                fetch_stock_warnings(rdb, stk_cd),
                return_exceptions=True,
            ),
            timeout=timeout,
        )
    except Exception:
        return {}
    result: dict = {}
    if isinstance(short_sell, dict):
        result["short_selling"] = short_sell
    if isinstance(credit, dict):
        result["credit_trades"] = credit
    if isinstance(lending, dict):
        result["securities_lending"] = lending
    if isinstance(warnings, list):
        result["warnings"] = warnings
    return result
