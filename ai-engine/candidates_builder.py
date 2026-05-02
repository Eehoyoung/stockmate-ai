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
from utils import safe_float as _clean, normalize_stock_code
from config import KIWOOM_BASE_URL, MARKET_LIST as MARKETS

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

CANDIDATE_BUILD_INTERVAL_SEC = int(os.getenv("CANDIDATE_BUILD_INTERVAL_SEC", "600"))
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
S3S5_STATUS_TTL_SEC = int(os.getenv("S3S5_STATUS_TTL_SEC", "1800"))


def _env_flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


ENABLE_S3S5_LATENCY_STATUS = _env_flag("ENABLE_S3S5_LATENCY_STATUS")
ENABLE_CANDIDATES_META = _env_flag("ENABLE_CANDIDATES_META")
ENABLE_SESSION_CANDIDATE_BUILDER = _env_flag("ENABLE_SESSION_CANDIDATE_BUILDER")

SESSION_PRE_MARKET = "pre_market"
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
    if time(9, 5) <= now < time(14, 50):
        return SESSION_INTRADAY
    if time(14, 50) <= now <= time(14, 55):
        return SESSION_S12_ONLY
    return SESSION_IDLE


def _normalize_candidate_builder_session(session) -> str:
    value = getattr(session, "value", session)
    value = str(value or "").strip().lower()
    if value in {SESSION_PRE_MARKET, "pre", "premarket", "before_open"}:
        return SESSION_PRE_MARKET
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

async def _lpush_with_ttl(rdb, key: str, codes: list[str], ttl: int) -> None:
    """기존 키를 삭제하고 새 목록을 RPUSH 한 뒤 EXPIRE 설정"""
    codes = [code for code in dict.fromkeys(normalize_stock_code(code) for code in codes) if code]
    if not codes:
        logger.debug("[builder] %s 빈 결과 – 기존 키 유지 (TTL 만료 대기)", key)
        return
    pipe = rdb.pipeline()
    pipe.delete(key)
    pipe.rpush(key, *codes)
    pipe.expire(key, ttl)
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
        }

        try:
            pric = float(exp_cntr_pric.replace(",", "").replace("+", "").replace("-", ""))
            flu = float(exp_flu_rt.replace(",", "").replace("+", ""))
            if pric > 0 and flu != -100:
                mapping["pred_pre_pric"] = str(round(pric / (1 + flu / 100)))
        except Exception:
            pass

        key = f"ws:expected:{stk_cd}"
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

async def _fetch_ka10029(token: str, market: str) -> list[dict]:
    """ka10029 예상체결등락률상위 (POST /api/dostk/rkinfo)"""
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
                "mrkt_tp": market, "sort_tp": "1", "trde_qty_cnd": "10",
                "stk_cnd": "1", "crd_cnd": "0", "pric_cnd": "8", "stex_tp": "3",
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


async def _build_s1(token: str, market: str, rdb) -> None:
    """S1 갭상승 시초가: 3.0% ≤ flu_rt ≤ 15.0%, TTL 3600s, 100개
    장전 마지막 빌드(~08:22)가 스캐너 종료(09:10)까지 유효해야 하므로 TTL 1시간."""
    items = await _fetch_ka10029(token, market)
    await _cache_expected_from_ka10029(rdb, items)
    ranked_items = _rank_ka10029_items(items)
    codes = []
    for item in ranked_items:
        stk_cd = normalize_stock_code(item.get("stk_cd", ""))
        if 3.0 <= item["flu_rt"] <= 15.0 and item["exp_cntr_pric"] > 0:
            codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s1:{market}", codes, 3600)


async def _build_s7(token: str, market: str, rdb) -> None:
    """S7 일목균형표 구름대 돌파 스윙: 0.5% ≤ flu_rt ≤ 10.0%, TTL 1800s, 100개"""
    items = await _fetch_ka10027(token, market, sort_tp="1")
    codes = []
    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.5 <= flu_rt <= 10.0:
            stk_cd = real_stk_cd
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s7:{market}", codes, 1800)


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
                "trde_qty_tp": "10", "stk_cnd": "1", "pric_tp": "8", "stex_tp": "3",
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
                "stk_cnd": "1", "crd_cnd": "0", "updown_incls": "0",
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
    items = await _fetch_ka10023(token, market)
    strong: list[str] = []
    normal: list[str] = []

    for x in items:
        real_stk_cd = normalize_stock_code(x.get("stk_cd", ""))
        sdnin_rt = _clean(x.get("sdnin_rt", 0))
        flu_rt   = _clean(x.get("flu_rt", 0))
        if not (sdnin_rt >= 50.0 and 3.0 <= flu_rt <= 20.0):
            continue
        stk_cd =real_stk_cd
        if not stk_cd:
            continue

        # WS 체결강도 확인 (ws:strength는 LPUSH LIST → lindex 0으로 최신값 조회)
        try:
            raw_str = await rdb.lindex(f"ws:strength:{stk_cd}", 0)
            if raw_str is not None and float(raw_str) >= 120:
                strong.append(stk_cd)
                continue
        except Exception:
            pass
        normal.append(stk_cd)

        if len(strong) + len(normal) >= 100:
            break

    codes = (strong + normal)[:100]
    await _lpush_with_ttl(rdb, f"candidates:s4:{market}", codes, 1200)


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
        if len(codes) >= 150:
            break
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
        if len(codes) >= 150:
            break
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
        if len(codes) >= 100:
            break
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
        if len(results) >= 100:
            break

    # [핵심 수정] 리스트 컴프리헨션 내부에서 정규화 함수 호출
    # 결과가 100개가 넘지 않도록 슬라이싱하고, 정제된 6자리 코드만 codes에 담깁니다.
    codes = [normalize_stock_code(x.get("stk_cd")) for x in results if x.get("stk_cd")][:100]

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
        if len(codes) >= 80:
            break
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
        if len(codes) >= 50:
            break
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
            "motn_tp": "0", "skip_stk": "000000000",
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
        if len(codes) >= 50:
            break
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
        codes = list(frgn_set & inst_set)[:100]
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
                    if len(codes) >= 100:
                        break
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
            try:
                flu_rt = _clean(x.get("flu_rt", "0"))
            except Exception:
                flu_rt = 0.0
            # 선도주 제외: 5% 이상 이미 상승한 종목
            if flu_rt < 5.0:
                all_codes.append(stk_cd)
                seen.add(stk_cd)
        if len(all_codes) >= 150:
            break

    codes = all_codes[:150]
    # S6는 테마 기반으로 시장 구분 없이 동일 풀 적재
    for market in MARKETS:
        await _lpush_with_ttl(rdb, f"candidates:s6:{market}", codes, 1200)


# ── S13: ka10023 거래량급증 독립 풀 ────────────────────────────────────

async def _build_s13(token: str, market: str, rdb) -> None:
    """S13 박스권 돌파: ka10023, sdninRt≥30% & fluRt 3~8%, TTL 1200s, 100개
    Java CandidateService.getS13Candidates와 동일 소스·필터 (M-2 fix 정렬)"""
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
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s13:{market}", codes, 1200)


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
        if len(codes) >= 80:
            break
    await _lpush_with_ttl(rdb, f"candidates:s15:{market}", codes, 1200)


# ── watchlist 통합 갱신 ─────────────────────────────────────────────────

async def _refresh_watchlist(rdb, ttl: int = 900) -> None:
    """모든 전략 후보 풀 → candidates:watchlist SET 통합.
    websocket-listener _watchlist_poller 가 이 SET 을 5초마다 읽어 동적 구독."""
    all_codes: set[str] = set()
    priority_codes: set[str] = set()
    for n in range(1, 16):
        for mkt in MARKETS:
            try:
                codes = await rdb.lrange(f"candidates:s{n}:{mkt}", 0, -1)
                all_codes.update(c for c in codes if c)
                if n in (1, 7):
                    priority_codes.update(c for c in codes if c)
            except Exception:
                pass
    if not all_codes:
        logger.debug("[builder] watchlist 갱신 건너뜀 (후보 없음)")
        return
    pipe = rdb.pipeline()
    pipe.delete("candidates:watchlist")
    pipe.sadd("candidates:watchlist", *all_codes)
    pipe.expire("candidates:watchlist", ttl)
    pipe.delete("candidates:watchlist:priority")
    if priority_codes:
        pipe.sadd("candidates:watchlist:priority", *priority_codes)
        pipe.expire("candidates:watchlist:priority", ttl)
    await pipe.execute()
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


async def _build_intraday(token: str, rdb, session: str | None = None) -> None:
    """Build intraday candidate pools.

    When session-based ordering is enabled, the S12-only session refreshes only
    candidates:s12:* and leaves existing S2 and other pools as auxiliary inputs.
    """
    s12_only = session == SESSION_S12_ONLY

    if not s12_only:
        for market in MARKETS:
            try:
                if not await rdb.exists(f"candidates:s1:{market}"):
                    logger.info("[builder] S1 %s missing; rebuilding during intraday", market)
                    await _build_s1(token, market, rdb)
                    await asyncio.sleep(_API_INTERVAL)
            except Exception as e:
                logger.error("[builder] S1 %s intraday rebuild failed: %s", market, e)

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
    await _refresh_watchlist(rdb)


# ── 메인 루프 ──────────────────────────────────────────────────────────

async def run_candidate_builder(rdb) -> None:
    """candidates_builder 메인 루프 – engine.py 에서 asyncio.create_task() 로 기동"""
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
                # 장전 집중 갱신: S1/S2 (3분 주기, 08:25 이전)
                logger.info("[builder] 장전 빌드 시작")
                await _build_pre_market(token, rdb)
                await asyncio.sleep(180)
            else:
                # 08:25 이후 S1/S7 풀 동결 – 스캐너가 안정적으로 읽도록 대기
                await asyncio.sleep(60)

        elif time(9, 5) <= now <= time(14, 55):
            # 장중: 전체 전략 갱신
            logger.info("[builder] 장중 빌드 시작")
            await _build_intraday(token, rdb)
            await asyncio.sleep(CANDIDATE_BUILD_INTERVAL_SEC)

        else:
            # 장외: 대기
            await asyncio.sleep(300)
