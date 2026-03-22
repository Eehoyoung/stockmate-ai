"""
전술 8: 20일선 골든크로스 스윙
유형: 스윙 / 보유기간: 3~7거래일
종목 선정: ka10172 HTS 조건검색 (일반)

진입 조건 (AND):
  5일 MA가 20일 MA 상향 돌파 (당일 골든크로스)
  당일 거래량 ≥ 20일 평균 거래량 × 1.5
  RSI(14) 40~65 구간
  현재가가 60일 MA 기준 -5% 이내 또는 위
  시가총액 500억 이상
  관리종목·당일 등락률 15% 초과 제외

⚠️ TODO: HTS(영웅문) 조건검색기에서 아래 조건식 생성 후 COND_NM / COND_ID 입력 필요
  조건 내용:
    1. 5일이평 > 20일이평 (전일: 5일 ≤ 20일 — 크로스 당일)
    2. 당일거래량 / 20일평균거래량 ≥ 1.5
    3. RSI(14) 40 이상 AND RSI(14) 65 이하
    4. 현재가 ≥ 60일이평 × 0.95
    5. 시가총액 500억 이상
    6. 관리종목 제외 / 등락률 15% 초과 제외
"""

import logging
import os

import httpx

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

# TODO: HTS에서 조건식 생성 후 아래 두 값을 입력하세요 (ka10171 목록조회로 확인 가능)
COND_NM = "TODO_골든크로스_스윙"   # HTS 조건식명
COND_ID = "TODO_COND_ID"          # ka10171 응답의 cond_id


async def fetch_condition_stocks(token: str) -> list[str]:
    """ka10172 조건검색 요청 일반 – 골든크로스 조건 부합 종목 리스트"""
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
        # 응답: {"stk_cd": ["005930", ...], "count": "N"}
        raw = data.get("stk_cd", [])
        if isinstance(raw, list):
            return [s for s in raw if isinstance(s, str)]
        return []


async def scan_golden_cross(token: str, rdb=None) -> list:
    """골든크로스 스윙 전략 스캔"""
    if COND_NM.startswith("TODO") or COND_ID.startswith("TODO"):
        logger.warning("[S8] HTS 조건식 미등록. COND_NM / COND_ID를 설정하세요.")
        return []

    candidates = await fetch_condition_stocks(token)
    if not candidates:
        logger.info("[S8] 조건검색 결과 없음")
        return []

    results = []
    for stk_cd in candidates[:20]:  # 최대 20종목 처리
        # Redis 실시간 데이터 조회
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

        # 당일 급등 노이즈 제거 (15% 초과)
        if flu_rt > 15.0:
            continue

        # 체결강도 확인 (보조 지표)
        try:
            cntr_str = float(tick.get("cntr_str", 100))
        except (TypeError, ValueError):
            cntr_str = 100.0

        score = flu_rt * 0.3 + max(cntr_str - 100, 0) * 0.2
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S8_GOLDEN_CROSS",
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "3~7거래일",
            "target_pct": 8.0,
            "stop_pct": -4.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
