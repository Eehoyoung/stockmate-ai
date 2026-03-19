"""
전술 6: 테마 상위 + 구성종목 연동
타이밍: 9:30~13:00 (테마 모멘텀 집중 시간)
진입 조건:

ka90001 테마그룹 상위 등락률 1위~5위 그룹 추출
ka90002 해당 테마 구성종목 중 등락률 상위 30% 제외 (이미 많이 오른 종목)
구성종목 중 5% 미만 상승 + 체결강도 ≥ 120% + 거래량 급증 종목 선별
테마 내 선도주 이미 강하게 오른 경우 → 후발주 매수
"""

import httpx
import os
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL")
async def fetch_theme_groups(token: str) -> list:
    """ka90001 테마그룹별 상위 수익률"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/thme",
            headers={"api-id": "ka90001", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "qry_tp": "1",          # 테마검색
                "date_tp": "1",         # 1일
                "flu_pl_amt_tp": "1",   # 상위기간수익률
                "stex_tp": "1"
            }
        )
        return resp.json().get("thme_grp", [])[:5]  # 상위 5 테마

async def fetch_theme_stocks(token: str, thema_grp_cd: str) -> list:
    """ka90002 테마구성종목"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/thme",
            headers={"api-id": "ka90002", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"date_tp": "1", "thema_grp_cd": thema_grp_cd, "stex_tp": "1"}
        )
        return resp.json().get("thme_comp_stk", [])


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """
    체결강도 조회 (ka10003 체결정보요청)
    - 종목코드(stk_cd)를 입력받아 최근 체결정보의 cntr_str 반환
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka10003",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            },
            json={"stk_cd": stk_cd}
        )

    data = resp.json()
    cntr_infr = data.get("cntr_infr", [])
    if not cntr_infr:
        return 0.0

    # 가장 최근 체결정보의 cntr_str 사용
    latest = cntr_infr[0]
    strength = latest.get("cntr_str", "0")
    try:
        return float(strength)
    except ValueError:
        return 0.0




async def scan_theme_laggard(token: str) -> list:
    themes = await fetch_theme_groups(token)
    results = []

    for theme in themes:
        thema_grp_cd = theme.get("thema_grp_cd")
        theme_flu_rt = float(theme.get("flu_rt", 0))

        if theme_flu_rt < 2.0:  # 테마 자체 등락률 2% 미만 제외
            continue

        stocks = await fetch_theme_stocks(token, thema_grp_cd)
        flu_rates = [float(s.get("flu_rt", 0)) for s in stocks]

        if not flu_rates:
            continue

        p70 = sorted(flu_rates)[int(len(flu_rates) * 0.7)]  # 상위 30% 기준

        for stk in stocks:
            stk_cd = stk.get("stk_cd")
            flu_rt = float(stk.get("flu_rt", 0))

            # 후발주 조건: 테마 평균보다 낮지만 상승 중
            if not (0.5 <= flu_rt < p70) or flu_rt >= 5.0:
                continue

            strength = await fetch_cntr_strength(token, stk_cd)
            if strength < 120:
                continue

            results.append({
                "stk_cd": stk_cd,
                "strategy": "S6_THEME_LAGGARD",
                "theme_name": theme.get("thema_nm"),
                "theme_flu_rt": theme_flu_rt,
                "stk_flu_rt": flu_rt,
                "cntr_strength": round(strength, 1),
                "entry_type": "지정가_1호가",
                "target_pct": theme_flu_rt * 0.6,  # 테마 상승률의 60%
                "stop_pct": -2.0,
            })

    return sorted(results, key=lambda x: x["cntr_strength"], reverse=True)[:5]
