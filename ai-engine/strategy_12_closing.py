from __future__ import annotations
"""
전술 12: 종가 강도 확인 매수 (종가매매)
유형: 종가매매 / 보유기간: 2~5거래일
종목 선정: ka10027 전일대비등락률상위 + ka10063 장중투자자별매매 교차 필터

진입 조건 (AND):
  ka10027: 당일 등락률 ≥ 4% (충분한 장중 모멘텀)
  ka10027: 체결강도(cntr_str) ≥ 110% — 응답에 직접 포함
  ka10063: 당일 기관 순매수 확인 (수급 뒷받침)
  당일 등락률 ≤ 15% (과도한 급등 제외)

타이밍: 14:30~15:10 체크 → 15:10 이후 동시호가 전 진입 검토

API 실제 스펙 (docs/api_new/ka10027.md 기준):
  - 파라미터: mrkt_tp, sort_tp, trde_qty_cnd, stk_cnd, crd_cnd, updown_incls, pric_cnd, trde_prica_cnd, stex_tp
  - 응답키: pred_pre_flu_rt_upper
  - 응답 필드: stk_cd, cur_prc, flu_rt(+/- 포함), cntr_str, now_trde_qty, sel_req, buy_req
  - ※ cntr_str이 응답에 포함되므로 Redis 조회 불필요
"""

import asyncio
import logging
import os
from collections import Counter, defaultdict

import httpx

from http_utils import validate_kiwoom_response, fetch_stk_nm, kiwoom_client, KiwoomReservationUnavailable
from ma_utils import fetch_daily_candles, _safe_price
from tp_sl_engine import calc_tp_sl

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

MIN_FLU_RT = float(os.getenv("S12_MIN_FLU_RT", "4.0"))       # 최소 등락률 (%)
MIN_CNTR_STR = float(os.getenv("S12_MIN_CNTR_STR", "110.0"))  # 최소 체결강도
POOL_BONUS = float(os.getenv("S12_POOL_BONUS", "5.0"))        # 거래대금상위 풀 동시 충족 가점


async def fetch_top_gainers_paged(token: str, market: str = "000", max_pages: int = 2) -> list[dict]:
    """ka10027 전일대비등락률상위 - 연속조회 지원"""
    all_gainers = []
    cont_yn, next_key = "N", ""

    async with kiwoom_client() as client:
        for _ in range(max_pages):
            try:
                resp = await client.post(
                    f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                    headers={
                        "api-id": "ka10027", "authorization": f"Bearer {token}",
                        "Content-Type": "application/json;charset=UTF-8",
                        "cont-yn": cont_yn, "next-key": next_key
                    },
                    json={
                        "mrkt_tp": market, "sort_tp": "1", "trde_qty_cnd": "0010",
                        "stk_cnd": "16", "crd_cnd": "0", "updown_incls": "0",
                        "pric_cnd": "8", "trde_prica_cnd": "10", "stex_tp": "3"
                    }
                )
            except KiwoomReservationUnavailable:
                logger.warning("[S12] Kiwoom rate limiter unavailable — 부분 결과로 조기 종료 (api=%s)", "ka10027")
                break
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10027", logger): break

            all_gainers.extend(data.get("pred_pre_flu_rt_upper", []))
            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if cont_yn != "Y" or not next_key: break
            await asyncio.sleep(0.2)

    return all_gainers


async def fetch_inst_netbuy_set(token: str, market: str = "000") -> tuple[set[str], bool]:
    """ka10063 장중투자자별매매요청 – 기관 당일 순매수 종목 집합.

    반환: (종목집합, 조회성공여부)

    성공여부를 함께 돌려주는 이유: 조회가 실패해도 빈 집합이 나오고,
    "기관이 아무것도 안 샀다"는 정상 결과도 빈 집합이다. 이 둘을 구분하지
    않으면 API가 죽은 날에도 전 종목이 조용히 필터링되면서 스캔이 정상
    동작한 것처럼 보인다(2026-08-14 관측).
    """
    async with kiwoom_client() as client:
        try:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10063",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "mrkt_tp": market,
                    "amt_qty_tp": "1",
                    "invsr": "7",            # 7: 기관계
                    "frgn_all": "0",
                    "smtm_netprps_tp": "0",  # 기관 단독 순매수
                    "stex_tp": "3",
                },
            )
        except KiwoomReservationUnavailable:
            logger.warning("[S12] Kiwoom rate limiter unavailable — 부분 결과로 조기 종료 (api=%s)", "ka10063")
            return set(), False
        resp.raise_for_status()
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10063", logger):
            return set(), False
        items = data.get("opmr_invsr_trde", [])
        result = set()
        for item in items:
            stk_cd = item.get("stk_cd")
            if not stk_cd:
                continue
            try:
                netprps_qty = int(str(item.get("netprps_qty", "0")).replace("+", "").replace(",", ""))
                if netprps_qty > 0:
                    result.add(stk_cd)
            except (TypeError, ValueError):
                pass
        return result, True


async def scan_closing_buy(token: str, market: str = "000", rdb=None) -> list:
    """S12: 종가 강도 + 기관 수급 교차 필터

    흐름:
      1. candidates:s12:{market} 풀 우선 읽기 (candidates_builder가 ka10032로 생성)
      2. ka10027 등락률상위 + ka10063 기관순매수 병렬 조회
      3. gainers 중 inst_set 교집합 (풀은 하드 게이트가 아니라 가점)
      4. 조건 검증(flu_rt/cntr_str) → 점수 산정
    """
    # 0. candidates:s12:{market} 풀 로드 — market="000" 시 001+101 모두 로드
    pool_set: set[str] = set()
    if rdb:
        _markets = [market] if market in ("001", "101") else ["001", "101"]
        for _m in _markets:
            try:
                pool = await rdb.lrange(f"candidates:s12:{_m}", 0, -1)
                if pool:
                    pool_set.update(pool)
                    logger.debug("[S12] 풀 %d종목 로드 (candidates:s12:%s)", len(pool), _m)
            except Exception as e:
                logger.warning("[S12] 풀 조회 실패 (candidates:s12:%s): %s", _m, e)
        if not pool_set:
            logger.debug("[S12] 모든 풀 없음 — 전체 스캔 fallback")

    # 1. 기관 순매수 세트와 등락률 상위 리스트 병렬 호출
    gainers_task = fetch_top_gainers_paged(token, market)
    inst_set_task = fetch_inst_netbuy_set(token, market)
    gainers, (inst_set, inst_ok) = await asyncio.gather(gainers_task, inst_set_task)

    if not gainers:
        logger.info("[S12][scan_summary] candidate_count=0 pass=0 rejects={'no_candidates': 1}")
        return []

    # 기관 수급이 S12의 핵심 근거다. 조회 자체가 실패했으면 전 종목을
    # "기관 미매수"로 떨구지 말고 이번 사이클을 건너뛴다.
    if not inst_ok:
        logger.warning(
            "[S12][scan_summary] candidate_count=%d pass=0 rejects={'inst_netbuy_fetch_failed': 1} "
            "— ka10063 조회 실패로 스캔 생략",
            len(gainers),
        )
        return []

    results = []
    reject_counts: Counter = Counter()
    reject_samples: defaultdict = defaultdict(list)
    evaluated_count = 0

    def _reject(reason: str, stk_cd: str, **fields) -> None:
        reject_counts[reason] += 1
        if len(reject_samples[reason]) < 5:
            sample = {"stk_cd": stk_cd}
            sample.update(fields)
            reject_samples[reason].append(sample)

    for item in gainers:
        stk_cd = item.get("stk_cd")
        evaluated_count += 1
        if not stk_cd or stk_cd not in inst_set:
            # 이름 주의: API 실패가 아니라 "기관 순매수 집합에 없음"이다.
            _reject("not_inst_netbuy", stk_cd or "unknown")
            continue

        # 풀(candidates:s12, ka10032 거래대금상위)은 gainers(ka10027 등락률상위)와
        # 서로 다른 유니버스라 AND로 걸면 교집합이 사실상 비어버린다. 2026-08-14에
        # 기관 필터를 통과한 47~106종목이 전부 여기서 잘려 하루 28,000평가 0통과가
        # 났다. 유동성 근거로서의 가치는 남기되 하드 게이트에서 가점으로 낮춘다.
        in_pool = bool(pool_set) and stk_cd in pool_set

        # 수치 파싱
        flu_rt = float(str(item.get("flu_rt", "0")).replace("+", ""))
        cntr_str = float(item.get("cntr_str", "0"))

        # 조건 검증: 4% <= 등락률 <= 15% AND 체결강도 >= 110%
        if not (MIN_FLU_RT <= flu_rt <= 15.0) or cntr_str < MIN_CNTR_STR:
            _reject("flu_rt_or_cntr_str_out_of_range", stk_cd, flu_rt=round(flu_rt, 2), cntr_str=round(cntr_str, 1))
            continue

        # 점수 산정: 등락률의 탄력과 체결강도의 밀도를 조합
        # $Score = (Flu\_Rate \times 0.5) + ((Cntr\_Str - 100) \times 0.3)$
        score = (flu_rt * 0.5) + (max(cntr_str - 100, 0) * 0.3)
        if in_pool:
            score += POOL_BONUS  # 거래대금상위 동시 충족 = 유동성 근거 보강

        cur_prc = abs(float(str(item.get("cur_prc", "0")).replace(",", "")))
        stk_nm = item.get("stk_nm", "").strip() or await fetch_stk_nm(rdb, token, stk_cd)

        try:
            buy_req = float(str(item.get("buy_req", "0")).replace(",", "").replace("+", "") or "0")
            sel_req = float(str(item.get("sel_req", "1")).replace(",", "").replace("+", "") or "1")
        except (TypeError, ValueError):
            buy_req, sel_req = 0.0, 1.0

        # 동적 TP/SL — 당일 저점 + 스윙 고점 기반 (일봉 조회)
        highs_d, lows_d, closes_d, ma5, ma20 = [], [], [], None, None
        try:
            await asyncio.sleep(0.2)
            candles = await fetch_daily_candles(token, stk_cd)
            closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
            highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
            lows_d   = [_safe_price(c.get("low_pric")) for c in candles]
            if len(closes_d) >= 5:
                ma5 = sum(closes_d[:5]) / 5
            if len(closes_d) >= 20:
                ma20 = sum(closes_d[:20]) / 20
        except Exception as e:
            logger.debug("[S12] 일봉 조회 실패 %s: %s", stk_cd, e)

        tp_sl = calc_tp_sl("S12_CLOSING", cur_prc, highs_d, lows_d, closes_d,
                           stk_cd=stk_cd, ma5=ma5, ma20=ma20)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": int(cur_prc),
            "strategy": "S12_CLOSING",
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "buy_req": buy_req,
            "sel_req": sel_req,
            "score": round(score, 2),
            "entry_type": "15:20_장마감_전_진입",
            **tp_sl.to_signal_fields(),
        })

    sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)[:5]
    logger.info(
        "[S12][scan_summary] candidate_count=%d evaluated=%d pass=%d returned=%d rejects=%s samples=%s",
        len(gainers),
        evaluated_count,
        len(results),
        len(sorted_results),
        dict(reject_counts),
        {key: value for key, value in reject_samples.items()},
    )
    return sorted_results
