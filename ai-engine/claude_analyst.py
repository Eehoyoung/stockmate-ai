"""
claude_analyst.py
/claude {code} 텔레그램 명령어 전용 종목 분석 모듈.

흐름:
  1. Redis 후보 풀에서 해당 종목이 어떤 전략으로 감지되었는지 확인
  2. Redis tick data + 일봉 가져와 기술지표 계산
  3. Claude API 에 종합 프롬프트 전송 → 자유 형식 한국어 분석 수신
  4. 결과 dict 반환 (engine.py HTTP 엔드포인트에서 JSON 응답)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import anthropic
import httpx

from http_utils import validate_kiwoom_response
from ma_utils import fetch_daily_candles, _safe_price, _safe_vol

logger = logging.getLogger(__name__)

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
_TIMEOUT        = 10.0

# 전략 코드 → 한국어 이름
_STRATEGY_NAMES: dict[str, str] = {
    "s1":  "S1 갭 상승 개장",
    "s2":  "S2 VI 눌림목",
    "s3":  "S3 기관·외인 매수",
    "s4":  "S4 장대양봉",
    "s5":  "S5 프로그램 매수",
    "s6":  "S6 테마 상승",
    "s7":  "S7 동시호가",
    "s8":  "S8 골든크로스",
    "s9":  "S9 눌림목 반등",
    "s10": "S10 신고가 돌파",
    "s11": "S11 외인 지속 매수",
    "s12": "S12 종가 강도",
    "s13": "S13 박스권 돌파",
    "s14": "S14 과매도 반등",
    "s15": "S15 모멘텀 정렬",
}

# Claude 클라이언트 싱글턴
_claude_client: anthropic.AsyncAnthropic | None = None

def _get_client() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise RuntimeError("CLAUDE_API_KEY 환경 변수 미설정")
        _claude_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _claude_client


def _sf(v) -> float:
    """안전한 숫자 변환"""
    try:
        return float(str(v).replace(",", "").replace("+", "").replace(" ", "") or "0")
    except (ValueError, TypeError):
        return 0.0


async def _fetch_stk_nm(token: str, stk_cd: str, rdb) -> str:
    """종목명 조회 (Redis 캐시 우선)"""
    if rdb:
        try:
            cached = await rdb.get(f"stk_nm:{stk_cd}")
            if cached:
                return cached
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={"api-id": "ka10001", "authorization": f"Bearer {token}",
                         "Content-Type": "application/json;charset=UTF-8"},
                json={"stk_cd": stk_cd},
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10001", logger):
                return stk_cd
            items = data.get("stk_info", [])
            nm = str(items[0].get("stk_nm", "")).strip() if items else stk_cd
        if rdb and nm and nm != stk_cd:
            try:
                await rdb.set(f"stk_nm:{stk_cd}", nm, ex=86400)
            except Exception:
                pass
        return nm or stk_cd
    except Exception as e:
        logger.debug("[claude_analyst] 종목명 조회 실패 [%s]: %s", stk_cd, e)
        return stk_cd


def _calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(period):
        d = closes[i] - closes[i + 1]
        (gains if d > 0 else losses).append(abs(d))
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _calc_bollinger(closes: list[float], period: int = 20) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(upper, mid, lower) 볼린저밴드 반환"""
    if len(closes) < period:
        return None, None, None
    window = closes[:period]
    mid = sum(window) / period
    std = (sum((p - mid) ** 2 for p in window) / period) ** 0.5
    return round(mid + 2 * std, 0), round(mid, 0), round(mid - 2 * std, 0)


async def _check_candidate_pools(rdb, stk_cd: str) -> list[str]:
    """
    Redis 후보 풀에서 해당 종목이 등록된 전략 목록을 반환.
    candidates:s{N}:{market} 키를 전수 확인.
    """
    found: list[str] = []
    markets = ["001", "101"]
    for n in range(1, 16):
        s = f"s{n}"
        for mkt in markets:
            key = f"candidates:{s}:{mkt}"
            try:
                members = await rdb.lrange(key, 0, -1)
                if stk_cd in members:
                    found.append(_STRATEGY_NAMES.get(s, s))
            except Exception:
                pass
    return found


async def analyze_stock_for_user(rdb, stk_cd: str) -> dict:
    """
    종목 종합 분석 — /claude {code} 명령어 전용.
    Returns:
        {
          "stk_cd": str,
          "stk_nm": str,
          "strategies_in_pool": [str, ...],
          "cur_prc": float,
          "flu_rt": float,
          "ma5": float | None,
          "ma20": float | None,
          "ma60": float | None,
          "rsi14": float | None,
          "bb_upper": float | None,
          "bb_lower": float | None,
          "claude_analysis": str,
          "error": str | None,
        }
    """
    result: dict = {"stk_cd": stk_cd, "error": None}

    # 0. 키움 토큰
    token = ""
    try:
        token = (await rdb.get("kiwoom:token")) or ""
    except Exception as e:
        logger.warning("[claude_analyst] 토큰 조회 실패: %s", e)

    # 1. 종목명
    stk_nm = stk_cd
    if token:
        stk_nm = await _fetch_stk_nm(token, stk_cd, rdb)
    result["stk_nm"] = stk_nm

    # 2. 후보 풀 전략 목록
    strategies_in_pool = await _check_candidate_pools(rdb, stk_cd)
    result["strategies_in_pool"] = strategies_in_pool

    # 3. Redis tick data
    cur_prc = 0.0
    flu_rt  = 0.0
    cntr_str = 0.0
    acc_vol  = 0
    try:
        tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
        if tick:
            cur_prc  = _sf(tick.get("cur_prc", 0))
            flu_rt   = _sf(tick.get("flu_rt", 0))
            cntr_str = _sf(tick.get("cntr_str", 0))
            acc_vol  = int(_sf(tick.get("acc_trde_qty", 0)))
    except Exception as e:
        logger.debug("[claude_analyst] tick 조회 실패 [%s]: %s", stk_cd, e)
    result["cur_prc"]  = cur_prc
    result["flu_rt"]   = flu_rt
    result["cntr_str"] = cntr_str
    result["acc_vol"]  = acc_vol

    # 4. 일봉 + 기술지표
    candles: list[dict] = []
    ma5 = ma20 = ma60 = rsi14 = None
    bb_upper = bb_mid = bb_lower = None
    vol_ma20 = None
    recent_high = recent_low = None

    if token:
        try:
            candles = await asyncio.wait_for(
                fetch_daily_candles(token, stk_cd, target_count=120), timeout=15.0
            )
        except Exception as e:
            logger.warning("[claude_analyst] 일봉 조회 실패 [%s]: %s", stk_cd, e)

    if candles:
        closes = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles[:20]]
        highs  = [_safe_price(c.get("high_pric")) for c in candles[:20] if _safe_price(c.get("high_pric")) > 0]
        lows   = [_safe_price(c.get("low_pric")) for c in candles[:20] if _safe_price(c.get("low_pric")) > 0]

        if closes:
            if cur_prc == 0:
                cur_prc = closes[0]
                result["cur_prc"] = cur_prc

            if len(closes) >= 5:
                ma5 = round(sum(closes[:5]) / 5, 0)
            if len(closes) >= 20:
                ma20    = round(sum(closes[:20]) / 20, 0)
                vol_ma20 = round(sum(vols[:20]) / 20, 0) if vols else None
            if len(closes) >= 60:
                ma60 = round(sum(closes[:60]) / 60, 0)

            rsi14 = _calc_rsi(closes)
            bb_upper, bb_mid, bb_lower = _calc_bollinger(closes)

        if highs:
            recent_high = round(max(highs), 0)
        if lows:
            recent_low  = round(min(lows), 0)

    result.update({
        "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "rsi14": rsi14,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
        "vol_ma20": vol_ma20,
        "recent_high_20d": recent_high,
        "recent_low_20d":  recent_low,
    })

    # 5. Claude API 호출
    try:
        analysis = await asyncio.wait_for(
            _call_claude(stk_cd, stk_nm, result), timeout=30.0
        )
        result["claude_analysis"] = analysis
    except asyncio.TimeoutError:
        result["claude_analysis"] = "Claude 응답 타임아웃 (30초 초과)"
        result["error"] = "timeout"
    except Exception as e:
        logger.error("[claude_analyst] Claude 호출 실패 [%s]: %s", stk_cd, e)
        result["claude_analysis"] = f"Claude 분석 실패: {e}"
        result["error"] = str(e)

    return result


async def _call_claude(stk_cd: str, stk_nm: str, ctx: dict) -> str:
    """Claude API 호출 — 자유 형식 한국어 분석 텍스트 반환"""

    cur_prc  = ctx.get("cur_prc", 0)
    flu_rt   = ctx.get("flu_rt", 0)
    ma5      = ctx.get("ma5")
    ma20     = ctx.get("ma20")
    ma60     = ctx.get("ma60")
    rsi14    = ctx.get("rsi14")
    bb_upper = ctx.get("bb_upper")
    bb_mid   = ctx.get("bb_mid")
    bb_lower = ctx.get("bb_lower")
    vol_ma20 = ctx.get("vol_ma20")
    acc_vol  = ctx.get("acc_vol", 0)
    cntr_str = ctx.get("cntr_str", 0)
    pool_strategies = ctx.get("strategies_in_pool", [])
    recent_high = ctx.get("recent_high_20d")
    recent_low  = ctx.get("recent_low_20d")

    # MA 배열 판단
    alignment = "데이터 부족"
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            alignment = "정배열 (MA5 > MA20 > MA60) ✅"
        elif ma5 < ma20 < ma60:
            alignment = "역배열 (MA5 < MA20 < MA60) ❌"
        else:
            alignment = "혼조 배열"

    # RSI 상태
    rsi_status = "N/A"
    if rsi14 is not None:
        if rsi14 >= 70:
            rsi_status = f"{rsi14} (과매수 구간 ⚠️)"
        elif rsi14 <= 30:
            rsi_status = f"{rsi14} (과매도 구간 🔻)"
        else:
            rsi_status = f"{rsi14} (중립)"

    # Bollinger 위치
    bb_position = "N/A"
    if bb_upper and bb_lower and cur_prc:
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            pct_b = (cur_prc - bb_lower) / bb_range * 100
            if pct_b >= 80:
                bb_position = f"%B={pct_b:.0f}% (상단 근접 ⚠️)"
            elif pct_b <= 20:
                bb_position = f"%B={pct_b:.0f}% (하단 근접 💡)"
            else:
                bb_position = f"%B={pct_b:.0f}%"

    # 거래량 비교
    vol_comment = "N/A"
    if vol_ma20 and acc_vol:
        ratio = acc_vol / vol_ma20 if vol_ma20 > 0 else 0
        vol_comment = f"오늘 {acc_vol:,}주 / 20일 평균 {vol_ma20:,.0f}주 (비율 {ratio:.1f}x)"

    pool_str = "\n".join(f"  - {s}" for s in pool_strategies) if pool_strategies else "  - (현재 후보 풀에 없음)"

    prompt = f"""
당신은 한국 주식 전문 트레이더 겸 기술적 분석가입니다.
아래 데이터를 바탕으로 종목 {stk_nm}({stk_cd})에 대한 **종합 분석 보고서**를 작성하세요.

## 시스템이 감지한 전략 후보 풀
{pool_str}

## 현재 시세
- 현재가: {cur_prc:,.0f}원
- 등락률: {flu_rt:+.2f}%
- 체결강도: {cntr_str:.1f}

## 이동평균선 (일봉 기준)
- MA5  : {f"{ma5:,.0f}원" if ma5 else "N/A"}
- MA20 : {f"{ma20:,.0f}원" if ma20 else "N/A"}
- MA60 : {f"{ma60:,.0f}원" if ma60 else "N/A"}
- 정배열 여부: {alignment}

## 기술지표
- RSI(14): {rsi_status}
- 볼린저밴드: 상단 {f"{bb_upper:,.0f}" if bb_upper else "N/A"} / 중단 {f"{bb_mid:,.0f}" if bb_mid else "N/A"} / 하단 {f"{bb_lower:,.0f}" if bb_lower else "N/A"}
- 볼린저 위치: {bb_position}

## 최근 20일 가격 범위
- 20일 고가: {f"{recent_high:,.0f}원" if recent_high else "N/A"}
- 20일 저가: {f"{recent_low:,.0f}원" if recent_low else "N/A"}

## 거래량
- {vol_comment}

---

다음 항목을 포함한 분석 보고서를 **한국어**로 작성하세요:

1. **종합 의견** (매수 적합 / 중립 / 주의 중 하나 + 근거 2~3줄)
2. **현재 기술적 상태** (MA 배열, RSI, 볼린저 기반)
3. **주목할 리스크** (과매수, 지지선 붕괴 가능성 등)
4. **매수 시나리오** (어떤 조건이 되면 진입 가능한지)
5. **TP / SL 제안** (기술적 근거 포함)

마지막에 한 줄 요약: ⭐ 결론: [한 문장]
""".strip()

    client = _get_client()
    resp = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text
