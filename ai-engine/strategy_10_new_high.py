"""
전술 10: 52주 신고가 돌파 스윙
유형: 스윙 / 보유기간: 5~10거래일
종목 선정: ka10016 신고저가요청 (term=250, 약 1년)

진입 조건 (AND):
  ka10016: 당일 52주(250거래일) 신고가 기록 종목
  ka10023: 전일 대비 거래량 급증률 ≥ 100% (거래량 2배 이상 동반 돌파)
  당일 등락률 2% ~ 15% 범위 (소폭 돌파 ~ 과도한 갭 제외)
  관리종목·ETF 제외
"""

import asyncio
import logging
import os

import httpx

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

# 52주 ≈ 250거래일
NEW_HIGH_TERM = os.getenv("S10_NEW_HIGH_TERM", "250")


async def fetch_new_high_stocks(token: str, market: str = "000") -> list[dict]:
    """ka10016 신고저가요청 – 52주 신고가 종목 리스트
    응답 배열키: ntl_pric
    파라미터: dt (기간 일수), trde_qty_tp, crd_cnd, updown_incls 필수
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka10016",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "mrkt_tp": market,
                "ntl_tp": "1",              # 1: 신고가
                "high_low_close_tp": "1",   # 1: 고저 기준
                "stk_cnd": "1",             # 관리종목 제외
                "trde_qty_tp": "00010",     # 만주 이상
                "crd_cnd": "0",             # 전체 조회
                "updown_incls": "0",        # 상하한 미포함
                "dt": NEW_HIGH_TERM,        # 기간 (5/10/20/60/250)
                "stex_tp": "1",             # KRX
            },
        )
        resp.raise_for_status()
        # 응답 배열키: ntl_pric
        return resp.json().get("ntl_pric", [])


async def fetch_volume_surge_set(token: str, market: str = "000") -> dict[str, float]:
    """ka10023 거래량급증요청 (전일 대비) – sdnin_rt(급증률) 매핑 반환"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={
                "api-id": "ka10023",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "mrkt_tp": market,
                "sort_tp": "2",       # 급증률순
                "tm_tp": "2",         # 전일 대비
                "trde_qty_tp": "10",  # 만주 이상
                "stk_cnd": "1",       # 관리종목 제외
                "pric_tp": "8",       # 1천원 이상
                "stex_tp": "1",
            },
        )
        resp.raise_for_status()
        items = resp.json().get("trde_qty_sdnin", [])
        result = {}
        for item in items:
            stk_cd = item.get("stk_cd")
            if not stk_cd:
                continue
            try:
                sdnin_rt = float(str(item.get("sdnin_rt", "0")).replace("+", "").replace(",", ""))
                result[stk_cd] = sdnin_rt
            except (TypeError, ValueError):
                pass
        return result


async def scan_new_high_swing(token: str, market: str = "000", rdb=None) -> list:
    """52주 신고가 돌파 스윙 전략 스캔"""
    new_high_items, vol_surge_map = await asyncio.gather(
        fetch_new_high_stocks(token, market),
        fetch_volume_surge_set(token, market),
    )

    results = []
    for item in new_high_items:
        stk_cd = item.get("stk_cd")
        if not stk_cd:
            continue

        # 등락률 필터: 2% ~ 15%
        try:
            # flu_rt: "+10.82", "-0.95" 형식
            flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
        except (TypeError, ValueError):
            continue

        if not (2.0 <= flu_rt <= 15.0):
            continue

        # 거래량 급증 교차 필터: 전일 대비 100% 이상 (2배)
        sdnin_rt = vol_surge_map.get(stk_cd, 0.0)
        if sdnin_rt < 100.0:
            continue

        # 현재가 파싱 (ka10016 응답 필드 cur_prc, 부호 제거 후 절대값 사용)
        try:
            cur_prc = abs(float(str(item.get("cur_prc", "0")).replace(",", "").replace("+", "") or "0"))
        except (TypeError, ValueError):
            cur_prc = 0.0

        # 종목명 (표시용)
        stk_nm = str(item.get("stk_nm", "")).strip()

        # 체결강도 확인 (Redis ws:strength TTL 300s 우선, 없으면 ws:tick TTL 30s fallback)
        cntr_str = 100.0
        if rdb:
            try:
                strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 4)
                if strength_data:
                    cntr_str = sum(float(s) for s in strength_data) / len(strength_data)
                else:
                    tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                    if tick:
                        cntr_str = float(tick.get("cntr_str", 100))
            except Exception:
                pass

        score = flu_rt * 0.4 + min(sdnin_rt / 100, 5.0) * 10 + max(cntr_str - 100, 0) * 0.2
        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": round(cur_prc) if cur_prc > 0 else None,
            "strategy": "S10_NEW_HIGH",
            "flu_rt": round(flu_rt, 2),
            "vol_surge_rt": round(sdnin_rt, 1),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "5~10거래일",
            "target_pct": 12.0,
            "target2_pct": 18.0,
            "stop_pct": -5.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
