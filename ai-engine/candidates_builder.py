"""
candidates_builder.py
Python 전담 후보 풀 적재 모듈.
Java CandidateService 역할을 Python으로 이관.

실행: engine.py 에서 asyncio.create_task(run_candidate_builder(rdb)) 로 기동
갱신 주기: CANDIDATE_BUILD_INTERVAL_SEC (기본 600초 = 10분)
"""
import asyncio
import logging
import os
from datetime import datetime, time

import httpx

from http_utils import validate_kiwoom_response

logger = logging.getLogger(__name__)

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
CANDIDATE_BUILD_INTERVAL_SEC = int(os.getenv("CANDIDATE_BUILD_INTERVAL_SEC", "600"))
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

MARKETS = ["001", "101"]  # KOSPI, KOSDAQ


# ── 공통 유틸 ──────────────────────────────────────────────────────────

def _clean(val) -> float:
    """콤마·+ 부호 제거, - 부호 보존"""
    try:
        return float(str(val).replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


async def _lpush_with_ttl(rdb, key: str, codes: list[str], ttl: int) -> None:
    """기존 키를 삭제하고 새 목록을 LPUSH 한 뒤 EXPIRE 설정"""
    if not codes:
        logger.debug("[builder] %s 빈 결과 – 기존 키 유지 (TTL 만료 대기)", key)
        return
    pipe = rdb.pipeline()
    pipe.delete(key)
    pipe.rpush(key, *codes)
    pipe.expire(key, ttl)
    await pipe.execute()
    logger.debug("[builder] %s ← %d종목 (TTL %ds)", key, len(codes), ttl)


# ── S1 / S7: ka10029 예상체결등락률상위 ────────────────────────────────

async def _fetch_ka10029(token: str, market: str) -> list[dict]:
    """ka10029 예상체결등락률상위 (POST /api/dostk/rkinfo)"""
    results = []
    next_key = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            headers = {
                "api-id": "ka10029",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "sort_tp": "1",
                    "trde_qty_cnd": "10",
                    "stk_cnd": "1",
                    "crd_cnd": "0",
                    "pric_cnd": "8",
                    "stex_tp": "1",
                },
            )
            resp.raise_for_status()
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
    """S1 갭상승 시초가: 3.0% ≤ flu_rt ≤ 15.0%, TTL 180s, 100개"""
    items = await _fetch_ka10029(token, market)
    codes = []
    for x in items:
        flu_rt = _clean(x.get("flu_rt", 0))
        if 3.0 <= flu_rt <= 15.0:
            stk_cd = x.get("stk_cd", "")
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s1:{market}", codes, 180)


async def _build_s7(token: str, market: str, rdb) -> None:
    """S7 동시호가: 2.0% ≤ flu_rt ≤ 10.0%, TTL 180s, 100개"""
    items = await _fetch_ka10029(token, market)
    codes = []
    for x in items:
        flu_rt = _clean(x.get("flu_rt", 0))
        if 2.0 <= flu_rt <= 10.0:
            stk_cd = x.get("stk_cd", "")
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s7:{market}", codes, 180)


# ── ka10027 전일대비등락률상위 공통 ─────────────────────────────────────

async def _fetch_ka10027(token: str, market: str, sort_tp: str = "1") -> list[dict]:
    """ka10027 전일대비등락률상위 (POST /api/dostk/rkinfo)"""
    results = []
    next_key = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            headers = {
                "api-id": "ka10027",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "sort_tp": sort_tp,
                    "trde_qty_cnd": "0010",
                    "stk_cnd": "1",
                    "crd_cnd": "0",
                    "updown_incls": "0",
                    "pric_cnd": "8",
                    "trde_prica_cnd": "0",
                    "stex_tp": "1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10027", logger):
                break

            items = data.get("pred_pre_flu_upper", [])
            results.extend(items)

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()
            if cont_yn != "Y" or not next_key:
                break
    return results


async def _build_s4(token: str, market: str, rdb) -> None:
    """S4 장대양봉 추격: 2.0% ≤ flu_rt ≤ 20.0%, TTL 300s, 100개
    ws:strength:{stk_cd} ≥ 120 종목 우선 정렬"""
    items = await _fetch_ka10027(token, market, sort_tp="1")
    strong: list[str] = []
    normal: list[str] = []

    for x in items:
        flu_rt = _clean(x.get("flu_rt", 0))
        if not (2.0 <= flu_rt <= 20.0):
            continue
        stk_cd = x.get("stk_cd", "")
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
    await _lpush_with_ttl(rdb, f"candidates:s4:{market}", codes, 300)


async def _build_s8(token: str, market: str, rdb) -> None:
    """S8 골든크로스 스윙: 0.5% ≤ flu_rt ≤ 8.0%, TTL 1200s, 150개"""
    items = await _fetch_ka10027(token, market, sort_tp="1")
    codes = []
    for x in items:
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.5 <= flu_rt <= 8.0:
            stk_cd = x.get("stk_cd", "")
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 150:
            break
    await _lpush_with_ttl(rdb, f"candidates:s8:{market}", codes, 1200)


async def _build_s9(token: str, market: str, rdb) -> None:
    """S9 눌림목 스윙: 0.3% ≤ flu_rt ≤ 5.0%, TTL 1200s, 150개"""
    items = await _fetch_ka10027(token, market, sort_tp="1")
    codes = []
    for x in items:
        flu_rt = _clean(x.get("flu_rt", 0))
        if 0.3 <= flu_rt <= 5.0:
            stk_cd = x.get("stk_cd", "")
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 150:
            break
    await _lpush_with_ttl(rdb, f"candidates:s9:{market}", codes, 1200)


async def _build_s14(token: str, market: str, rdb) -> None:
    """S14 과매도 반등: sort_tp=3(하락률), 3.0% ≤ abs(flu_rt) ≤ 10.0%, TTL 1200s, 100개"""
    items = await _fetch_ka10027(token, market, sort_tp="3")
    codes = []
    for x in items:
        flu_rt = abs(_clean(x.get("flu_rt", 0)))
        if 3.0 <= flu_rt <= 10.0:
            stk_cd = x.get("stk_cd", "")
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s14:{market}", codes, 1200)


# ── S10: ka10016 신고저가요청 ──────────────────────────────────────────

async def _build_s10(token: str, market: str, rdb) -> None:
    """S10 52주 신고가: ka10016, 필터 없음, TTL 1200s, 100개"""
    results = []
    next_key = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            headers = {
                "api-id": "ka10016",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "ntl_tp": "1",
                    "high_low_close_tp": "1",
                    "stk_cnd": "1",
                    "trde_qty_tp": "00010",
                    "crd_cnd": "0",
                    "updown_incls": "0",
                    "dt": "250",
                    "stex_tp": "1",
                },
            )
            resp.raise_for_status()
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

    codes = [x.get("stk_cd") for x in results if x.get("stk_cd")][:100]
    await _lpush_with_ttl(rdb, f"candidates:s10:{market}", codes, 1200)


# ── S11: ka10035 외인연속순매매상위 ────────────────────────────────────

async def _build_s11(token: str, market: str, rdb) -> None:
    """S11 외인 연속 순매수: dm1>0, dm2>0, dm3>0, tot>0, TTL 1800s, 80개"""
    results = []
    next_key = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            headers = {
                "api-id": "ka10035",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "trde_tp": "2",
                    "base_dt_tp": "1",
                    "stex_tp": "1",
                },
            )
            resp.raise_for_status()
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
        stk_cd = x.get("stk_cd", "")
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
    await _lpush_with_ttl(rdb, f"candidates:s11:{market}", codes, 1800)


# ── S12: ka10032 거래대금상위 ──────────────────────────────────────────

async def _build_s12(token: str, market: str, rdb) -> None:
    """S12 종가강도: flu_rt > 0, TTL 600s, 50개"""
    results = []
    next_key = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            headers = {
                "api-id": "ka10032",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "mang_stk_incls": "0",
                    "stex_tp": "1",
                },
            )
            resp.raise_for_status()
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
        flu_rt = _clean(x.get("flu_rt", 0))
        if flu_rt > 0:
            stk_cd = x.get("stk_cd", "")
            if stk_cd:
                codes.append(stk_cd)
        if len(codes) >= 50:
            break
    await _lpush_with_ttl(rdb, f"candidates:s12:{market}", codes, 600)


# ── S2: ka10054 변동성완화장치발동종목 ───────────────────────────────────

async def _build_s2(token: str, market: str, rdb) -> None:
    """S2 VI 발동 종목: ka10054 상승방향 동적VI, TTL 300s, 50개"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka10054",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "mrkt_tp": market,
                "bf_mkrt_tp": "1",
                "stk_cd": "",
                "motn_tp": "0",
                "skip_stk": "000000000",
                "trde_qty_tp": "0",
                "min_trde_qty": "0",
                "max_trde_qty": "0",
                "trde_prica_tp": "0",
                "min_trde_prica": "0",
                "max_trde_prica": "0",
                "motn_drc": "1",
                "stex_tp": "3",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    if not validate_kiwoom_response(data, "ka10054", logger):
        return

    codes = []
    for x in data.get("motn_stk", []):
        stk_cd = x.get("stk_cd", "")
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
    await _lpush_with_ttl(rdb, f"candidates:s2:{market}", codes, 300)


# ── S3: ka10065 장중투자자별매매상위 (외인 ∩ 기관계) ────────────────────

async def _fetch_ka10065_set(token: str, market: str, orgn_tp: str) -> set:
    """ka10065 장중투자자별매매상위 – 지정 투자자 순매수 종목코드 세트 반환"""
    codes: set = set()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={
                "api-id": "ka10065",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={"trde_tp": "1", "mrkt_tp": market, "orgn_tp": orgn_tp},
        )
        resp.raise_for_status()
        data = resp.json()
    if not validate_kiwoom_response(data, "ka10065", logger):
        return codes
    for x in data.get("opmr_invsr_trde_upper", []):
        stk_cd = x.get("stk_cd", "")
        if stk_cd:
            codes.add(stk_cd)
    return codes


async def _build_s3(token: str, market: str, rdb) -> None:
    """S3 외인+기관 동시순매수: ka10065 교집합, TTL 600s, 100개"""
    frgn_set, inst_set = await asyncio.gather(
        _fetch_ka10065_set(token, market, "9000"),
        _fetch_ka10065_set(token, market, "9999"),
    )
    codes = list(frgn_set & inst_set)[:100]
    await _lpush_with_ttl(rdb, f"candidates:s3:{market}", codes, 600)


# ── S5: ka90003 프로그램순매수상위 ──────────────────────────────────────

_PROG_MRKT_MAP = {"001": "P00101", "101": "P10102"}


async def _build_s5(token: str, market: str, rdb) -> None:
    """S5 프로그램순매수: ka90003, TTL 600s, 100개"""
    kiwoom_mkt = _PROG_MRKT_MAP.get(market, "P00101")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka90003",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "trde_upper_tp": "2",
                "amt_qty_tp": "1",
                "mrkt_tp": kiwoom_mkt,
                "stex_tp": "1",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    if not validate_kiwoom_response(data, "ka90003", logger):
        return

    codes = []
    for x in data.get("prm_netprps_upper_50", []):
        stk_cd = x.get("stk_cd", "")
        try:
            net = _clean(x.get("prm_netprps_amt", "0"))
        except Exception:
            net = 0.0
        if stk_cd and net > 0:
            codes.append(stk_cd)
        if len(codes) >= 100:
            break
    await _lpush_with_ttl(rdb, f"candidates:s5:{market}", codes, 600)


# ── S6: ka90001→ka90002 테마 구성종목 ────────────────────────────────────

async def _build_s6(token: str, rdb) -> None:
    """S6 테마 구성종목: ka90001 상위 5테마→ka90002, TTL 300s, 150개"""
    # 1단계: 상위 5개 테마 코드 추출
    theme_codes: list[str] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/thme",
            headers={
                "api-id": "ka90001",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "qry_tp": "1",
                "date_tp": "1",
                "flu_pl_amt_tp": "3",
                "stex_tp": "1",
            },
        )
    resp.raise_for_status()
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        for tc in theme_codes:
            await asyncio.sleep(_API_INTERVAL)
            resp2 = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/thme",
                headers={
                    "api-id": "ka90002",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"date_tp": "1", "thema_grp_cd": tc, "stex_tp": "1"},
            )
            data2 = resp2.json()
            if not validate_kiwoom_response(data2, "ka90002", logger):
                continue
            for x in data2.get("thema_comp_stk", []):
                stk_cd = x.get("stk_cd", "")
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
        await _lpush_with_ttl(rdb, f"candidates:s6:{market}", codes, 300)


# ── S13 / S15: 기존 풀 재활용 ─────────────────────────────────────────

async def _build_s13(market: str, rdb) -> None:
    """S13 박스권 돌파: candidates:s8 ∪ candidates:s10, TTL 1200s, 150개"""
    try:
        s8 = await rdb.lrange(f"candidates:s8:{market}", 0, -1)
        s10 = await rdb.lrange(f"candidates:s10:{market}", 0, -1)
        # 중복 제거, 순서 유지
        seen: set[str] = set()
        codes: list[str] = []
        for cd in list(s8) + list(s10):
            if cd not in seen:
                seen.add(cd)
                codes.append(cd)
            if len(codes) >= 150:
                break
        await _lpush_with_ttl(rdb, f"candidates:s13:{market}", codes, 1200)
    except Exception as e:
        logger.warning("[builder] S13 %s 합산 실패: %s", market, e)


async def _build_s15(market: str, rdb) -> None:
    """S15 모멘텀 정렬: candidates:s8 재활용, TTL 1200s, 100개"""
    try:
        s8 = await rdb.lrange(f"candidates:s8:{market}", 0, 99)
        codes = list(s8)[:100]
        await _lpush_with_ttl(rdb, f"candidates:s15:{market}", codes, 1200)
    except Exception as e:
        logger.warning("[builder] S15 %s 재활용 실패: %s", market, e)


# ── 배치 빌드 함수 ─────────────────────────────────────────────────────

async def _build_pre_market(token: str, rdb) -> None:
    """장전 배치: S1, S7 (ka10029), S2 (ka10054)"""
    for market in MARKETS:
        try:
            await _build_s1(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s7(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s2(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
        except Exception as e:
            logger.error("[builder] 장전 %s 빌드 오류: %s", market, e)


async def _build_intraday(token: str, rdb) -> None:
    """장중 배치: S2~S15 전략 풀 갱신"""
    for market in MARKETS:
        try:
            await _build_s2(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s3(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s4(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s5(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s8(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s9(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s10(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s11(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s12(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)
            await _build_s14(token, market, rdb)
            await asyncio.sleep(_API_INTERVAL)

            # 파생 풀: S8/S10 완료 후 구성
            await _build_s13(market, rdb)
            await _build_s15(market, rdb)

        except Exception as e:
            logger.error("[builder] 장중 %s 빌드 오류: %s", market, e)

    # S6: 테마는 시장 무관 → 루프 외부에서 1회 호출
    try:
        await _build_s6(token, rdb)
    except Exception as e:
        logger.error("[builder] S6 빌드 오류: %s", e)


# ── 메인 루프 ──────────────────────────────────────────────────────────

async def run_candidate_builder(rdb) -> None:
    """candidates_builder 메인 루프 — engine.py 에서 asyncio.create_task() 로 기동"""
    logger.info("[builder] candidates_builder 시작 (주기=%ds)", CANDIDATE_BUILD_INTERVAL_SEC)

    while True:
        now = datetime.now().time()
        try:
            token = await rdb.get("kiwoom:token")
        except Exception as e:
            logger.warning("[builder] Redis token 조회 실패: %s", e)
            token = None

        if not token:
            logger.debug("[builder] kiwoom:token 없음 — 30초 대기")
            await asyncio.sleep(30)
            continue

        if time(7, 25) <= now <= time(9, 10):
            # 장전: S1, S7 집중 갱신 (3분 주기)
            logger.info("[builder] 장전 빌드 시작")
            await _build_pre_market(token, rdb)
            await asyncio.sleep(180)

        elif time(9, 5) <= now <= time(14, 55):
            # 장중: 전체 전략 갱신
            logger.info("[builder] 장중 빌드 시작")
            await _build_intraday(token, rdb)
            await asyncio.sleep(CANDIDATE_BUILD_INTERVAL_SEC)

        else:
            # 장외: 대기
            await asyncio.sleep(300)
