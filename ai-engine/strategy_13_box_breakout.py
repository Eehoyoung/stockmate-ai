"""
전술 13: 거래량 폭발 박스권 돌파 스윙
유형: 스윙 / 보유기간: 3~7거래일
종목 선정: ka10172 HTS 조건검색 (일반)

진입 조건 (AND):
  최근 10~30거래일 고가-저가 변동폭 ≤ 8% (박스권 형성)
  당일 박스 상단(최근 N일 최고가) 상향 돌파
  당일 거래량 ≥ 20일 평균 거래량 × 3.0 (거래량 폭발)
  당일 양봉 + 종가가 당일 고가의 80% 이상 (장대 양봉 형태)
  체결강도 ≥ 130%
  시가총액 300억 이상 / 관리종목·ETF 제외

⚠️ TODO: HTS(영웅문) 조건검색기에서 아래 조건식 생성 후 COND_NM / COND_ID 입력 필요
  조건 내용:
    1. 최근 15거래일 (고가 - 저가) / 저가 ≤ 8%  → 박스권 판단
    2. 당일 고가 > 최근 15거래일 최고가            → 박스 상단 돌파
    3. 당일 거래량 / 20일평균거래량 ≥ 3.0          → 거래량 폭발
    4. 현재가 > 시가 (양봉)
    5. 현재가 / 당일 고가 ≥ 0.80                  → 장대 양봉 형태
    6. 시가총액 300억 이상 / 관리종목·ETF 제외
    7. 당일 등락률 ≤ 20% (상한가 종목 제외)
"""

import logging
import os

import httpx

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

# TODO: HTS에서 조건식 생성 후 아래 두 값을 입력하세요 (ka10171 목록조회로 확인 가능)
COND_NM = "TODO_박스권돌파_스윙"   # HTS 조건식명
COND_ID = "TODO_COND_ID"           # ka10171 응답의 cond_id

MIN_CNTR_STR = float(os.getenv("S13_MIN_CNTR_STR", "130.0"))


async def fetch_condition_stocks(token: str) -> list[str]:
    """ka10172 조건검색 요청 일반 – 박스권 돌파 조건 부합 종목 리스트"""
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


async def scan_box_breakout(token: str, rdb=None) -> list:
    """거래량 폭발 박스권 돌파 스윙 전략 스캔"""
    if COND_NM.startswith("TODO") or COND_ID.startswith("TODO"):
        logger.warning("[S13] HTS 조건식 미등록. COND_NM / COND_ID를 설정하세요.")
        return []

    candidates = await fetch_condition_stocks(token)
    if not candidates:
        logger.info("[S13] 조건검색 결과 없음")
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

        # 상한가 종목(20% 초과) 제외
        if flu_rt > 20.0 or flu_rt <= 0:
            continue

        # 체결강도 확인 (Redis)
        cntr_str = 100.0
        if rdb:
            try:
                import statistics
                strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 4)
                if strength_data:
                    cntr_str = statistics.mean([float(s) for s in strength_data])
            except Exception:
                pass

        if cntr_str < MIN_CNTR_STR:
            continue

        score = flu_rt * 0.4 + (cntr_str - 100) * 0.3
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S13_BOX_BREAKOUT",
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "3~7거래일",
            "target_pct": 10.0,
            "stop_pct": -5.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
