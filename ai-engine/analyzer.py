from __future__ import annotations
"""
analyzer.py
Claude API 를 호출하여 거래 신호를 최종 분석·판단하는 모듈.
전략별 압축 프롬프트 사용으로 토큰 비용 절감.
"""

import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS      = 512   # TP/SL 절대가 출력을 위한 공간 확보
CLAUDE_TIMEOUT  = 10    # seconds

# 수수료+세금+슬리피지 합산 (왕복 기준, KOSPI 0.35%, KOSDAQ 0.45%)
SLIP_FEE = {"KOSPI": 0.0035, "KOSDAQ": 0.0035}


def _get_slip_fee(stk_cd: str) -> float:
    """종목코드 첫 자리로 시장 구분 후 슬리피지 비율 반환 (KOSPI: 0, KOSDAQ: 기타)"""
    return SLIP_FEE["KOSPI"] if str(stk_cd).startswith("0") else SLIP_FEE["KOSDAQ"]

# Claude 클라이언트 싱글턴 (모듈 로드 시 생성, 매 호출 시 재생성 방지)
_claude_client: anthropic.AsyncAnthropic | None = None

def _get_claude_client() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise RuntimeError("CLAUDE_API_KEY 환경 변수 미설정")
        _claude_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _claude_client

# 시스템 프롬프트 (공통)
_PROMPT_DIR = Path(__file__).parent / "prompts"
try:
    _SYS_PROMPT = (_PROMPT_DIR / "signal_analysis.txt").read_text(encoding="utf-8")
except Exception:
    _SYS_PROMPT = (
        "당신은 한국 주식 단기 매매 신호 분석 전문가입니다. "
        "주어진 지표와 규칙 기반 TP/SL을 참고하여 최종 TP1/TP2/SL을 결정하고 "
        "JSON 형식으로만 답하세요. "
        "claude_tp1/tp2/sl은 절대 원화 가격(정수)으로 반환하세요. "
        "action이 CANCEL이면 cancel_reason을 짧은 한국어 문자열로 반드시 채우고, "
        "ENTER/HOLD이면 cancel_reason은 null로 반환하세요. "
        "진입 불가 판단 시 claude_tp1/tp2/sl은 null로 반환하세요: "
        '{"action":"ENTER|HOLD|CANCEL","ai_score":0~100,"confidence":"HIGH|MEDIUM|LOW",'
        '"reason":"2문장 이내","cancel_reason":null,"adjusted_target_pct":null,"adjusted_stop_pct":null,'
        '"claude_tp1":null,"claude_tp2":null,"claude_sl":null}'
    )


def _fmt_tpsl(signal: dict) -> str:
    """규칙 기반 TP/SL 컨텍스트 + 실질 R:R(슬리피지 반영) 문자열 생성"""
    entry = signal.get("cur_prc") or signal.get("entry_price") or 0
    tp1   = signal.get("tp1_price")
    tp2   = signal.get("tp2_price")
    sl    = signal.get("sl_price")
    if not any([tp1, tp2, sl]):
        return ""
    parts = []
    if entry:
        parts.append(f"진입가:{int(entry):,}원")
    if tp1:
        pct = f"(+{(tp1-entry)/entry*100:.1f}%)" if entry else ""
        parts.append(f"규칙TP1:{int(tp1):,}원{pct}")
    if tp2:
        pct = f"(+{(tp2-entry)/entry*100:.1f}%)" if entry else ""
        parts.append(f"규칙TP2:{int(tp2):,}원{pct}")
    if sl:
        pct = f"({(sl-entry)/entry*100:.1f}%)" if entry else ""
        parts.append(f"규칙SL:{int(sl):,}원{pct}")

    # 실질 R:R 계산 (슬리피지 반영)
    if entry and tp1 and sl:
        slip = _get_slip_fee(signal.get("stk_cd", ""))
        raw_target = (tp1 - entry) / entry
        raw_risk   = (entry - sl)  / entry
        eff_target = raw_target - slip
        eff_risk   = raw_risk   + slip
        if eff_risk > 0:
            eff_rr = eff_target / eff_risk
            parts.append(f"실질R:R={eff_rr:.2f}({'⚠️' if eff_rr < 1.0 else 'OK'})")

    return " | ".join(parts) + "\n" if parts else ""


# ── 전략별 프롬프트 생성 헬퍼 ────────────────────────────────────
# 각 함수는 (signal, c) 를 받아 header + body 문자열을 반환.
# c = {"stk_cd", "stk_nm", "flu_rt", "strength", "bid_ratio", "rule_score", "tpsl_ctx"}
# 공통 후행 문구는 호출처(_build_user_message)에서 추가.

def _s1_body(sig, c) -> str:
    return (
        f"갭상승 매수 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 갭: {sig.get('gap_pct', 'N/A')}%, "
        f"호가비율: {c['bid_ratio']}, 체결강도: {c['strength']}, 등락: {c['flu_rt']}%, "
        f"규칙점수: {c['rule_score']}/100\n"
    )

def _s2_body(sig, c) -> str:
    return (
        f"VI 눌림목 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 눌림: {sig.get('pullback_pct', 'N/A')}%, "
        f"동적VI: {sig.get('is_dynamic', False)}, 체결강도: {c['strength']}, "
        f"규칙점수: {c['rule_score']}/100\n"
    )

def _s3_body(sig, c) -> str:
    amt = sig.get("net_buy_amt", 0)
    amt_str = f"{int(amt) // 100_000_000}억" if amt else "N/A"
    return (
        f"외인+기관 순매수 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 순매수: {amt_str}, "
        f"연속일: {sig.get('continuous_days', 'N/A')}일, "
        f"거래량비율: {sig.get('vol_ratio', 'N/A')}x, 규칙점수: {c['rule_score']}/100\n"
    )

def _s4_body(sig, c) -> str:
    return (
        f"장대양봉 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 양봉비율: {sig.get('body_ratio', 'N/A')}, "
        f"거래량비율: {sig.get('vol_ratio', 'N/A')}배, "
        f"신고가: {sig.get('is_new_high', False)}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s5_body(sig, c) -> str:
    amt = sig.get("net_buy_amt", 0)
    amt_str = f"{int(amt) // 100_000_000}억" if amt else "N/A"
    return (
        f"프로그램+외인 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 순매수: {amt_str}, "
        f"체결강도: {c['strength']}, 호가비율: {c['bid_ratio']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s6_body(sig, c) -> str:
    return (
        f"테마 후발주 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 테마: {sig.get('theme_name', 'N/A')}, "
        f"등락: {sig.get('gap_pct', 'N/A')}%, 체결강도: {c['strength']}, "
        f"호가비율: {c['bid_ratio']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s7_body(sig, c) -> str:
    return (
        f"일목균형표 구름대 돌파 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 구름 두께: {sig.get('cloud_thickness_pct', 'N/A')}%, "
        f"후행스팬 상방: {sig.get('chikou_above', 'N/A')}, 거래량 배수: {sig.get('vol_ratio', 'N/A')}x, "
        f"RSI: {sig.get('rsi', 'N/A')}, 조건 충족: {sig.get('cond_count', 'N/A')}, "
        f"규칙점수: {c['rule_score']}/100\n"
    )

def _s8_body(sig, c) -> str:
    return (
        f"골든크로스 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), MA5≥MA20 크로스, 등락: {c['flu_rt']}%, "
        f"RSI: {sig.get('rsi', 'N/A')}, 거래량비율: {sig.get('vol_ratio', 'N/A')}x, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s9_body(sig, c) -> str:
    return (
        f"정배열 눌림목 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), MA5 근접 눌림 반등, 등락: {c['flu_rt']}%, "
        f"RSI: {sig.get('rsi', 'N/A')}, 거래량비율: {sig.get('vol_ratio', 'N/A')}x, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s10_body(sig, c) -> str:
    return (
        f"52주 신고가 돌파 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 등락: {c['flu_rt']}%, "
        f"거래량급증률: {sig.get('vol_surge_rt', 'N/A')}%, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s11_body(sig, c) -> str:
    return (
        f"외국인 연속 순매수 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 등락: {c['flu_rt']}%, "
        f"D-1순매수: {sig.get('dm1', 'N/A')}, D-2: {sig.get('dm2', 'N/A')}, D-3: {sig.get('dm3', 'N/A')}, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s12_body(sig, c) -> str:
    return (
        f"종가 강도 확인 매수 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 등락: {c['flu_rt']}%, "
        f"체결강도: {sig.get('cntr_strength', c['strength'])}, "
        f"호가비율: {c['bid_ratio']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s13_body(sig, c) -> str:
    return (
        f"박스권 돌파 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 거래량폭발 돌파, 등락: {c['flu_rt']}%, "
        f"거래량비율: {sig.get('vol_ratio', 'N/A')}x, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s14_body(sig, c) -> str:
    return (
        f"과매도 반등 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), RSI: {sig.get('rsi', 'N/A')}(과매도), "
        f"ATR%: {sig.get('atr_pct', 'N/A')}, 조건충족: {sig.get('cond_count', 'N/A')}/3, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

def _s15_body(sig, c) -> str:
    return (
        f"다중지표 모멘텀 동조 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), RSI: {sig.get('rsi', 'N/A')}, "
        f"ATR%: {sig.get('atr_pct', 'N/A')}, 조건충족: {sig.get('cond_count', 'N/A')}/4, "
        f"거래량비율: {sig.get('vol_ratio', 'N/A')}x, "
        f"체결강도: {c['strength']}, 규칙점수: {c['rule_score']}/100\n"
    )

# 전략코드 → (body_fn, 질문 문구)
_STRATEGY_TEMPLATES: dict[str, tuple[callable, str]] = {
    "S1_GAP_OPEN":       (_s1_body,  "매수 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S2_VI_PULLBACK":    (_s2_body,  "진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S3_INST_FRGN":      (_s3_body,  "진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S4_BIG_CANDLE":     (_s4_body,  "추가 상승 가능성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S5_PROG_FRGN":      (_s5_body,  "진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S6_THEME_LAGGARD":  (_s6_body,  "후발주 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S7_ICHIMOKU_BREAKOUT":        (_s7_body,  "일목균형표 돌파 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S8_GOLDEN_CROSS":   (_s8_body,  "스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S9_PULLBACK_SWING": (_s9_body,  "스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S10_NEW_HIGH":      (_s10_body, "신고가 돌파 후 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S11_FRGN_CONT":     (_s11_body, "외국인 수급 기반 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S12_CLOSING":       (_s12_body, "종가 매수 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S13_BOX_BREAKOUT":  (_s13_body, "박스권 돌파 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S14_OVERSOLD_BOUNCE": (_s14_body, "과매도 반등 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
    "S15_MOMENTUM_ALIGN":  (_s15_body, "모멘텀 동조 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
}


# 전략별 압축 프롬프트 생성기
def _build_user_message(signal: dict, market_ctx: dict, rule_score: float) -> str:
    strategy = signal.get("strategy", "")
    tick     = market_ctx.get("tick", {})
    hoga     = market_ctx.get("hoga", {})
    signal_strength = signal.get("cntr_strength", signal.get("cntr_str"))
    try:
        strength = float(signal_strength) if signal_strength is not None else float(market_ctx.get("strength", 0) or 0)
    except (TypeError, ValueError):
        strength = market_ctx.get("strength", 0)

    bid  = hoga.get("total_buy_bid_req", "0")
    ask  = hoga.get("total_sel_bid_req", "1")
    try:
        bid_ratio = round(float(str(bid).replace(",", "")) /
                          max(float(str(ask).replace(",", "")), 1), 2)
    except Exception:
        bid_ratio = 0

    # 공통 컨텍스트 – 각 body 함수에 전달
    ctx = {
        "stk_cd":    signal.get("stk_cd", ""),
        "stk_nm":    signal.get("stk_nm", ""),
        "flu_rt":    tick.get("flu_rt", "N/A"),
        "strength":  round(strength, 1),
        "bid_ratio": bid_ratio,
        "rule_score": rule_score,
    }
    tpsl_ctx = _fmt_tpsl(signal)

    tpl = _STRATEGY_TEMPLATES.get(strategy)
    if tpl:
        body_fn, question = tpl
        return body_fn(signal, ctx) + tpsl_ctx + question

    # 미등록 전략 – 범용 폴백
    return (
        f"매매 신호 평가:\n"
        f"종목: {ctx['stk_nm']}({ctx['stk_cd']}), 전략: {strategy}, "
        f"등락: {ctx['flu_rt']}%, 체결강도: {ctx['strength']}, 규칙점수: {rule_score}/100\n"
        f"{tpsl_ctx}"
        f"진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
    )


async def _track_api_usage(rdb, input_tokens: int = 0, output_tokens: int = 0):
    """
    Claude API 호출 후 일별 사용량을 Redis에 기록.
    claude:daily_calls:{YYYYMMDD}  – 호출 횟수 (scorer.py check_daily_limit 과 공유)
    claude:daily_tokens:{YYYYMMDD} – 입력+출력 토큰 합계
    """
    if rdb is None:
        return
    today_str = date.today().strftime("%Y%m%d")
    try:
        # 호출 횟수 증분 (check_daily_limit 과 동일 키 – 이미 증분된 경우 중복 방지를 위해
        # scorer.py check_daily_limit 에서 1차 증분하므로 여기서는 토큰만 추적)
        token_key = f"claude:daily_tokens:{today_str}"
        total = input_tokens + output_tokens
        if total > 0:
            cnt = await rdb.incrby(token_key, total)
            if cnt <= total:  # 첫 기록
                await rdb.expire(token_key, 86400)
    except Exception as e:
        logger.debug("[Analyzer] API 사용량 기록 실패 (무시): %s", e)


async def analyze_signal(signal: dict, market_ctx: dict, rule_score: float,
                         rdb=None) -> dict:
    """
    Claude API 호출로 신호 최종 분석.
    타임아웃(10s) 또는 오류 시 규칙 스코어 폴백.
    rdb: Redis 클라이언트 (토큰 사용량 추적용, 선택)
    반환: {"action": ..., "ai_score": ..., "confidence": ..., "reason": ...,
           "cancel_reason": ..., "adjusted_target_pct": ..., "adjusted_stop_pct": ...}
    """
    client       = _get_claude_client()
    user_message = _build_user_message(signal, market_ctx, rule_score)

    raw_text = ""
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model      = CLAUDE_MODEL,
                max_tokens = MAX_TOKENS,
                system     = _SYS_PROMPT,
                messages   = [{"role": "user", "content": user_message}],
            ),
            timeout=CLAUDE_TIMEOUT,
        )
        raw_text = response.content[0].text.strip()

        # 토큰 사용량 추적 (usage 속성이 있는 경우)
        try:
            usage = response.usage
            await _track_api_usage(
                rdb,
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
            )
        except Exception:
            pass

        # JSON 파싱 – Claude 가 JSON 앞뒤에 텍스트를 추가하는 경우 중괄호 범위 추출
        json_start = raw_text.find("{")
        json_end   = raw_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            raw_text = raw_text[json_start:json_end]
        result = _normalize_signal_result(json.loads(raw_text))
        logger.info(
            json.dumps({
                "ts": __import__("time").time(),
                "module": "analyzer",
                "strategy": signal.get("strategy"),
                "stk_cd": signal.get("stk_cd"),
                "action": result.get("action"),
                "ai_score": result.get("ai_score"),
                "cancel_reason": result.get("cancel_reason"),
            })
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("[AI] Claude 타임아웃 (%ds) [%s %s] – 규칙 폴백",
                       CLAUDE_TIMEOUT, signal.get("stk_cd"), signal.get("strategy"))
        return _fallback(rule_score)
    except json.JSONDecodeError as e:
        logger.error("[AI] JSON 파싱 실패: %s / raw=%.200s", e, raw_text)
        return _fallback(rule_score)
    except anthropic.APIError as e:
        logger.warning("[AI] Claude API 오류: %s – 규칙 폴백", e)
        return _fallback(rule_score)
    except Exception as e:
        logger.warning("[AI] 예기치 않은 오류: %s – 규칙 폴백", e)
        return _fallback(rule_score)


def _fallback(rule_score: float) -> dict:
    """Claude API 실패 시 규칙 스코어 기반 폴백"""
    action = "ENTER" if rule_score >= 70 else ("HOLD" if rule_score >= 50 else "CANCEL")
    return {
        "action":              action,
        "ai_score":            rule_score,
        "confidence":          "LOW",
        "reason":              "AI 분석 실패 – 규칙 스코어 기반 폴백 적용",
        "cancel_reason":       "AI 분석 실패" if action == "CANCEL" else None,
        "adjusted_target_pct": None,
        "adjusted_stop_pct":   None,
        "claude_tp1":          None,
        "claude_tp2":          None,
        "claude_sl":           None,
    }


def _normalize_signal_result(result: dict) -> dict:
    """Claude 신호 응답을 후속 파이프라인이 기대하는 형태로 정규화한다."""
    action = str(result.get("action") or "HOLD").upper()
    confidence = str(result.get("confidence") or "LOW").upper()
    reason = str(result.get("reason") or "").strip() or "AI 판단 근거 없음"

    raw_cancel_reason = result.get("cancel_reason")
    cancel_reason = None
    if raw_cancel_reason is not None:
        cancel_reason = str(raw_cancel_reason).strip() or None

    if action == "CANCEL" and not cancel_reason:
        cancel_reason = reason
    if action != "CANCEL":
        cancel_reason = None

    return {
        "action":              action,
        "ai_score":            result.get("ai_score"),
        "confidence":          confidence,
        "reason":              reason,
        "cancel_reason":       cancel_reason,
        "adjusted_target_pct": result.get("adjusted_target_pct"),
        "adjusted_stop_pct":   result.get("adjusted_stop_pct"),
        "claude_tp1":          result.get("claude_tp1"),
        "claude_tp2":          result.get("claude_tp2"),
        "claude_sl":           result.get("claude_sl"),
    }


# ──────────────────────────────────────────────────────────────
# 매도 판단 — position_monitor.py 에서 TREND_REVERSAL 후보에 호출
# ──────────────────────────────────────────────────────────────

_EXIT_SYS_PROMPT = (
    "당신은 한국 주식 포지션 청산 결정 전문가입니다. "
    "주어진 포지션 정보와 하락 지표를 분석하여 즉시 청산(exit=true) 또는 보유(exit=false)를 판단하세요. "
    "다음 조건 중 하나라도 해당하면 exit=true: "
    "(1) 현재가가 SL 기준 이하 또는 근접(-0.5% 이내) "
    "(2) 하락추세점수 >= 4 + 체결강도 < 85 + 호가 매도 우위 동시 충족 "
    "(3) 손익 -3% 초과 하락 + 강도 지속 약화 "
    "보유 조건: 일시적 눌림(추세 미훼손), 손익 양전(+1% 이상), 단기 반등 가능성 존재. "
    "추가 텍스트·마크다운 없이 JSON 한 줄로만 답하세요: "
    '{"exit":true|false,"confidence":"HIGH|MEDIUM|LOW","reason":"2문장 이내 판단근거"}'
)


async def analyze_exit(
    position: dict,
    reversal:  dict,
    rdb=None,
) -> dict:
    """
    TREND_REVERSAL 후보 포지션에 대해 Claude API 로 즉시 청산 여부 판단.

    Args:
        position: get_active_positions() 반환 행 (dict with id, stk_cd, strategy, entry_price, …)
        reversal: compute_reversal_score() 반환값 (score, components, details, cur_prc)
        rdb:      Redis 클라이언트 (토큰 추적용, optional)

    Returns:
        {"exit": bool, "confidence": str, "reason": str}
        오류/타임아웃 → {"exit": False, "confidence": "LOW", "reason": "AI 판단 실패"}
    """
    stk_cd     = position.get("stk_cd", "")
    strategy   = position.get("strategy", "")
    entry_prc  = position.get("entry_price", 0) or 0
    cur_prc    = reversal.get("cur_prc", 0) or 0
    sl_price   = position.get("sl_price", 0) or 0
    score      = reversal.get("score", 0)
    details    = reversal.get("details", {})

    pnl_pct = 0.0
    if entry_prc > 0 and cur_prc > 0:
        pnl_pct = (cur_prc - entry_prc) / entry_prc * 100.0

    user_msg = (
        f"포지션 청산 판단 요청:\n"
        f"종목: {stk_cd}  전략: {strategy}\n"
        f"진입가: {entry_prc:,}원  현재가: {cur_prc:,}원  손익: {pnl_pct:+.2f}%\n"
        f"SL기준: {sl_price:,}원\n"
        f"하락추세점수: {score}/5\n"
        f"  · 체결강도평균: {details.get('avg_strength', 'N/A')}\n"
        f"  · 호가매도비율: {details.get('hoga_ratio', 'N/A')}\n"
        f"  · 진입대비낙폭: {details.get('drop_pct', 'N/A')}%\n"
        f"  · 등락률: {details.get('flu_rt', 'N/A')}%\n"
        f"  · 체결강도하락추세: {details.get('strength_declining', False)}\n"
        f"위 데이터 기반으로 즉시 청산(exit=true)해야 하는지 JSON으로 답하세요."
    )

    client = _get_claude_client()
    raw_text = ""
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model      = CLAUDE_MODEL,
                max_tokens = 256,
                system     = _EXIT_SYS_PROMPT,
                messages   = [{"role": "user", "content": user_msg}],
            ),
            timeout=CLAUDE_TIMEOUT,
        )
        raw_text = response.content[0].text.strip()

        try:
            usage = response.usage
            await _track_api_usage(
                rdb,
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
            )
        except Exception:
            pass

        json_start = raw_text.find("{")
        json_end   = raw_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            raw_text = raw_text[json_start:json_end]
        result = json.loads(raw_text)
        logger.info(
            "[Analyzer] EXIT 판단 stk_cd=%s strategy=%s exit=%s confidence=%s",
            stk_cd, strategy, result.get("exit"), result.get("confidence"),
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("[Analyzer] analyze_exit 타임아웃 stk_cd=%s", stk_cd)
    except (json.JSONDecodeError, anthropic.APIError, Exception) as e:
        logger.warning("[Analyzer] analyze_exit 오류 stk_cd=%s: %s", stk_cd, e)

    return {"exit": False, "confidence": "LOW", "reason": "AI 청산 판단 실패 – 보유 유지"}
