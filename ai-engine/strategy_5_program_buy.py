"""
전술 5: 프로그램 순매수 + 외인 동반 상위
타이밍: 10:00~14:00
진입 조건 (AND):

ka90003 프로그램 순매수 상위 50 내 포함 (금액 기준)
ka90009 외국인+기관 매매상위에도 동시 포함
ka10044 일별기관매매: 전일 기관 순매수 종목
현재가 5일 이평선 상단 유지
"""
import asyncio
import httpx
import logging
import os

logger = logging.getLogger(__name__)

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

async def fetch_program_netbuy(token: str, market: str) -> dict:
    """ka90003 프로그램순매수상위50"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={"api-id": "ka90003", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "trde_upper_tp": "2",   # 순매수상위
                "amt_qty_tp": "1",      # 금액
                "mrkt_tp": market,
                "stex_tp": "1"
            }
        )
        resp.raise_for_status()
        items = resp.json().get("prm_netprps_upper_50", [])
        return {x["stk_cd"]: int(x.get("net_buy_amt", 0)) for x in items}


async def fetch_frgn_inst_upper(token: str, market: str) -> set:
    """ka90009 외국인기관매매상위"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={"api-id": "ka90009", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "mrkt_tp": market,
                "amt_qty_tp": "1",
                "qry_dt_tp": "0",
                "stex_tp": "1"
            }
        )
        resp.raise_for_status()
        items = resp.json().get("for_inst_trde_upper", [])
        return {x["stk_cd"] for x in items}

async def scan_program_buy(token: str, market: str = "000") -> list:
    prog_map, frgn_set = await asyncio.gather(
        fetch_program_netbuy(token, market),
        fetch_frgn_inst_upper(token, market)
    )

    overlap = set(prog_map.keys()) & frgn_set
    results = []

    for stk_cd in overlap:
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S5_PROG_FRGN",
            "net_buy_amt": prog_map[stk_cd],
            "entry_type": "지정가_1호가",
            "target_pct": 3.0,
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
