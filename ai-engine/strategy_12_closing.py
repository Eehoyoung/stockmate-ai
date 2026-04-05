"""
전술 12: 종가 강도 확인 매수 (종가매매)
유형: 종가매매 / 보유기간: 2~5거래일
종목 선정: ka10027 전일대비등락률상위 + ka10063 장중투자자별매매 교차 필터

진입 조건 (AND):
  ka10027: 당일 등락률 ≥ 4% (충분한 장중 모멘텀)
  ka10027: 체결강도(cntr_str) ≥ 110% — 응답에 직접 포함
  ka10063: 당일 기관 순매수 확인 (수급 뒷받침)
  당일 등락률 ≤ 15% (과도한 급등 제외)

타이밍: 14:30~14:50 체크 → 14:50~15:00 동시호가 시장가 진입

API 실제 스펙 (docs/api_new/ka10027.md 기준):
  - 파라미터: mrkt_tp, sort_tp, trde_qty_cnd, stk_cnd, crd_cnd, updown_incls, pric_cnd, trde_prica_cnd, stex_tp
  - 응답키: pred_pre_flu_rt_upper
  - 응답 필드: stk_cd, cur_prc, flu_rt(+/- 포함), cntr_str, now_trde_qty, sel_req, buy_req
  - ※ cntr_str이 응답에 포함되므로 Redis 조회 불필요
"""

import asyncio
import logging
import os

import httpx

from http_utils import validate_kiwoom_response, fetch_stk_nm

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

MIN_FLU_RT = float(os.getenv("S12_MIN_FLU_RT", "4.0"))       # 최소 등락률 (%)
MIN_CNTR_STR = float(os.getenv("S12_MIN_CNTR_STR", "110.0"))  # 최소 체결강도


async def fetch_top_gainers_paged(token: str, market: str = "000", max_pages: int = 2) -> list[dict]:
    """ka10027 전일대비등락률상위 - 연속조회 지원"""
    all_gainers = []
    cont_yn, next_key = "N", ""

    async with httpx.AsyncClient(timeout=10.0) as client:
        for _ in range(max_pages):
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers={
                    "api-id": "ka10027", "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                    "cont-yn": cont_yn, "next-key": next_key
                },
                json={
                    "mrkt_tp": market, "sort_tp": "1", "trde_qty_cnd": "0010",
                    "stk_cnd": "1", "crd_cnd": "0", "updown_incls": "0",
                    "pric_cnd": "8", "trde_prica_cnd": "10", "stex_tp": "1"
                }
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10027", logger): break

            all_gainers.extend(data.get("pred_pre_flu_rt_upper", []))
            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if cont_yn != "Y" or not next_key: break
            await asyncio.sleep(0.2)

    return all_gainers


async def fetch_inst_netbuy_set(token: str, market: str = "000") -> set[str]:
    """ka10063 장중투자자별매매요청 – 기관 당일 순매수 종목 집합"""
    async with httpx.AsyncClient(timeout=10.0) as client:
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
                "stex_tp": "1",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10063", logger):
            return set()
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
        return result


async def scan_closing_buy(token: str, market: str = "000", rdb=None) -> list:
    """S12: 종가 강도 + 기관 수급 교차 필터"""
    # 1. 기관 순매수 세트와 등락률 상위 리스트 병렬 호출
    gainers_task = fetch_top_gainers_paged(token, market)
    inst_set_task = fetch_inst_netbuy_set(token, market) # 기존 코드 활용
    gainers, inst_set = await asyncio.gather(gainers_task, inst_set_task)

    results = []
    for item in gainers:
        stk_cd = item.get("stk_cd")
        if not stk_cd or stk_cd not in inst_set: continue

        # 수치 파싱
        flu_rt = float(str(item.get("flu_rt", "0")).replace("+", ""))
        cntr_str = float(item.get("cntr_str", "0"))

        # 조건 검증: 4% <= 등락률 <= 15% AND 체결강도 >= 110%
        if not (4.0 <= flu_rt <= 15.0) or cntr_str < 110.0:
            continue

        # 점수 산정: 등락률의 탄력과 체결강도의 밀도를 조합
        # $Score = (Flu\_Rate \times 0.5) + ((Cntr\_Str - 100) \times 0.3)$
        score = (flu_rt * 0.5) + (max(cntr_str - 100, 0) * 0.3)

        cur_prc = abs(float(str(item.get("cur_prc", "0")).replace(",", "")))
        stk_nm = item.get("stk_nm", "").strip() or await fetch_stk_nm(rdb, token, stk_cd)

        try:
            buy_req = float(str(item.get("buy_req", "0")).replace(",", "").replace("+", "") or "0")
            sel_req = float(str(item.get("sel_req", "1")).replace(",", "").replace("+", "") or "1")
        except (TypeError, ValueError):
            buy_req, sel_req = 0.0, 1.0

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
            "target_pct": 5.0,
            "stop_pct": -3.0
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
