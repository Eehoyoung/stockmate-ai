"""
전술 3: 외인 + 기관 동시 순매수 돌파
타이밍: 9:30 이후 장중
진입 조건 (AND):

ka10063 장중투자자별매매: 외국인 + 기관계 동시 순매수 종목 (smtm_netprps_tp: "1")
ka10065 장중투자자별매매상위: 외국인 상위 20위 내 + 기관 상위 30위 내 동시 해당
ka10131 기관외국인연속매매: 최근 3일 연속 기관+외인 순매수
현재가가 5일선 위 (ka10080 5분봉 데이터로 MA 계산)
당일 거래량이 전일 동시간 대비 ≥ 1.5배 (ka10055)
"""
import httpx
import os

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL")


async def fetch_intraday_investor(token: str, market: str = "000") -> list:
    """ka10063 장중투자자별매매 - 외인+기관 동시 순매수"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
            headers={"api-id": "ka10063", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "mrkt_tp": market,
                "amt_qty_tp": "1",
                "invsr": "6",          # 외국인
                "frgn_all": "1",
                "smtm_netprps_tp": "1",  # 동시순매수
                "stex_tp": "1"
            }
        )
        return resp.json().get("opmr_invsr_trde", [])

async def fetch_continuous_netbuy(token: str, market: str) -> set:
    """ka10131 기관외국인연속매매 - 3일 연속 순매수 종목셋"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/frgnistt",
            headers={"api-id": "ka10131", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "dt": "3",
                "mrkt_tp": market,
                "netslmt_tp": "2",  # 순매수
                "stk_inds_tp": "0",
                "amt_qty_tp": "0",
                "stex_tp": "1"
            }
        )
        items = resp.json().get("orgn_for_cont_trde", [])
        return {x["stk_cd"] for x in items}

async def fetch_volume_compare(token: str, stk_cd: str) -> float:
    """ka10055 당일전일체결량 - 동시간 거래량 비율"""
    async with httpx.AsyncClient() as client:
        today = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={"api-id": "ka10055", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"stk_cd": stk_cd, "tdy_pred": "1"}  # 당일
        )
        prev = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={"api-id": "ka10055", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"stk_cd": stk_cd, "tdy_pred": "2"}  # 전일
        )

    today_qty = sum(int(x.get("cntr_qty", 0))
                    for x in today.json().get("tdy_pred_cntr_qty", []))
    prev_qty = sum(int(x.get("cntr_qty", 0))
                   for x in prev.json().get("tdy_pred_cntr_qty", []))

    return today_qty / prev_qty if prev_qty > 0 else 0

async def scan_inst_foreign(token: str, market: str = "000") -> list:
    smtm_list = await fetch_intraday_investor(token, market)
    cont_set = await fetch_continuous_netbuy(token, market)

    results = []
    for item in smtm_list[:30]:
        stk_cd = item.get("stk_cd")
        if stk_cd not in cont_set:
            continue

        vol_ratio = await fetch_volume_compare(token, stk_cd)
        if vol_ratio < 1.5:
            continue

        net_buy_amt = float(item.get("net_buy_amt", 0))
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S3_INST_FRGN",
            "net_buy_amt": net_buy_amt,
            "vol_ratio": round(vol_ratio, 2),
            "continuous_days": 3,
            "entry_type": "지정가_1호가",
            "target_pct": 3.5,
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
