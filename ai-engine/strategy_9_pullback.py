"""
전술 9: 눌림목 지지 반등 스윙
유형: 스윙 / 보유기간: 3~5거래일
종목 선정: ka10172 HTS 조건검색 (일반)

진입 조건 (AND):
  5일 MA > 20일 MA > 60일 MA (정배열)
  현재가가 5일 MA 기준 -3% ~ +2% 범위 (눌림 구간)
  당일 양봉 + 거래량이 전일 대비 120% 이상 (반등 신호)
  최근 3일 평균 거래량이 최근 10일 평균 대비 80% 이하 (눌림 중 거래량 감소)
  시가총액 500억 이상 / 관리종목 제외

⚠️ TODO: HTS(영웅문) 조건검색기에서 아래 조건식 생성 후 COND_NM / COND_ID 입력 필요
  조건
    1. 5일이평 > 20일이평 > 60일이평 (정배열)
    2. 현재가 ≥ 5일이평 × 0.97 AND 현재가 ≤ 5일이평 × 1.02
    3. 당일 양봉 (현재가 > 시가)
    4. 당일 거래량 / 전일 거래량 ≥ 1.2
    5. 최근 3일 평균 거래량 / 최근 10일 평균 거래량 ≤ 0.8
    6. 시가총액 500억 이상 / 관리종목 제외
"""

import logging
import os

import httpx

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

# TODO: HTS에서 조건식 생성 후 아래 두 값을 입력하세요 (ka10171 목록조회로 확인 가능)
COND_NM = "TODO_눌림목_스윙"       # HTS 조건식명
COND_ID = "TODO_COND_ID"           # ka10171 응답의 cond_id


async def fetch_condition_stocks(token: str) -> list[str]:
    """ka10172 조건검색 요청 일반 – 눌림목 반등 조건 부합 종목 리스트"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/cond",
            headers={
                "api-id": "ka10172",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={"cond_nm": COND_NM, "cond_id": COND_ID},
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("stk_cd", [])
        if isinstance(raw, list):
            return [s for s in raw if isinstance(s, str)]
        return []


async def scan_pullback_swing(token: str, rdb=None) -> list:
    """눌림목 지지 반등 스윙 전략 스캔"""
    if COND_NM.startswith("TODO") or COND_ID.startswith("TODO"):
        logger.warning("[S9] HTS 조건식 미등록. COND_NM / COND_ID를 설정하세요.")
        return []

    candidates = await fetch_condition_stocks(token)
    if not candidates:
        logger.info("[S9] 조건검색 결과 없음")
        return []

    results = []
    for stk_cd in candidates[:20]:
        tick = {}
        if rdb:
            try:
                tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            except Exception:
                pass

        flu_rt_raw = tick.get("flu_rt", "0")
        try:
            flu_rt = float(str(flu_rt_raw).replace("+", "").replace(",", ""))
        except (TypeError, ValueError):
            flu_rt = 0.0

        # 당일 하락 종목 제외 (양봉 조건 이중 확인)
        if flu_rt <= 0:
            continue

        try:
            cntr_str = float(tick.get("cntr_str", 100))
        except (TypeError, ValueError):
            cntr_str = 100.0

        # 체결강도가 지나치게 낮으면 반등 신뢰도 낮음
        if cntr_str < 100:
            continue

        score = flu_rt * 0.4 + max(cntr_str - 100, 0) * 0.15
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S9_PULLBACK_SWING",
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "3~5거래일",
            "target_pct": 6.0,
            "stop_pct": -4.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
