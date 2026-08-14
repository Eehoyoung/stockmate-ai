from __future__ import annotations
"""
candidates_builder.py
Python 전담 후보 풀 적재 모듈.
Java CandidateService 역할을 Python으로 이관.

실행: engine.py 에서 asyncio.create_task(run_candidate_builder(rdb)) 로 기동
갱신 주기: CANDIDATE_BUILD_INTERVAL_SEC (기본 600초 = 10분)
"""
import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime, time, timedelta, timezone

from http_utils import validate_kiwoom_response, kiwoom_post
from redis_reader import get_strength_with_status
from strategy_meta import normalize_market_type as _normalize_market_type
from toss_client import fetch_market_ranking as _toss_fetch_market_ranking, toss_enabled as _toss_enabled
from utils import safe_float as _clean, normalize_stock_code
from config import KIWOOM_BASE_URL, MARKET_LIST as MARKETS

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

CANDIDATE_BUILD_INTERVAL_SEC = int(os.getenv("CANDIDATE_BUILD_INTERVAL_SEC", "600"))
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.8"))
S3S5_STATUS_TTL_SEC = int(os.getenv("S3S5_STATUS_TTL_SEC", "1800"))
CANDIDATE_POOL_OWNER = str(os.getenv("CANDIDATE_POOL_OWNER", "PYTHON")).strip().upper()

# 품질 필터 / watchlist ZSET 기능 플래그
ENABLE_CANDIDATE_QUALITY_FILTER = os.getenv("ENABLE_CANDIDATE_QUALITY_FILTER", "false").lower() in {"1", "true", "yes"}
ENABLE_WATCHLIST_ZSET = os.getenv("ENABLE_WATCHLIST_ZSET", "true").lower() in {"1", "true", "yes"}
CANDIDATE_MIN_MARKET_CAP_EOK = float(os.getenv("CANDIDATE_MIN_MARKET_CAP_EOK", "800"))
CANDIDATE_MIN_TRDE_AMT = float(os.getenv("CANDIDATE_MIN_TRDE_AMT", "500000"))

# 섹터 과열 임계치 (같은 섹터 후보가 이 수 이상이면 하향)
_SECTOR_HEAT_MAX = int(os.getenv("CANDIDATE_SECTOR_HEAT_MAX", "10"))


def _env_flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(str(os.getenv(name, default)).strip()))
    except (TypeError, ValueError):
        return default


# 토스 종목검색(Ranking) 후보풀 보강 — S4/S13은 이미 Kiwoom ka10023(급등종목)로
# 같은 성격의 후보를 뽑고 있으므로, 이 보강은 새 판단기준이 아니라 "같은 flu_rt
# 밴드를 만족하는 종목을 더 넓게(Kiwoom 페이지네이션/rate-limit 누락분까지)
# 찾아내는" 순수 추가(union) 역할이다. 기존 Kiwoom 후보는 그대로 두고 뒤에
# 덧붙이며, 개별 종목의 최종 진입 여부는 이후 rule score/Claude 게이트가
# 동일하게 적용한다 (2026-08-11).
TOSS_RANKING_SUPPLEMENT_ENABLED = _env_flag("TOSS_RANKING_SUPPLEMENT_ENABLED", "true")
TOSS_RANKING_SUPPLEMENT_LIMIT = _int_env("TOSS_RANKING_SUPPLEMENT_LIMIT", 20)

CANDIDATE_LIMIT_S1 = _int_env("CANDIDATE_LIMIT_S1", 100)
CANDIDATE_LIMIT_S2 = _int_env("CANDIDATE_LIMIT_S2", 50)
CANDIDATE_LIMIT_S3 = _int_env("CANDIDATE_LIMIT_S3", 150)
CANDIDATE_LIMIT_S4 = _int_env("CANDIDATE_LIMIT_S4", 100)
CANDIDATE_LIMIT_S5 = _int_env("CANDIDATE_LIMIT_S5", 150)
CANDIDATE_LIMIT_S6 = _int_env("CANDIDATE_LIMIT_S6", 150)
CANDIDATE_LIMIT_S7 = _int_env("CANDIDATE_LIMIT_S7", 100)
CANDIDATE_LIMIT_S8 = _int_env("CANDIDATE_LIMIT_S8", 220)
CANDIDATE_LIMIT_S9 = _int_env("CANDIDATE_LIMIT_S9", 220)
CANDIDATE_LIMIT_S10 = _int_env("CANDIDATE_LIMIT_S10", 150)
CANDIDATE_LIMIT_S11 = _int_env("CANDIDATE_LIMIT_S11", 120)
CANDIDATE_LIMIT_S12 = _int_env("CANDIDATE_LIMIT_S12", 50)
CANDIDATE_LIMIT_S13 = _int_env("CANDIDATE_LIMIT_S13", 150)
CANDIDATE_LIMIT_S14 = _int_env("CANDIDATE_LIMIT_S14", 100)
CANDIDATE_LIMIT_S15 = _int_env("CANDIDATE_LIMIT_S15", 150)
CANDIDATE_WATCHLIST_PRIORITY_LIMIT = _int_env("CANDIDATE_WATCHLIST_PRIORITY_LIMIT", 300)
CANDIDATE_LIVE_CONFLUENCE_LIMIT = _int_env("CANDIDATE_LIVE_CONFLUENCE_LIMIT", 100)
CANDIDATE_LIVE_CONFLUENCE_TTL_SEC = _int_env("CANDIDATE_LIVE_CONFLUENCE_TTL_SEC", 900)


def now_kst_str() -> str:
    """현재 KST 시각을 ISO 포맷 문자열로 반환"""
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _decode_redis_hash(data: dict | None) -> dict:
    decoded: dict = {}
    for key, value in (data or {}).items():
        if isinstance(key, bytes):
            key = key.decode("utf-8", errors="ignore")
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        decoded[str(key)] = value
    return decoded


def _as_float(value, default: float = 0.0) -> float:
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        return float(str(value).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return default


ENABLE_S3S5_LATENCY_STATUS = _env_flag("ENABLE_S3S5_LATENCY_STATUS")
ENABLE_CANDIDATES_META = _env_flag("ENABLE_CANDIDATES_META")
ENABLE_SESSION_CANDIDATE_BUILDER = _env_flag("ENABLE_SESSION_CANDIDATE_BUILDER")

SESSION_PRE_MARKET = "pre_market"
SESSION_OPENING_RECOVERY = "opening_recovery"
SESSION_INTRADAY = "intraday"
SESSION_S12_ONLY = "s12_only"
SESSION_IDLE = "idle"


try:
    from market_session import get_candidate_builder_session as _external_candidate_builder_session
except Exception:
    _external_candidate_builder_session = None


def _local_candidate_builder_session(now: time) -> str:
    if time(7, 25) <= now <= time(8, 25):
        return SESSION_PRE_MARKET
    if time(8, 25) < now < time(9, 5):
        return SESSION_OPENING_RECOVERY
    if time(9, 5) <= now < time(14, 30):
        return SESSION_INTRADAY
    if time(14, 30) <= now <= time(15, 10):
        return SESSION_S12_ONLY
    return SESSION_IDLE


def _normalize_candidate_builder_session(session) -> str:
    value = getattr(session, "value", session)
    value = str(value or "").strip().lower()
    if value in {SESSION_PRE_MARKET, "pre", "premarket", "before_open"}:
        return SESSION_PRE_MARKET
    if value in {SESSION_OPENING_RECOVERY, "opening", "opening_recovery", "auction"}:
        return SESSION_OPENING_RECOVERY
    if value in {SESSION_INTRADAY, "regular", "market", "open"}:
        return SESSION_INTRADAY
    if value in {SESSION_S12_ONLY, "closing", "close", "closing_auction", "after_1450"}:
        return SESSION_S12_ONLY
    return SESSION_IDLE


def _candidate_builder_session(now: datetime | time) -> str:
    if _external_candidate_builder_session:
        try:
            session = _external_candidate_builder_session(now)
            if session:
                return _normalize_candidate_builder_session(session)
        except TypeError:
            try:
                session = _external_candidate_builder_session()
                if session:
                    return _normalize_candidate_builder_session(session)
            except Exception:
                pass
        except Exception:
            pass
    return _local_candidate_builder_session(now)


async def _incr_pipeline_daily(rdb, strategy: str, field: str) -> None:
    if not rdb or not strategy:
        return
    try:
        today = datetime.now(KST).strftime("%Y-%m-%d")
        key = f"pipeline_daily:{today}:{strategy}"
        await rdb.hincrby(key, field, 1)
        await rdb.expire(key, 172800)
    except Exception:
        pass


async def _write_candidates_meta(
    rdb,
    *,
    strategy: str,
    market: str,
    codes: list[str],
    ttl: int,
    source: str,
    elapsed_ms: int | None = None,
    state: str = "ok",
) -> None:
    if not ENABLE_CANDIDATES_META or not rdb:
        return
    try:
        mapping = {
            "strategy": strategy,
            "market": market,
            "count": str(len(codes)),
            "source": source,
            "ttl": str(ttl),
            "state": state,
            "updated_at": str(int(_time.time())),
            "codes_json": json.dumps(codes, ensure_ascii=False),
        }
        if elapsed_ms is not None:
            mapping["latency_ms"] = str(elapsed_ms)
        key = f"candidates_meta:{strategy.lower()}:{market}"
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, ttl)
    except Exception as meta_err:
        logger.debug("[builder] candidates_meta write failed [%s %s]: %s", strategy, market, meta_err)


async def _record_s3s5_status(
    rdb,
    *,
    strategy: str,
    market: str,
    count: int,
    elapsed_ms: int,
    state: str,
    source: str,
) -> None:
    if not ENABLE_S3S5_LATENCY_STATUS or not rdb:
        return
    try:
        key = f"status:candidates_builder:{strategy}:{market}"
        await rdb.hset(
            key,
            mapping={
                "strategy": strategy,
                "market": market,
                "state": state,
                "count": str(count),
                "latency_ms": str(elapsed_ms),
                "source": source,
                "updated_at": str(int(_time.time())),
            },
        )
        await rdb.expire(key, S3S5_STATUS_TTL_SEC)
    except Exception as status_err:
        logger.debug("[builder] S3/S5 status write failed [%s %s]: %s", strategy, market, status_err)


# ── 공통 유틸 ──────────────────────────────────────────────────────────

# stk_cnd="20" 미지원 API 결과에 적용하는 종목명 기반 2차 필터
# 계획 4.4 섹션 기준: ETF/ETN/SPAC/우선주/리츠/인프라 등 포함
_EXCLUDE_STK_NM_KEYWORDS = (
    "ETF", "ETN", "레버리지", "인버스", "2X", "곱버스", "SPAC", "스팩",
    "선물", "합성", "액티브", "우선", "리츠", "인프라",
)

# 전략별 우선순위 가중치 (watchlist ZSET 점수 계산용)
# NOTE(2026-08-05): S11(120개/시장, 240개 합산)은 S8/S9(220개/시장)와 비슷하거나
# 더 넓은 유니버스를 갖는 스윙 전략인데도 예전에는 18점(s3/s5/s6/s14와 동일)으로
# 낮게 책정되어 있었다. STRICT_REST_ENTER_GUARD(queue_worker.py)는 WS 실시간
# 커버리지(top-200 watchlist)를 벗어난 종목의 ENTER를 강제 CANCEL하는데, S11의
# 낮은 가중치가 통합 watchlist ZSET(candidates:watchlist:z) 상위 200 슬롯 경쟁에서
# 불리하게 작동해 정당한 ENTER 신호가 REST-fallback만 남은 채 차단되는 사고가
# 있었다(2026-08-05 조사). S7/S8/S9와 같은 20점 티어로 상향해 유니버스 크기 대비
# 형평성을 맞춘다.
#: 후보 풀 스캔 상한. 전략을 추가할 때 이 값만 올리면 watchlist 통합 루프가
#: 자동으로 따라온다. 하드코딩된 range(1, 16)이 s16을 누락시킨 사고 재발 방지용.
_MAX_STRATEGY_NUM = 16

_STRATEGY_PRIORITY_WEIGHT = {
    "s1": 30, "s2": 30, "s4": 30, "s13": 30,
    "s10": 25,
    "s7": 20, "s8": 20, "s9": 20, "s11": 20, "s15": 20,
    "s12": 15,
    # s16은 그동안 DB CHECK 제약(V53에서 수정)과 watchlist range 버그로 신호를
    # 한 건도 낸 적이 없어 실측 성과가 없다. 기존 기본값(15)과 동일하게 두어
    # 현재 랭킹 동작을 바꾸지 않고, 실제 신호가 쌓인 뒤 티어를 재검토한다.
    # WS 구독 슬롯이 이미 포화(200 후보 → 70 슬롯) 상태라 섣불리 올리면
    # 검증된 다른 전략의 실시간 커버리지를 잠식한다.
    "s16": 15,
    "s3": 18, "s5": 18, "s6": 18, "s14": 18,
}
# 실시간 필수 전략 (추가 가점 부여)
_REALTIME_CRITICAL_STRATEGIES = {"s1", "s2", "s4", "s13"}

# 즉시 운영에 반영하는 추가 순위정보 소스의 가중치. 점수는 기존 전략별
# 후보 풀을 제거하지 않고, 같은 풀 안에서 우선순위를 결정하는 데 사용한다.
_LIVE_CONFLUENCE_WEIGHTS = {
    "liquidity": 24,       # ka10030 당일 거래량/거래대금 상위
    "foreign_net_buy": 26, # ka10034 외국인 순매수 상위
    "same_net_buy": 26,    # ka10062 기관·외국인 동시 순매수
    "bid_balance": 12,     # ka10020 매수잔량 비율 상위
    "bid_surge": 7,        # ka10021 매수잔량 급증
    "ratio_surge": 5,      # ka10022 매수/매도 잔량비율 급증
}


def _is_etf_or_etn_name(stk_nm: object) -> bool:
    """Return whether a Kiwoom response name identifies an ETF or ETN."""
    normalized = str(stk_nm or "").upper()
    return "ETF" in normalized or "ETN" in normalized


async def _filter_individual_stocks(rdb, codes: list[str]) -> list[str]:
    """stock:code_map Redis 해시에서 종목명을 일괄 조회해 ETF/ETN/파생 종목을 제거한다.
    Redis 장애나 이름 미조회 시 원본 목록을 그대로 반환해 안전하게 fallback한다."""
    if not codes or not rdb:
        return codes
    try:
        pipe = rdb.pipeline()
        for code in codes:
            pipe.hget("stock:code_map", code)
        names = await pipe.execute()
        filtered = [
            code for code, name in zip(codes, names)
            if not (name and any(kw in name for kw in _EXCLUDE_STK_NM_KEYWORDS))
        ]
        removed = len(codes) - len(filtered)
        if removed:
            logger.debug("[builder] ETF/ETN 필터: %d종목 제거 (잔류 %d)", removed, len(filtered))
        return filtered
    except Exception as exc:
        logger.debug("[builder] ETF 이름 필터 실패 – 원본 반환: %s", exc)
        return codes


def _live_confluence_requests(market: str, as_of: datetime | None = None) -> tuple[tuple[str, dict, str, str], ...]:
    """Return the documented Kiwoom ranking requests used for live prioritization.

    These calls intentionally run only in the intraday builder.  All source
    results are used immediately to reorder the already strategy-qualified
    pools; they are never written to a shadow-only key.
    """
    as_of = as_of or datetime.now(KST)
    start_dt = (as_of - timedelta(days=5)).strftime("%Y%m%d")
    end_dt = as_of.strftime("%Y%m%d")
    return (
        ("liquidity", {
            "mrkt_tp": market, "sort_tp": "3", "mang_stk_incls": "16",
            "crd_tp": "0", "trde_qty_tp": "0", "pric_tp": "0",
            "trde_prica_tp": "0", "mrkt_open_tp": "0", "stex_tp": "3",
        }, "ka10030", "tdy_trde_qty_upper"),
        ("foreign_net_buy", {
            "mrkt_tp": market, "trde_tp": "2", "dt": "0", "stex_tp": "3",
        }, "ka10034", "for_dt_trde_upper"),
        ("same_net_buy", {
            "strt_dt": start_dt, "end_dt": end_dt, "mrkt_tp": market,
            "trde_tp": "1", "sort_cnd": "2", "unit_tp": "1", "stex_tp": "3",
        }, "ka10062", "eql_nettrde_rank"),
        ("bid_balance", {
            "mrkt_tp": market, "sort_tp": "3", "trde_qty_tp": "0010",
            "stk_cnd": "1", "crd_cnd": "0", "stex_tp": "3",
        }, "ka10020", "bid_req_upper"),
        ("bid_surge", {
            "mrkt_tp": market, "trde_tp": "1", "sort_tp": "1", "tm_tp": "30",
            "trde_qty_tp": "10", "stk_cnd": "1", "stex_tp": "3",
        }, "ka10021", "bid_req_sdnin"),
        ("ratio_surge", {
            "mrkt_tp": market, "rt_tp": "1", "tm_tp": "30", "trde_qty_tp": "10",
            "stk_cnd": "1", "stex_tp": "3",
        }, "ka10022", "req_rt_sdnin"),
    )


async def _fetch_live_rank_items(token: str, api_id: str, body: dict, response_key: str) -> list[dict]:
    """Fetch one Kiwoom ranking source for the active candidate prioritizer."""
    headers = {
        "api-id": api_id,
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    resp = await kiwoom_post(
        f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers, body, api_id,
    )
    if resp is None:
        return []
    data = resp.json()
    if not validate_kiwoom_response(data, api_id, logger):
        return []
    rows = data.get(response_key, [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _score_live_confluence(
    candidate_codes: set[str], source_codes: dict[str, set[str]],
) -> tuple[dict[str, float], list[str]]:
    """Score existing strategy candidates and return direct confluence candidates.

    A confluence candidate must be liquid and have either foreign-only or
    institution-plus-foreign net-buy confirmation.  Order-book sources raise
    priority but cannot create a candidate alone.
    """
    scores: dict[str, float] = {}
    for code in candidate_codes:
        score = sum(
            weight for source, weight in _LIVE_CONFLUENCE_WEIGHTS.items()
            if code in source_codes.get(source, set())
        )
        if score:
            scores[code] = float(score)

    liquid = source_codes.get("liquidity", set())
    buy_confirmed = source_codes.get("foreign_net_buy", set()) | source_codes.get("same_net_buy", set())
    confluence_codes = [
        code for code in candidate_codes
        if code in liquid and code in buy_confirmed
    ]
    confluence_codes.sort(key=lambda code: (-scores.get(code, 0.0), code))
    return scores, confluence_codes[:CANDIDATE_LIVE_CONFLUENCE_LIMIT]


async def _prioritize_existing_candidate_pools(rdb, market: str, scores: dict[str, float]) -> None:
    """Reorder live strategy pools in place, preserving membership and each TTL."""
    if not scores:
        return
    for strategy_no in range(1, 16):
        key = f"candidates:s{strategy_no}:{market}"
        try:
            codes = await rdb.lrange(key, 0, -1)
            ttl = await rdb.ttl(key)
        except Exception as exc:
            logger.debug("[builder] live priority pool read failed [%s]: %s", key, exc)
            continue
        if not codes or ttl is None or ttl <= 0:
            continue
        ranked = sorted(
            enumerate(codes),
            key=lambda entry: (-scores.get(normalize_stock_code(entry[1]), 0.0), entry[0]),
        )
        prioritized = [code for _, code in ranked]
        if prioritized != list(codes):
            await _lpush_with_ttl(rdb, key, prioritized, int(ttl))


async def _build_live_confluence(token: str, market: str, rdb) -> None:
    """Immediately enrich active candidate pools with liquidity, flow, and order-book ranks."""
    candidate_codes: set[str] = set()
    for strategy_no in range(1, 16):
        try:
            candidate_codes.update(
                normalize_stock_code(code) for code in await rdb.lrange(f"candidates:s{strategy_no}:{market}", 0, -1)
                if normalize_stock_code(code)
            )
        except Exception:
            continue
    if not candidate_codes:
        return

    source_raw_codes: dict[str, set[str]] = {}
    for source, body, api_id, response_key in _live_confluence_requests(market):
        try:
            items = await _fetch_live_rank_items(token, api_id, body, response_key)
            codes = [normalize_stock_code(item.get("stk_cd", "")) for item in items]
            source_raw_codes[source] = {code for code in codes if code}
        except Exception as exc:
            # Existing candidate order remains live if a supplementary ranking
            # source fails; this is a fail-open enrichment, not a shadow path.
            logger.warning("[builder] live confluence source failed [%s]: %s", api_id, exc)
            source_raw_codes[source] = set()
        await asyncio.sleep(_API_INTERVAL)

    raw_codes = sorted({code for codes in source_raw_codes.values() for code in codes})
    individual_codes = set(await _filter_individual_stocks(rdb, raw_codes))
    source_codes = {
        source: {code for code in codes if code in individual_codes}
        for source, codes in source_raw_codes.items()
    }
    scores, confluence_codes = _score_live_confluence(candidate_codes, source_codes)
    await _prioritize_existing_candidate_pools(rdb, market, scores)

    pipe = rdb.pipeline()
    confluence_key = f"candidates:confluence:{market}"
    pipe.delete(confluence_key)
    if confluence_codes:
        pipe.rpush(confluence_key, *confluence_codes)
    pipe.expire(confluence_key, CANDIDATE_LIVE_CONFLUENCE_TTL_SEC)
    built_at = now_kst_str()
    for code in candidate_codes:
        active_sources = [source for source, codes in source_codes.items() if code in codes]
        key = f"candidate:enrichment:{code}"
        pipe.hset(key, mapping={
            "market": market,
            "score": str(scores.get(code, 0.0)),
            "source_count": str(len(active_sources)),
            "sources": ",".join(active_sources),
            "confluence": str(code in confluence_codes).lower(),
            "built_at": built_at,
        })
        pipe.expire(key, CANDIDATE_LIVE_CONFLUENCE_TTL_SEC)
    await pipe.execute()
    logger.info(
        "[builder] live candidate confluence updated [market=%s candidates=%d confirmed=%d]",
        market, len(candidate_codes), len(confluence_codes),
    )


def _assess_candidate_quality(stk_cd: str, raw_data: dict, strategy_id: str) -> dict:
    """종목별 품질 평가 함수.

    Returns dict with:
    - candidate_quality: "A" | "B" | "C" | "REJECT"
    - quality_score: 0~100
    - liquidity_score: 0~100
    - spread_score: 0~100 (데이터 없으면 50)
    - market_cap_score: 0~100 (데이터 없으면 50)
    - status_filter_pass: bool
    - sector_heat_score: 0~100
    - source_confluence: int
    - reject_reasons: list[str]
    """
    reject_reasons: list[str] = []

    # 1. 종목명 기반 ETF/ETN/SPAC/우선주 필터
    stk_nm = str(raw_data.get("stk_nm", "") or "")
    for kw in _EXCLUDE_STK_NM_KEYWORDS:
        if kw in stk_nm:
            reject_reasons.append(f"name_filter:{kw}")
            break

    # 2. 관리/거래정지 상태 필터 (status 필드가 있는 경우만)
    status_filter_pass = True
    stk_status = str(raw_data.get("status", "") or "")
    if stk_status and stk_status not in {"0", "", "정상"}:
        reject_reasons.append(f"status:{stk_status}")
        status_filter_pass = False

    # 3. 유동성 점수 계산 (거래대금/거래량 기반)
    trde_amt = _clean(raw_data.get("trde_amt", raw_data.get("trde_prica", 0)))
    trde_qty = _clean(raw_data.get("trde_qty", 0))
    market_cap_eok = _clean(
        raw_data.get("market_cap_eok")
        or raw_data.get("market_cap")
        or raw_data.get("mkt_cap")
        or raw_data.get("stk_mkt_cap")
        or 0
    )
    if market_cap_eok > 10_000_000:
        market_cap_eok = market_cap_eok / 100_000_000
    if trde_amt >= 10_000_000:  # 100억 이상
        liquidity_score = 90
    elif trde_amt >= 5_000_000:  # 50억 이상
        liquidity_score = 70
    elif trde_amt >= 1_000_000:  # 10억 이상
        liquidity_score = 50
    elif trde_amt > 0:
        liquidity_score = 30
    elif trde_qty >= 500_000:
        liquidity_score = 60
    elif trde_qty > 0:
        liquidity_score = 40
    else:
        liquidity_score = 50  # 데이터 없음 — 중립

    # 거래대금이 명시적으로 낮은 경우 하향
    if trde_amt > 0 and trde_amt < CANDIDATE_MIN_TRDE_AMT:
        reject_reasons.append("low_liquidity")

    # 4. 스프레드 점수 (데이터 없으면 중립 50)
    spread_score = 50

    # 5. 시가총액 점수 (데이터 없으면 중립 50)
    if market_cap_eok <= 0:
        market_cap_score = 50
    elif market_cap_eok >= 3000:
        market_cap_score = 90
    elif market_cap_eok >= CANDIDATE_MIN_MARKET_CAP_EOK:
        market_cap_score = 70
    elif market_cap_eok >= CANDIDATE_MIN_MARKET_CAP_EOK * 0.75:
        market_cap_score = 50
    else:
        market_cap_score = 30
        reject_reasons.append("low_market_cap")

    # 6. 섹터 과열 점수 (기본 100 — 외부에서 섹터 카운트 적용 시 하향)
    sector_heat_score = 100

    # 7. 출현 소스 수 (기본 1 — _refresh_watchlist에서 집계)
    source_confluence = 1

    # 최종 품질 점수 계산
    if reject_reasons:
        quality_score = 0
        candidate_quality = "REJECT"
    else:
        base = (liquidity_score * 0.5 + spread_score * 0.2 + market_cap_score * 0.2 + sector_heat_score * 0.1)
        quality_score = int(min(100, max(0, base)))
        if quality_score >= 80:
            candidate_quality = "A"
        elif quality_score >= 60:
            candidate_quality = "B"
        else:
            candidate_quality = "C"

    return {
        "candidate_quality": candidate_quality,
        "quality_score": quality_score,
        "liquidity_score": liquidity_score,
        "spread_score": spread_score,
        "market_cap_score": market_cap_score,
        "market_cap_eok": round(market_cap_eok, 2) if market_cap_eok else 0,
        "trde_amt": round(trde_amt, 2) if trde_amt else 0,
        "trde_qty": round(trde_qty, 2) if trde_qty else 0,
        "status_filter_pass": status_filter_pass,
        "sector_heat_score": sector_heat_score,
        "source_confluence": source_confluence,
        "reject_reasons": reject_reasons,
    }


async def _persist_candidate_quality_batch(
    rdb,
    *,
    strategy_id: str,
    market: str,
    source_api: str,
    raw_items: list[dict],
    qualified_codes: list[str],
    ttl: int,
) -> list[str]:
    """raw/qualified/quality Redis 키를 한 번에 적재하고 최종 후보 코드를 반환한다."""
    built_at = now_kst_str()
    qualified_set = set(qualified_codes)
    final_codes: list[str] = []

    quality_rows: dict[str, dict] = {}
    raw_rows: list[str] = []
    qualified_rows: list[str] = []

    for item in raw_items:
        stk_cd = normalize_stock_code(item.get("stk_cd", ""))
        if not stk_cd:
            continue
        raw_rows.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))

        quality = _assess_candidate_quality(stk_cd, item, strategy_id)
        quality.update({
            "stk_cd": stk_cd,
            "strategy_id": strategy_id,
            "market": market,
            "source_api": source_api,
            "built_at": built_at,
        })
        quality_rows[stk_cd] = quality

        is_qualified = stk_cd in qualified_set
        if ENABLE_CANDIDATE_QUALITY_FILTER and quality["candidate_quality"] == "REJECT":
            is_qualified = False
        if is_qualified:
            final_codes.append(stk_cd)
            qualified_rows.append(json.dumps({
                "stk_cd": stk_cd,
                "strategy_id": strategy_id,
                "market": market,
                "source_api": source_api,
                "candidate_quality": quality["candidate_quality"],
                "quality_score": quality["quality_score"],
                "built_at": built_at,
            }, ensure_ascii=False, separators=(",", ":")))

    final_codes = list(dict.fromkeys(final_codes))
    pipe = rdb.pipeline()
    raw_key = f"candidates:raw:{source_api}:{market}"
    qualified_key = f"candidates:qualified:{strategy_id}:{market}"
    pipe.delete(raw_key)
    if raw_rows:
        pipe.rpush(raw_key, *raw_rows)
    pipe.expire(raw_key, ttl)

    pipe.delete(qualified_key)
    if qualified_rows:
        pipe.rpush(qualified_key, *qualified_rows)
    pipe.expire(qualified_key, ttl)

    for stk_cd, quality in quality_rows.items():
        q_key = f"candidate:quality:{stk_cd}"
        mapping = {
            "candidate_quality": quality["candidate_quality"],
            "quality_score": str(quality["quality_score"]),
            "liquidity_score": str(quality["liquidity_score"]),
            "spread_score": str(quality["spread_score"]),
            "market_cap_score": str(quality["market_cap_score"]),
            "market_cap_eok": str(quality["market_cap_eok"]),
            "trde_amt": str(quality["trde_amt"]),
            "trde_qty": str(quality["trde_qty"]),
            "status_filter_pass": str(quality["status_filter_pass"]),
            "sector_heat_score": str(quality["sector_heat_score"]),
            "source_confluence": str(quality["source_confluence"]),
            "reject_reasons": json.dumps(quality["reject_reasons"], ensure_ascii=False),
            "strategy_id": strategy_id,
            "market": market,
            "source_api": source_api,
            "built_at": built_at,
        }
        pipe.hset(q_key, mapping=mapping)
        pipe.expire(q_key, ttl)

    await pipe.execute()
    return final_codes


async def _lpush_with_ttl(rdb, key: str, codes: list[str], ttl: int, meta: dict | None = None) -> None:
    """기존 키를 삭제하고 새 목록을 RPUSH 한 뒤 EXPIRE 설정.

    빈 codes이면 기존 키에 source_status=EMPTY와 built_at을 기록한다.
    이렇게 하면 장중 API 실패(EMPTY)와 진짜 빈 후보를 구분할 수 있다.
    """
    codes = [code for code in dict.fromkeys(normalize_stock_code(code) for code in codes) if code]
    if not codes:
        logger.debug("[builder] %s 빈 결과 – EMPTY 상태 기록 후 stale key 유지", key)
        try:
            meta_key = f"{key}:meta"
            await rdb.hset(meta_key, mapping={
                "source_status": "EMPTY",
                "built_at": now_kst_str(),
                "count": "0",
            })
            await rdb.expire(meta_key, ttl)
        except Exception as e:
            logger.debug("[builder] EMPTY meta 기록 실패 %s: %s", key, e)
        return
    pipe = rdb.pipeline()
    pipe.delete(key)
    pipe.rpush(key, *codes)
    pipe.expire(key, ttl)
    if meta:
        meta_key = f"{key}:meta"
        mapping = {k: str(v) if not isinstance(v, str) else v for k, v in meta.items()}
        pipe.hset(meta_key, mapping=mapping)
        pipe.expire(meta_key, ttl)
    await pipe.execute()
    logger.debug("[builder] %s ← %d종목 (TTL %ds)", key, len(codes), ttl)


# ── ka10029 예상체결 스냅샷 캐시 ─────────────────────────────────────────────

async def _cache_expected_from_ka10029(rdb, items: list[dict], ttl: int = 1800) -> None:
    """ka10029 응답을 ws:expected:{stk_cd} 형태로 백필한다.

    장전 WebSocket 0H가 늦게 붙거나 일시적으로 비어 있어도
    S1/S7 전략이 예상체결가와 예상등락률을 읽을 수 있도록 REST 결과를 동일 키에 적재한다.
    """
    if not items:
        return

    pipe = rdb.pipeline()
    cached = 0

    for rank, item in enumerate(items, start=1):
        stk_cd = normalize_stock_code(item.get("stk_cd", ""))
        exp_cntr_pric = str(item.get("exp_cntr_pric", "")).strip()
        exp_flu_rt = str(item.get("flu_rt", "")).strip()
        exp_cntr_qty = str(item.get("exp_cntr_qty", "")).strip()

        if not stk_cd or not exp_cntr_pric or not exp_flu_rt:
            continue

        key = f"ws:expected:{stk_cd}"
        prev_buy_req = ""
        try:
            prev_buy_req = str(await rdb.hget(key, "buy_req") or "").strip()
        except Exception:
            prev_buy_req = ""

        mapping = {
            "exp_cntr_pric": exp_cntr_pric,
            "exp_flu_rt": exp_flu_rt,
            "exp_cntr_qty": exp_cntr_qty,
            "base_pric": str(item.get("base_pric", "")).strip(),
            "pred_pre_sig": str(item.get("pred_pre_sig", "")).strip(),
            "pred_pre": str(item.get("pred_pre", "")).strip(),
            "sel_req": str(item.get("sel_req", "")).strip(),
            "sel_bid": str(item.get("sel_bid", "")).strip(),
            "buy_bid": str(item.get("buy_bid", "")).strip(),
            "buy_req": str(item.get("buy_req", "")).strip(),
            "ka10029_rank": str(rank),
            "source": "ka10029",
            "updated_at_ms": str(int(_time.time() * 1000)),
        }
        if prev_buy_req:
            mapping["prev_buy_req"] = prev_buy_req

        try:
            pric = float(exp_cntr_pric.replace(",", "").replace("+", "").replace("-", ""))
            flu = float(exp_flu_rt.replace(",", "").replace("+", ""))
            if pric > 0 and flu != -100:
                mapping["pred_pre_pric"] = str(round(pric / (1 + flu / 100)))
        except Exception:
            pass

        flat_args: list[str] = []
        for field, value in mapping.items():
            if value == "":
                continue
            flat_args.extend([field, str(value)])
        if not flat_args:
            continue
        pipe.execute_command("HSET", key, *flat_args)
        pipe.expire(key, ttl)
        cached += 1

    if cached:
        await pipe.execute()
        logger.debug("[builder] ka10029 예상체결 캐시 백필 %d건", cached)


# ── S1 / S7: ka10029 예상체결등락률상위 ────────────────────────────────

def _rank_ka10029_items(items: list[dict]) -> list[dict]:
    ranked: list[dict] = []
    seen: set[str] = set()
    rank = 0

    for item in items:
        stk_cd = normalize_stock_code(item.get("stk_cd", ""))
        if not stk_cd or stk_cd in seen:
            continue
        rank += 1
        ranked.append(
            {
                "stk_cd": stk_cd,
                "rank": rank,
                "flu_rt": _clean(item.get("flu_rt", 0)),
                "exp_cntr_qty": _clean(item.get("exp_cntr_qty", 0)),
                "exp_cntr_pric": _clean(item.get("exp_cntr_pric", 0)),
                "base_pric": _clean(item.get("base_pric", 0)),
                "buy_req": _clean(item.get("buy_req", 0)),
                "sel_req": _clean(item.get("sel_req", 0)),
                "buy_bid": _clean(item.get("buy_bid", 0)),
                "sel_bid": _clean(item.get("sel_bid", 0)),
            }
        )
        seen.add(stk_cd)

    return ranked

async def _fetch_ka10029(token: str, market: str, trde_qty_cnd: str | None = None) -> list[dict]:
    """ka10029 예상체결등락률상위 (POST /api/dostk/rkinfo)"""
    if trde_qty_cnd is None:
        trde_qty_cnd = os.getenv("S1_KA10029_TRADE_QTY_CONDITION", "0").strip() or "0"
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10029",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers,
            {
                "mrkt_tp": market, "sort_tp": "1", "trde_qty_cnd": trde_qty_cnd,
                "stk_cnd": "16", "crd_cnd": "0", "pric_cnd": "8", "stex_tp": "3",
            },
            "ka10029",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10029", logger):
            break

        items = data.get("exp_cntr_flu_rt_upper", [])
        results.extend(items)

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break
    return results


async def _fetch_s1_ka10029_items(token: str, market: str) -> tuple[list[dict], str]:
    """Fetch S1 expected-execution candidates.

    Kiwoom's market-specific ka10029 result can be empty during the pre-open
    window even when the all-market request already has usable snapshots. In
    that case, use the all-market response so S1 pools and ws:expected hashes
    are available before the runner starts scanning.
    """
    items = await _fetch_ka10029(token, market)
    if items or market == "000":
        return items, market

    fallback_items = await _fetch_ka10029(token, "000")
    if fallback_items:
        logger.info(
            "[builder] S1 %s ka10029 empty; all-market fallback supplied %d items",
            market,
            len(fallback_items),
        )
        return fallback_items, "000"
    return items, market


async def _build_s1(token: str, market: str, rdb) -> None:
    """S1 갭상승 시초가: 3.0% ≤ flu_rt ≤ 15.0%, TTL 3600s, 100개
    장전 마지막 빌드(~08:22)가 스캐너 종료(09:10)까지 유효해야 하므로 TTL 1시간."""
    started_at = _time.monotonic()
    ttl = 3600
    items, source_market = await _fetch_s1_ka10029_items(token, market)
    await _cache_expected_from_ka10029(rdb, items)
    ranked_items = _rank_ka10029_items(items)
    raw_count = len(ranked_items)
    codes = []
    for item in ranked_items:
        stk_cd = normalize_stock_code(item.get("stk_cd", ""))
        if 3.0 <= item["flu_rt"] <= 15.0 and item["exp_cntr_pric"] > 0:
            codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S1:
            break
    codes = await _filter_individual_stocks(rdb, codes)
    codes = await _persist_candidate_quality_batch(
        rdb,
        strategy_id="s1",
        market=market,
        source_api="ka10029",
        raw_items=ranked_items,
        qualified_codes=codes,
        ttl=ttl,
    )
    meta = {
        "raw_count": raw_count,
        "filtered_count": len(codes),
        "rejected_count": raw_count - len(codes),
        "top_quality_count": len(codes),
        "built_at": now_kst_str(),
        "source_api": "ka10029",
        "source_market": source_market,
        "trade_qty_condition": os.getenv("S1_KA10029_TRADE_QTY_CONDITION", "0"),
        "source_status": "EMPTY" if not codes else ("FALLBACK_ALL_MARKET" if source_market == "000" and market != "000" else "OK"),
    }
    logger.info(
        "[builder] S1 build market=%s source_market=%s raw=%d filtered=%d rejected=%d status=%s elapsed=%.2fs",
        market,
        source_market,
        raw_count,
        len(codes),
        raw_count - len(codes),
        meta["source_status"],
        _time.monotonic() - started_at,
    )
    await _lpush_with_ttl(rdb, f"candidates:s1:{market}", codes, ttl, meta=meta)
    try:
        await rdb.hset(f"candidate:quality:meta:s1:{market}", mapping=meta)
        await rdb.expire(f"candidate:quality:meta:s1:{market}", ttl)
    except Exception as e:
        logger.debug("[builder] S1 meta 기록 실패: %s", e)


async def _build_s7(token: str, market: str, rdb) -> None:
    """S7 일목균형표 구름대 돌파 스윙: 0.5% ≤ flu_rt ≤ 10.0%, TTL 1800s, 100개"""
    ttl = 1800
    items = await _fetch_ka10027(token, market, sort_tp="1")
    raw_count = len(items)
    codes = []
    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.5 <= flu_rt <= 10.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S7:
            break

    existing = {normalize_stock_code(x.get("stk_cd", "")) for x in items}
    toss_items = await _toss_ranking_supplement(
        rdb, market, 0.5, 10.0, max(0, CANDIDATE_LIMIT_S7 - len(codes)),
    )
    toss_items = [t for t in toss_items if t["stk_cd"] not in existing]
    if toss_items:
        codes = list(dict.fromkeys(codes + [t["stk_cd"] for t in toss_items]))[:CANDIDATE_LIMIT_S7]

    codes = await _filter_individual_stocks(rdb, codes)
    meta = {
        "raw_count": raw_count,
        "filtered_count": len(codes),
        "rejected_count": raw_count - len(codes),
        "top_quality_count": len(codes),
        "built_at": now_kst_str(),
        "source_api": "ka10027",
        "source_status": "EMPTY" if not codes else "OK",
        "toss_supplement_count": len(toss_items),
    }
    await _lpush_with_ttl(rdb, f"candidates:s7:{market}", codes, ttl)
    try:
        await rdb.hset(f"candidate:quality:meta:s7:{market}", mapping=meta)
        await rdb.expire(f"candidate:quality:meta:s7:{market}", ttl)
    except Exception as e:
        logger.debug("[builder] S7 meta 기록 실패: %s", e)


# ── ka10023 거래량급증상위 공통 ────────────────────────────────────────

async def _fetch_ka10023(token: str, market: str) -> list[dict]:
    """ka10023 거래량급증상위 (POST /api/dostk/rkinfo)"""
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10023",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers,
            {
                "mrkt_tp": market, "sort_tp": "2", "tm_tp": "1",
                "trde_qty_tp": "10", "stk_cnd": "20", "pric_tp": "8", "stex_tp": "3",
            },
            "ka10023",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10023", logger):
            break

        items = data.get("trde_qty_sdnin", [])
        results.extend(items)

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break
    return results


# ── 토스 종목검색(Ranking) 보강 ─────────────────────────────────────────
# _build_s4/_build_s13가 market="001"/"101" 각각 호출하므로 같은 빌드 사이클
# 안에서 토스 랭킹을 두 번 조회하지 않도록 짧게(90초) 캐시한다.
_TOSS_RANKING_CACHE: dict = {"items": None, "expire_at": 0.0}


async def _get_toss_ranking_items(rdb) -> list[dict]:
    now = _time.monotonic()
    if _TOSS_RANKING_CACHE["items"] is not None and now < _TOSS_RANKING_CACHE["expire_at"]:
        return _TOSS_RANKING_CACHE["items"]
    items = await _toss_fetch_market_ranking(
        rdb, type_="MARKET_TRADING_AMOUNT", market_country="KR",
        duration="realtime", count=100, exclude_investment_caution=True,
    )
    _TOSS_RANKING_CACHE["items"] = items
    _TOSS_RANKING_CACHE["expire_at"] = now + 90.0
    return items


async def _toss_ranking_supplement(
    rdb, market: str, flu_lo: float, flu_hi: float, limit: int,
) -> list[dict]:
    """토스 거래대금 상위 랭킹에서 strategy의 flu_rt 밴드를 만족하는 종목을
    market("001"/"101")에 맞게 골라 Kiwoom raw_item과 같은 모양(dict)으로 반환한다.
    시장 구분을 확인할 수 없는 심볼은 다른 market 풀에 잘못 섞이지 않도록 건너뛴다.
    """
    if not TOSS_RANKING_SUPPLEMENT_ENABLED or not _toss_enabled() or limit <= 0:
        return []
    try:
        items = await _get_toss_ranking_items(rdb)
    except Exception as e:
        logger.debug("[builder] 토스 랭킹 조회 실패 (무시): %s", e)
        return []

    out: list[dict] = []
    for item in items:
        if len(out) >= limit:
            break
        symbol = normalize_stock_code(str(item.get("symbol", "")))
        if not symbol:
            continue
        price = item.get("price") or {}
        try:
            change_pct = float(price.get("changeRate")) * 100.0
        except (TypeError, ValueError):
            continue
        if not (flu_lo <= change_pct <= flu_hi):
            continue
        try:
            market_type = _normalize_market_type(
                await rdb.get(f"stock:market:{symbol}") or await rdb.get(f"stock:market_type:{symbol}")
            )
        except Exception:
            market_type = ""
        if market_type != market:
            continue  # 시장 미확인/불일치 — 다른 market 풀 오염 방지, 조용히 skip
        try:
            trde_amt_krw = float(item.get("tradingAmount") or 0)
        except (TypeError, ValueError):
            trde_amt_krw = 0.0
        out.append({
            "stk_cd": symbol,
            "flu_rt": change_pct,
            "trde_amt": trde_amt_krw / 1000.0,  # Kiwoom 관례: 천원 단위
            "trde_qty": _clean(item.get("tradingVolume", 0)),
            "source": "toss_ranking",
        })
    return out


# ── ka10027 전일대비등락률상위 공통 ─────────────────────────────────────

async def _fetch_ka10027(token: str, market: str, sort_tp: str = "1") -> list[dict]:
    """ka10027 전일대비등락률상위 (POST /api/dostk/rkinfo)"""
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10027",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers,
            {
                "mrkt_tp": market, "sort_tp": sort_tp, "trde_qty_cnd": "0010",
                "stk_cnd": "16", "crd_cnd": "0", "updown_incls": "0",
                "pric_cnd": "8", "trde_prica_cnd": "0", "stex_tp": "3",
            },
            "ka10027",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10027", logger):
            break

        items = data.get("pred_pre_flu_rt_upper", [])
        results.extend(items)

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break
    return results


async def _build_s4(token: str, market: str, rdb) -> None:
    """S4 장대양봉 + 거래량급증: ka10023, sdninRt≥50% & fluRt 3~20%, TTL 1200s, 100개
    ws:strength:{stk_cd} ≥ 120 종목 우선 정렬 (Java CandidateService.getS4Candidates와 동일 소스)"""
    ttl = 1200
    items = await _fetch_ka10023(token, market)
    raw_count = len(items)
    strong: list[str] = []
    normal: list[str] = []

    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        sdnin_rt = _clean(x.get("sdnin_rt", 0))
        flu_rt   = _clean(x.get("flu_rt", 0))
        if not (sdnin_rt >= 50.0 and 3.0 <= flu_rt <= 20.0):
            continue
        stk_cd = real_stk_cd
        if not stk_cd:
            continue

        # WS 체결강도 확인 — 30초 이내 신선한 데이터만 strong 분류
        try:
            strength_result = await get_strength_with_status(rdb, stk_cd, count=1)
            strength = strength_result.get("data")
            if strength is not None and float(strength) >= 115:
                strong.append(stk_cd)
                continue
        except Exception:
            pass
        normal.append(stk_cd)

        if len(strong) + len(normal) >= CANDIDATE_LIMIT_S4:
            break

    codes = (strong + normal)[:CANDIDATE_LIMIT_S4]

    existing = {normalize_stock_code(x.get("stk_cd", "")) for x in items}
    toss_items = await _toss_ranking_supplement(
        rdb, market, 3.0, 20.0, max(0, CANDIDATE_LIMIT_S4 - len(codes)),
    )
    toss_items = [t for t in toss_items if t["stk_cd"] not in existing]
    if toss_items:
        items = items + toss_items
        codes = list(dict.fromkeys(codes + [t["stk_cd"] for t in toss_items]))[:CANDIDATE_LIMIT_S4]

    # 토스 랭킹 항목은 종목명이 없어(symbol만 제공) _assess_candidate_quality의
    # 이름 기반 ETF/ETN 필터가 못 잡는다. stock:code_map 코드 기반 필터를 병합된
    # 최종 목록에 적용해 출처와 무관하게 ETF/ETN이 후보풀에 들어오지 않게 한다.
    codes = await _filter_individual_stocks(rdb, codes)

    codes = await _persist_candidate_quality_batch(
        rdb,
        strategy_id="s4",
        market=market,
        source_api="ka10023",
        raw_items=items,
        qualified_codes=codes,
        ttl=ttl,
    )
    meta = {
        "raw_count": raw_count,
        "filtered_count": len(codes),
        "rejected_count": raw_count - len(codes),
        "top_quality_count": len(strong),
        "built_at": now_kst_str(),
        "source_api": "ka10023",
        "source_status": "EMPTY" if not codes else "OK",
        "toss_supplement_count": len(toss_items),
    }
    await _lpush_with_ttl(rdb, f"candidates:s4:{market}", codes, ttl)
    try:
        await rdb.hset(f"candidate:quality:meta:s4:{market}", mapping=meta)
        await rdb.expire(f"candidate:quality:meta:s4:{market}", ttl)
    except Exception as e:
        logger.debug("[builder] S4 meta 기록 실패: %s", e)


async def _build_s8(token: str, market: str, rdb) -> None:
    """S8 golden-cross input: ka10027 rising-rate pool, 0.5% <= flu_rt <= 8.0%."""
    items = await _fetch_ka10027(token, market, sort_tp="1")
    codes = []
    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.5 <= flu_rt <= 8.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S8:
            break

    existing = {normalize_stock_code(x.get("stk_cd", "")) for x in items}
    toss_items = await _toss_ranking_supplement(
        rdb, market, 0.5, 8.0, max(0, CANDIDATE_LIMIT_S8 - len(codes)),
    )
    toss_items = [t for t in toss_items if t["stk_cd"] not in existing]
    if toss_items:
        codes = list(dict.fromkeys(codes + [t["stk_cd"] for t in toss_items]))[:CANDIDATE_LIMIT_S8]

    codes = await _filter_individual_stocks(rdb, codes)
    await _lpush_with_ttl(rdb, f"candidates:s8:{market}", codes, 1800)


async def _build_s9(token: str, market: str, rdb) -> None:
    """S9 pullback input uses the same source/filter as S8 but owns candidates:s9:*."""
    # S8 and S9 use the same source/filter, but each strategy writes its own Redis pool.
    items = await _fetch_ka10027(token, market, sort_tp="1")
    codes = []
    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.5 <= flu_rt <= 8.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S9:
            break

    existing = {normalize_stock_code(x.get("stk_cd", "")) for x in items}
    toss_items = await _toss_ranking_supplement(
        rdb, market, 0.5, 8.0, max(0, CANDIDATE_LIMIT_S9 - len(codes)),
    )
    toss_items = [t for t in toss_items if t["stk_cd"] not in existing]
    if toss_items:
        codes = list(dict.fromkeys(codes + [t["stk_cd"] for t in toss_items]))[:CANDIDATE_LIMIT_S9]

    codes = await _filter_individual_stocks(rdb, codes)
    await _lpush_with_ttl(rdb, f"candidates:s9:{market}", codes, 1800)


async def _build_s14(token: str, market: str, rdb) -> None:
    """S14 과매도 반등: sort_tp=3(하락률), 3.0% ≤ abs(flu_rt) ≤ 10.0%, TTL 1800s, 100개"""
    items = await _fetch_ka10027(token, market, sort_tp="3")
    codes = []
    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = abs(_clean(x.get("flu_rt", 0)))
        if 3.0 <= flu_rt <= 10.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S14:
            break

    # sort_tp=3(하락률)이라 flu_rt/changeRate 모두 음수 — 밴드도 음수로 맞춘다
    # (하락 3.0~10.0% == changeRate -10.0~-3.0%).
    existing = {normalize_stock_code(x.get("stk_cd", "")) for x in items}
    toss_items = await _toss_ranking_supplement(
        rdb, market, -10.0, -3.0, max(0, CANDIDATE_LIMIT_S14 - len(codes)),
    )
    toss_items = [t for t in toss_items if t["stk_cd"] not in existing]
    if toss_items:
        codes = list(dict.fromkeys(codes + [t["stk_cd"] for t in toss_items]))[:CANDIDATE_LIMIT_S14]

    codes = await _filter_individual_stocks(rdb, codes)
    await _lpush_with_ttl(rdb, f"candidates:s14:{market}", codes, 1800)


# ── S10: ka10016 신고저가요청 ──────────────────────────────────────────

async def _build_s10(token: str, market: str, rdb) -> None:
    """S10 52주 신고가: ka10016, 필터 없음, TTL 1200s, 100개"""
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10016",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo", headers,
            {
                "mrkt_tp": market, "ntl_tp": "1", "high_low_close_tp": "1",
                "stk_cnd": "1", "trde_qty_tp": "00010", "crd_cnd": "0",
                "updown_incls": "0", "dt": "250", "stex_tp": "3",
            },
            "ka10016",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10016", logger):
            break

        items = data.get("ntl_pric", [])
        results.extend(items)

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break
        if len(results) >= CANDIDATE_LIMIT_S10:
            break

    # ka10016's stk_cnd has no ETF/ETN exclusion value in the official contract.
    # Remove explicit ETF/ETN names here, then use stock:code_map as a fallback
    # for records whose response name was absent or incomplete.
    codes = [
        normalize_stock_code(x.get("stk_cd"))
        for x in results
        if x.get("stk_cd") and not _is_etf_or_etn_name(x.get("stk_nm"))
    ][:CANDIDATE_LIMIT_S10]
    codes = await _filter_individual_stocks(rdb, codes)
    codes = await _persist_candidate_quality_batch(
        rdb,
        strategy_id="s10",
        market=market,
        source_api="ka10016",
        raw_items=results,
        qualified_codes=codes,
        ttl=1800,
    )

    # Redis에 저장할 때 이제 "005930_AL"이 아닌 "005930" 형태로 들어갑니다.
    await _lpush_with_ttl(rdb, f"candidates:s10:{market}", codes, 1800)


# ── S11: ka10035 외인연속순매매상위 ────────────────────────────────────

async def _build_s11(token: str, market: str, rdb) -> None:
    """S11 외인 연속 순매수: dm1>0, dm2>0, dm3>0, tot>0, TTL 1800s, 80개"""
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10035",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers,
            {"mrkt_tp": market, "trde_tp": "2", "base_dt_tp": "1", "stex_tp": "3"},
            "ka10035",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10035", logger):
            break

        items = data.get("for_cont_nettrde_upper", [])
        results.extend(items)

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break

    codes = []
    for x in results:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        stk_cd = real_stk_cd
        if not stk_cd:
            continue
        try:
            dm1 = _clean(x.get("dm1", 0))
            dm2 = _clean(x.get("dm2", 0))
            dm3 = _clean(x.get("dm3", 0))
            tot = _clean(x.get("tot", 0))
        except Exception:
            continue
        if dm1 > 0 and dm2 > 0 and dm3 > 0 and tot > 0:
            codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S11:
            break
    codes = await _filter_individual_stocks(rdb, codes)
    await _lpush_with_ttl(rdb, f"candidates:s11:{market}", codes, 2400)


# ── S12: ka10032 거래대금상위 ──────────────────────────────────────────

async def _build_s12(token: str, market: str, rdb) -> None:
    """S12 종가강도: flu_rt > 0, TTL 600s, 50개"""
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10032",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers,
            {"mrkt_tp": market, "mang_stk_incls": "0", "stex_tp": "3"},
            "ka10032",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10032", logger):
            break

        items = data.get("trde_prica_upper", [])
        results.extend(items)

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break

    codes = []
    for x in results:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = _clean(x.get("flu_rt", 0))
        if flu_rt > 0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S12:
            break
    codes = await _filter_individual_stocks(rdb, codes)
    await _lpush_with_ttl(rdb, f"candidates:s12:{market}", codes, 1200)


# ── S2: ka10054 변동성완화장치발동종목 ───────────────────────────────────

async def _build_s2(token: str, market: str, rdb) -> None:
    """S2 VI 발동 종목: ka10054 상승방향 동적VI, TTL 300s, 50개"""
    resp = await kiwoom_post(
        f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
        {
            "api-id": "ka10054",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        },
        {
            "mrkt_tp": market, "bf_mkrt_tp": "1", "stk_cd": "",
            # ka10054 skip_stk position 8/9: ETF / ETN exclusion.
            "motn_tp": "0", "skip_stk": "000000011",
            "trde_qty_tp": "0", "min_trde_qty": "0", "max_trde_qty": "0",
            "trde_prica_tp": "0", "min_trde_prica": "0", "max_trde_prica": "0",
            "motn_drc": "1", "stex_tp": "3",
        },
        "ka10054",
    )
    if resp is None:
        return
    data = resp.json()
    if not validate_kiwoom_response(data, "ka10054", logger):
        return

    codes = []
    for x in data.get("motn_stk", []):
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        stk_cd = real_stk_cd
        if not stk_cd:
            continue
        try:
            open_flu = _clean(x.get("open_pric_pre_flu_rt", "0"))
        except Exception:
            open_flu = 0.0
        if open_flu > 0:
            codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S2:
            break
    codes = await _filter_individual_stocks(rdb, codes)
    await _lpush_with_ttl(rdb, f"candidates:s2:{market}", codes, 1200)


# ── S3: ka10065 장중투자자별매매상위 (외인 ∩ 기관계) ────────────────────

async def _fetch_ka10065_set(token: str, market: str, orgn_tp: str) -> set:
    """ka10065 장중투자자별매매상위 – 지정 투자자 순매수 종목코드 세트 반환"""
    codes: set = set()
    resp = await kiwoom_post(
        f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
        {
            "api-id": "ka10065",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        },
        {"trde_tp": "1", "mrkt_tp": market, "orgn_tp": orgn_tp},
        "ka10065",
    )
    if resp is None:
        return codes
    data = resp.json()
    if not validate_kiwoom_response(data, "ka10065", logger):
        return codes
    for x in data.get("opmr_invsr_trde_upper", []):
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        stk_cd = real_stk_cd
        if stk_cd:
            codes.add(stk_cd)
    return codes


async def _build_s3(token: str, market: str, rdb) -> None:
    """S3 외인+기관 동시순매수: ka10065 교집합, TTL 600s, 100개"""
    started_at = _time.monotonic()
    strategy = "S3"
    ttl = 1200
    try:
        frgn_set, inst_set = await asyncio.gather(
            _fetch_ka10065_set(token, market, "9000"),
            _fetch_ka10065_set(token, market, "9999"),
        )
        codes = await _filter_individual_stocks(rdb, list(frgn_set & inst_set))
        codes = codes[:CANDIDATE_LIMIT_S3]
        await _lpush_with_ttl(rdb, f"candidates:s3:{market}", codes, ttl)
        elapsed_ms = int((_time.monotonic() - started_at) * 1000)
        state = "empty" if not codes else "ok"
        await _write_candidates_meta(
            rdb,
            strategy=strategy,
            market=market,
            codes=codes,
            ttl=ttl,
            source="ka10065",
            elapsed_ms=elapsed_ms,
            state=state,
        )
        await _record_s3s5_status(
            rdb,
            strategy=strategy,
            market=market,
            count=len(codes),
            elapsed_ms=elapsed_ms,
            state=state,
            source="ka10065",
        )
        await _incr_pipeline_daily(rdb, strategy, "candidate_build_empty" if not codes else "candidate_build_ok")
    except Exception:
        elapsed_ms = int((_time.monotonic() - started_at) * 1000)
        await _record_s3s5_status(
            rdb,
            strategy=strategy,
            market=market,
            count=0,
            elapsed_ms=elapsed_ms,
            state="error",
            source="ka10065",
        )
        await _incr_pipeline_daily(rdb, strategy, "candidate_build_error")
        raise


# ── S5: ka90003 프로그램순매수상위 ──────────────────────────────────────

_PROG_MRKT_MAP = {"001": "P00101", "101": "P10102"}


async def _build_s5(token: str, market: str, rdb) -> None:
    """S5 프로그램순매수: ka90003, TTL 600s, 100개"""
    started_at = _time.monotonic()
    strategy = "S5"
    ttl = 1200
    kiwoom_mkt = _PROG_MRKT_MAP.get(market, "P00101")
    try:
        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            {
                "api-id": "ka90003",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            {"trde_upper_tp": "2", "amt_qty_tp": "1", "mrkt_tp": kiwoom_mkt, "stex_tp": "3"},
            "ka90003",
        )
        codes = []
        state = "empty"
        if resp is not None:
            data = resp.json()
            if validate_kiwoom_response(data, "ka90003", logger):
                for x in data.get("prm_netprps_upper_50", []):
                    real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
                    stk_cd = real_stk_cd
                    try:
                        net = _clean(x.get("prm_netprps_amt", "0"))
                    except Exception:
                        net = 0.0
                    if stk_cd and net > 0:
                        codes.append(stk_cd)
                    if len(codes) >= CANDIDATE_LIMIT_S5:
                        break
                codes = await _filter_individual_stocks(rdb, codes)
                await _lpush_with_ttl(rdb, f"candidates:s5:{market}", codes, ttl)
                state = "empty" if not codes else "ok"
        elapsed_ms = int((_time.monotonic() - started_at) * 1000)
        await _write_candidates_meta(
            rdb,
            strategy=strategy,
            market=market,
            codes=codes,
            ttl=ttl,
            source="ka90003",
            elapsed_ms=elapsed_ms,
            state=state,
        )
        await _record_s3s5_status(
            rdb,
            strategy=strategy,
            market=market,
            count=len(codes),
            elapsed_ms=elapsed_ms,
            state=state,
            source="ka90003",
        )
        await _incr_pipeline_daily(rdb, strategy, "candidate_build_empty" if not codes else "candidate_build_ok")
    except Exception:
        elapsed_ms = int((_time.monotonic() - started_at) * 1000)
        await _record_s3s5_status(
            rdb,
            strategy=strategy,
            market=market,
            count=0,
            elapsed_ms=elapsed_ms,
            state="error",
            source="ka90003",
        )
        await _incr_pipeline_daily(rdb, strategy, "candidate_build_error")
        raise


# ── S6: ka90001→ka90002 테마 구성종목 ────────────────────────────────────

async def _build_s6(token: str, rdb) -> None:
    """S6 테마 구성종목: ka90001 상위 5테마→ka90002, TTL 300s, 150개"""
    # 1단계: 상위 5개 테마 코드 추출
    theme_codes: list[str] = []
    resp = await kiwoom_post(
        f"{KIWOOM_BASE_URL}/api/dostk/thme",
        {
            "api-id": "ka90001",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        },
        {"qry_tp": "1", "date_tp": "1", "flu_pl_amt_tp": "3", "stex_tp": "3"},
        "ka90001",
    )
    if resp is None:
        return
    data = resp.json()
    if validate_kiwoom_response(data, "ka90001", logger):
        for grp in data.get("thema_grp", [])[:5]:
            tc = grp.get("thema_grp_cd", "")
            if tc:
                theme_codes.append(tc)

    if not theme_codes:
        logger.debug("[builder] S6 테마 없음 – 풀 적재 생략")
        return

    # 2단계: 각 테마 구성종목 수집
    all_codes: list[str] = []
    seen: set[str] = set()
    for tc in theme_codes:
        await asyncio.sleep(_API_INTERVAL)
        resp2 = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/thme",
            {
                "api-id": "ka90002",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            {"date_tp": "1", "thema_grp_cd": tc, "stex_tp": "3"},
            "ka90002",
        )
        if resp2 is None:
            continue
        data2 = resp2.json()
        if not validate_kiwoom_response(data2, "ka90002", logger):
            continue
        for x in data2.get("thema_comp_stk", []):
            real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
            stk_cd = real_stk_cd
            if not stk_cd or stk_cd in seen:
                continue
            # flu_rt 기준 사전 제외 없음 — strategy_6_theme.py에서 모드별 분류
            all_codes.append(stk_cd)
            seen.add(stk_cd)
        if len(all_codes) >= CANDIDATE_LIMIT_S6:
            break

    codes = await _filter_individual_stocks(rdb, all_codes[:CANDIDATE_LIMIT_S6])
    # S6는 테마 기반으로 시장 구분 없이 동일 풀 적재
    for market in MARKETS:
        await _lpush_with_ttl(rdb, f"candidates:s6:{market}", codes, 1200)


# ── S13: ka10023 거래량급증 독립 풀 ────────────────────────────────────

async def _build_s13(token: str, market: str, rdb) -> None:
    """S13 박스권 돌파: ka10023, sdninRt≥30% & fluRt 3~8%, TTL 1200s, 100개
    Java CandidateService.getS13Candidates와 동일 소스·필터 (M-2 fix 정렬)"""
    ttl = 1200
    items = await _fetch_ka10023(token, market)
    codes: list[str] = []
    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        sdnin_rt = _clean(x.get("sdnin_rt", 0))
        flu_rt   = _clean(x.get("flu_rt", 0))
        if sdnin_rt >= 30.0 and 3.0 <= flu_rt <= 8.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S13:
            break

    existing = {normalize_stock_code(x.get("stk_cd", "")) for x in items}
    toss_items = await _toss_ranking_supplement(
        rdb, market, 3.0, 8.0, max(0, CANDIDATE_LIMIT_S13 - len(codes)),
    )
    toss_items = [t for t in toss_items if t["stk_cd"] not in existing]
    if toss_items:
        items = items + toss_items
        codes = list(dict.fromkeys(codes + [t["stk_cd"] for t in toss_items]))[:CANDIDATE_LIMIT_S13]

    codes = await _filter_individual_stocks(rdb, codes)

    codes = await _persist_candidate_quality_batch(
        rdb,
        strategy_id="s13",
        market=market,
        source_api="ka10023",
        raw_items=items,
        qualified_codes=codes,
        ttl=ttl,
    )
    await _lpush_with_ttl(rdb, f"candidates:s13:{market}", codes, ttl)


# ── S15: ka10032 거래대금상위 독립 풀 ──────────────────────────────────

async def _build_s15(token: str, market: str, rdb) -> None:
    """S15 모멘텀 정렬: ka10032, fluRt 0.5~8%, TTL 900s, 80개
    Java CandidateService.getS15Candidates와 동일 소스·필터 (M-2 fix 정렬)"""
    results = []
    next_key = ""
    while True:
        headers = {
            "api-id": "ka10032",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if next_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo", headers,
            {"mrkt_tp": market, "mang_stk_incls": "0", "stex_tp": "3"},
            "ka10032",
        )
        if resp is None:
            break
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10032", logger):
            break

        results.extend(data.get("trde_prica_upper", []))

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "").strip()
        if cont_yn != "Y" or not next_key:
            break

    codes: list[str] = []
    for x in results:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.5 <= flu_rt <= 8.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= CANDIDATE_LIMIT_S15:
            break
    codes = await _filter_individual_stocks(rdb, codes)
    # RSI 필터: stock:rsi14:{stk_cd} 캐시가 있으면 RSI > 72 종목 제거 (fail-open)
    if rdb:
        rsi_ok = []
        for code in codes:
            try:
                rsi_val = await rdb.get(f"stock:rsi14:{code}")
                if rsi_val is not None and float(rsi_val) > 72.0:
                    logger.debug("[S15] RSI 필터 제외 %s rsi=%.1f", code, float(rsi_val))
                    continue
            except Exception:
                pass  # fail-open: RSI 데이터 없으면 포함
            rsi_ok.append(code)
        codes = rsi_ok
    await _lpush_with_ttl(rdb, f"candidates:s15:{market}", codes, 1200)


# ── watchlist ZSET 우선순위 계산 ───────────────────────────────────────

def _calculate_watchlist_priority_score(
    stk_cd: str,
    strategy_ids: list[str],
    quality_data: dict | None = None,
    enrichment_data: dict | None = None,
) -> float:
    """종목의 watchlist 우선순위 점수를 계산한다.

    점수 구성 (최대 ~100점):
    - 전략 중요도: 전략 중 가장 높은 가중치 (0~30)
    - candidate quality: A=25, B=18, C=10, REJECT=-30(패널티 포함)
    - 최신성: built_at 기준 0~15 (10분 이내=15, 30분=10, 60분=5, 이상=0)
    - 유동성/거래대금: 0~15 (liquidity_score 0~100 → 0~15 변환)
    - 다중 전략 출현: 전략 수 × 5, 최대 10
    - 실시간 필수도: s1/s2/s4/s13=5, 나머지=0
    - REJECT 패널티: candidate_quality=REJECT이면 -30
    """
    # 전략 중요도
    strategy_weight = max(
        (_STRATEGY_PRIORITY_WEIGHT.get(sid.lower(), 15) for sid in strategy_ids),
        default=15,
    )

    # quality 점수
    if quality_data:
        quality_data = _decode_redis_hash(quality_data)
        cq = str(quality_data.get("candidate_quality", "C"))
        ls = _as_float(quality_data.get("liquidity_score", 50), 50.0)
    else:
        cq = "C"
        ls = 50.0

    quality_bonus_map = {"A": 25, "B": 18, "C": 10, "REJECT": 0}
    quality_bonus = quality_bonus_map.get(cq, 10)

    # 최신성 점수 (built_at이 없으면 중간값 5)
    recency_score = 5
    if quality_data:
        built_at_str = quality_data.get("built_at", "")
        if built_at_str:
            try:
                # now_kst_str() 포맷: "2026-05-06T09:00:00+09:00"
                built_dt = datetime.fromisoformat(built_at_str)
                now_dt = datetime.now(KST)
                age_min = (now_dt - built_dt).total_seconds() / 60
                if age_min <= 10:
                    recency_score = 15
                elif age_min <= 30:
                    recency_score = 10
                elif age_min <= 60:
                    recency_score = 5
                else:
                    recency_score = 0
            except Exception:
                recency_score = 5

    # 유동성 점수 (0~100 → 0~15)
    liquidity_bonus = int(ls * 15 / 100)

    # 다중 전략 출현 가점
    confluence_bonus = min(len(strategy_ids) * 5, 10)

    # 실시간 필수도
    realtime_bonus = 5 if any(sid.lower() in _REALTIME_CRITICAL_STRATEGIES for sid in strategy_ids) else 0

    # REJECT 패널티
    reject_penalty = -30 if cq == "REJECT" else 0
    enrichment_score = _as_float((enrichment_data or {}).get("score", 0), 0.0)
    enrichment_bonus = min(30.0, max(0.0, enrichment_score * 0.30))

    score = (
        strategy_weight
        + quality_bonus
        + recency_score
        + liquidity_bonus
        + confluence_bonus
        + realtime_bonus
        + reject_penalty
        + enrichment_bonus
    )
    return float(max(0.0, score))


# ── watchlist 통합 갱신 ─────────────────────────────────────────────────

async def _refresh_watchlist(rdb, ttl: int = 900) -> None:
    """모든 전략 후보 풀 → candidates:watchlist SET 통합.
    websocket-listener _watchlist_poller 가 이 SET 을 5초마다 읽어 동적 구독.

    ENABLE_WATCHLIST_ZSET=true(기본)이면 candidates:watchlist:z ZSET 도 추가로 갱신.
    기존 SET(candidates:watchlist, candidates:watchlist:priority)은 하위 호환을 위해 유지.
    """
    all_codes: set[str] = set()
    priority_codes: set[str] = set()
    # 전략별 코드 맵: stk_cd → 해당 종목이 출현한 전략 ID 리스트
    code_strategy_map: dict[str, list[str]] = {}

    # range 상한은 최대 전략 번호 + 1이어야 한다. 2026-08-10까지 range(1, 16)으로
    # 굳어 있어 s16 후보 풀이 watchlist/ZSET에 한 번도 반영되지 않았고, 그 결과
    # S16 종목은 websocket-listener의 동적 구독 대상에서 통째로 빠져 있었다.
    # (같은 날 발견된 trading_signals_strategy_check의 S16 누락과 동일 계열 버그.)
    for n in range(1, _MAX_STRATEGY_NUM + 1):
        sid = f"s{n}"
        for mkt in MARKETS:
            try:
                codes = await rdb.lrange(f"candidates:{sid}:{mkt}", 0, -1)
                for c in codes:
                    if c:
                        all_codes.add(c)
                        code_strategy_map.setdefault(c, [])
                        if sid not in code_strategy_map[c]:
                            code_strategy_map[c].append(sid)
                if n in (1, 7):
                    priority_codes.update(c for c in codes if c)
            except Exception:
                pass

    if not all_codes:
        logger.debug("[builder] watchlist 갱신 건너뜀 (후보 없음)")
        return

    pipe = rdb.pipeline()
    # 기존 SET 유지 (하위 호환)
    pipe.delete("candidates:watchlist")
    pipe.sadd("candidates:watchlist", *all_codes)
    pipe.expire("candidates:watchlist", ttl)
    pipe.delete("candidates:watchlist:priority")
    if priority_codes:
        pipe.sadd("candidates:watchlist:priority", *priority_codes)
        pipe.expire("candidates:watchlist:priority", ttl)
    await pipe.execute()

    # ZSET 갱신 (ENABLE_WATCHLIST_ZSET=true 일 때)
    if ENABLE_WATCHLIST_ZSET and all_codes:
        try:
            zset_key = "candidates:watchlist:z"
            zset_ttl = 3600

            # 종목별 품질 데이터 로드 (candidate:quality:{stk_cd} hash)
            quality_cache: dict[str, dict] = {}
            enrichment_cache: dict[str, dict] = {}
            for stk_cd in all_codes:
                try:
                    qdata = _decode_redis_hash(await rdb.hgetall(f"candidate:quality:{stk_cd}"))
                    if qdata:
                        quality_cache[stk_cd] = qdata
                except Exception:
                    pass
                try:
                    enrichment = _decode_redis_hash(await rdb.hgetall(f"candidate:enrichment:{stk_cd}"))
                    if enrichment:
                        enrichment_cache[stk_cd] = enrichment
                except Exception:
                    pass

            # 점수 계산 및 ZADD
            zset_pipe = rdb.pipeline()
            zset_pipe.delete(zset_key)
            scored_items: list[tuple[float, str]] = []
            for stk_cd in all_codes:
                strategy_ids = code_strategy_map.get(stk_cd, [])
                quality_data = quality_cache.get(stk_cd)
                score = _calculate_watchlist_priority_score(
                    stk_cd,
                    strategy_ids,
                    quality_data,
                    enrichment_cache.get(stk_cd),
                )
                scored_items.append((score, stk_cd))

            # redis-py zadd: {member: score} mapping
            if scored_items:
                zadd_mapping = {stk_cd: score for score, stk_cd in scored_items}
                zset_pipe.zadd(zset_key, zadd_mapping)
                zset_pipe.expire(zset_key, zset_ttl)

            # zset top-ranked symbols are also backfilled into candidates:watchlist:priority.
            top_priority = sorted(scored_items, key=lambda x: x[0], reverse=True)[:CANDIDATE_WATCHLIST_PRIORITY_LIMIT]
            top_priority_codes = [stk_cd for _, stk_cd in top_priority]
            if top_priority_codes:
                zset_pipe.delete("candidates:watchlist:priority")
                zset_pipe.sadd("candidates:watchlist:priority", *top_priority_codes)
                zset_pipe.expire("candidates:watchlist:priority", ttl)

            await zset_pipe.execute()
            logger.info(
                "[builder] candidates:watchlist:z updated %d items (top%d priority cached)",
                len(scored_items),
                CANDIDATE_WATCHLIST_PRIORITY_LIMIT,
            )
        except Exception as zset_err:
            logger.warning("[builder] watchlist ZSET 갱신 실패: %s", zset_err)

    logger.info(
        "[builder] candidates:watchlist 갱신 – %d종목 (priority=%d)",
        len(all_codes),
        len(priority_codes),
    )


# ── 배치 빌드 함수 ─────────────────────────────────────────────────────

async def _build_pre_market(token: str, rdb) -> None:
    """장전 배치: S1 (ka10029), S2 (ka10054)"""
    for market in MARKETS:
        try:
            await _build_s1(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s2(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
        except Exception as e:
            logger.error("[builder] 장전 %s 빌드 오류: %s", market, e)
    await _refresh_watchlist(rdb)


async def _build_opening_recovery(token: str, rdb) -> None:
    """Keep S1 fresh during 08:25-09:05 when ka10029 often becomes valid late."""
    for market in MARKETS:
        try:
            existing = await rdb.llen(f"candidates:s1:{market}")
        except Exception:
            existing = 0
        if existing:
            continue
        try:
            logger.info("[builder] S1 %s opening recovery rebuild start", market)
            await _build_s1(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
        except Exception as e:
            logger.error("[builder] S1 %s opening recovery failed: %s", market, e)
    await _refresh_watchlist(rdb)


async def _build_intraday(token: str, rdb, session: str | None = None) -> None:
    """Build intraday candidate pools.

    When session-based ordering is enabled, the S12-only session refreshes only
    candidates:s12:* and leaves existing S2 and other pools as auxiliary inputs.
    """
    s12_only = session == SESSION_S12_ONLY

    for market in MARKETS:
        builders = [(_build_s12, f"S12 {market}")] if s12_only else [
            (_build_s2,  f"S2 {market}"),
            (_build_s3,  f"S3 {market}"),
            (_build_s4,  f"S4 {market}"),
            (_build_s5,  f"S5 {market}"),
            (_build_s7,  f"S7 {market}"),
            (_build_s8,  f"S8 {market}"),
            (_build_s9,  f"S9 {market}"),
            (_build_s10, f"S10 {market}"),
            (_build_s11, f"S11 {market}"),
            (_build_s12, f"S12 {market}"),
            (_build_s13, f"S13 {market}"),
            (_build_s14, f"S14 {market}"),
            (_build_s15, f"S15 {market}"),
        ]
        for fn, name in builders:
            try:
                await fn(token, market, rdb)
            except Exception as e:
                logger.error("[builder] intraday %s build failed: %s", name, e)
            await asyncio.sleep(_API_INTERVAL)

    if not s12_only:
        try:
            await _build_s6(token, rdb)
        except Exception as e:
            logger.error("[builder] S6 build failed: %s", e)
        for market in MARKETS:
            try:
                await _build_live_confluence(token, market, rdb)
            except Exception as e:
                logger.error("[builder] live confluence build failed [%s]: %s", market, e)
    await _refresh_watchlist(rdb)


# ── 메인 루프 ──────────────────────────────────────────────────────────

async def run_candidate_builder(rdb) -> None:
    """candidates_builder 메인 루프 – engine.py 에서 asyncio.create_task() 로 기동"""
    if CANDIDATE_POOL_OWNER != "PYTHON":
        logger.warning(
            "[builder] candidate pool owner is %s; Python builder will not write pools",
            CANDIDATE_POOL_OWNER,
        )
        return
    try:
        await rdb.set("ops:candidate_pool_owner", "PYTHON")
    except Exception as exc:
        logger.warning("[builder] candidate owner marker write failed: %s", exc)
    logger.info("[builder] candidates_builder 시작 (주기=%ds)", CANDIDATE_BUILD_INTERVAL_SEC)

    while True:
        now_dt = datetime.now(KST)
        now = now_dt.time()
        try:
            token = await rdb.get("kiwoom:token")
        except Exception as e:
            logger.warning("[builder] Redis token 조회 실패: %s", e)
            token = None

        if not token:
            logger.debug("[builder] kiwoom:token 없음 — 30초 대기")
            await asyncio.sleep(30)
            continue

        if ENABLE_SESSION_CANDIDATE_BUILDER:
            session = _candidate_builder_session(now_dt)
            if session == SESSION_PRE_MARKET:
                logger.info("[builder] pre-market candidate build start")
                await _build_pre_market(token, rdb)
                await asyncio.sleep(180)
            elif session == SESSION_OPENING_RECOVERY:
                logger.info("[builder] opening recovery candidate build start")
                await _build_opening_recovery(token, rdb)
                await asyncio.sleep(60)
            elif session == SESSION_INTRADAY:
                logger.info("[builder] intraday candidate build start")
                await _build_intraday(token, rdb, session=session)
                await asyncio.sleep(CANDIDATE_BUILD_INTERVAL_SEC)
            elif session == SESSION_S12_ONLY:
                logger.info("[builder] S12-only candidate build start")
                await _build_intraday(token, rdb, session=session)
                await asyncio.sleep(CANDIDATE_BUILD_INTERVAL_SEC)
            else:
                await asyncio.sleep(300)
            continue

        if time(7, 25) <= now <= time(9, 10):
            if now <= time(8, 25):
                logger.info("[builder] pre-market candidate build start")
                await _build_pre_market(token, rdb)
                await asyncio.sleep(180)
            else:
                await _build_opening_recovery(token, rdb)
                await asyncio.sleep(60)

        elif time(9, 5) <= now <= time(14, 55):
            # 장중: 전체 전략 갱신
            logger.info("[builder] 장중 빌드 시작")
            await _build_intraday(token, rdb)
            await asyncio.sleep(CANDIDATE_BUILD_INTERVAL_SEC)

        else:
            # 장외: 대기
            await asyncio.sleep(300)
