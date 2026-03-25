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

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

MIN_FLU_RT = float(os.getenv("S12_MIN_FLU_RT", "4.0"))       # 최소 등락률 (%)
MIN_CNTR_STR = float(os.getenv("S12_MIN_CNTR_STR", "110.0"))  # 최소 체결강도


async def fetch_top_gainers(token: str, market: str = "000") -> list[dict]:
    """ka10027 전일대비등락률상위요청 – 상승률 상위 종목
    응답 배열키: pred_pre_flu_rt_upper
    응답 필드: stk_cd, flu_rt("+29.86" 형식), cntr_str, now_trde_qty
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={
                "api-id": "ka10027",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "mrkt_tp": market,
                "sort_tp": "1",          # 1: 상승률순
                "trde_qty_cnd": "0010",  # 만주 이상
                "stk_cnd": "1",          # 관리종목 제외
                "crd_cnd": "0",          # 전체 조회
                "updown_incls": "0",     # 상하한 미포함
                "pric_cnd": "8",         # 1천원 이상
                "trde_prica_cnd": "10",  # 거래대금 1억원 이상
                "stex_tp": "1",          # KRX
            },
        )
        resp.raise_for_status()
        # 응답 배열키: pred_pre_flu_rt_upper
        return resp.json().get("pred_pre_flu_rt_upper", [])


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
        items = resp.json().get("opmr_invsr_trde", [])
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
    """종가 강도 확인 매수 (종가매매) 스캔 – 14:30 이후 실행 권장"""
    gainers, inst_set = await asyncio.gather(
        fetch_top_gainers(token, market),
        fetch_inst_netbuy_set(token, market),
    )

    results = []
    for item in gainers:
        stk_cd = item.get("stk_cd")
        if not stk_cd:
            continue

        # flu_rt: "+29.86" 형식
        try:
            flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
        except (TypeError, ValueError):
            continue

        # 등락률 4% ~ 15% 범위
        if not (MIN_FLU_RT <= flu_rt <= 15.0):
            continue

        # 체결강도: ka10027 응답에 cntr_str 직접 포함 — Redis 조회 불필요
        try:
            cntr_str = float(item.get("cntr_str", "0"))
        except (TypeError, ValueError):
            cntr_str = 0.0

        if cntr_str < MIN_CNTR_STR:
            continue

        # 기관 순매수 교차 필터
        if stk_cd not in inst_set:
            continue

        # 현재가 파싱 (ka10027 응답 cur_prc, 부호 제거 후 절대값)
        try:
            cur_prc = abs(float(str(item.get("cur_prc", "0")).replace(",", "").replace("+", "") or "0"))
        except (TypeError, ValueError):
            cur_prc = 0.0

        score = flu_rt * 0.5 + (cntr_str - 100) * 0.3
        results.append({
            "stk_cd": stk_cd,
            "cur_prc": round(cur_prc) if cur_prc > 0 else None,
            "strategy": "S12_CLOSING",
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "entry_type": "종가_동시호가",
            "holding_days": "2~5거래일",
            "target_pct": 5.0,
            "stop_pct": -3.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
