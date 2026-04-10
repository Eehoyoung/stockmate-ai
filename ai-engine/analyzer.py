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

CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS      = 512   # TP/SL 절대가 출력을 위한 공간 확보
CLAUDE_TIMEOUT  = 10    # seconds

# 수수료+세금+슬리피지 합산 (왕복 기준, KOSPI 0.35%, KOSDAQ 0.45%)
SLIP_FEE = {"KOSPI": 0.0035, "KOSDAQ": 0.0045}


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
        "진입 불가 판단 시 claude_tp1/tp2/sl은 null로 반환하세요: "
        '{"action":"ENTER|HOLD|CANCEL","ai_score":0~100,"confidence":"HIGH|MEDIUM|LOW",'
        '"reason":"2문장 이내","adjusted_target_pct":null,"adjusted_stop_pct":null,'
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


# 전략별 압축 프롬프트 생성기
def _build_user_message(signal: dict, market_ctx: dict, rule_score: float) -> str:
    strategy = signal.get("strategy", "")
    stk_cd   = signal.get("stk_cd", "")
    stk_nm   = signal.get("stk_nm", "")
    tick     = market_ctx.get("tick", {})
    hoga     = market_ctx.get("hoga", {})
    strength = market_ctx.get("strength", 0)
    flu_rt   = tick.get("flu_rt", "N/A")

    bid  = hoga.get("total_buy_bid_req", "0")
    ask  = hoga.get("total_sel_bid_req", "1")
    try:
        bid_ratio = round(float(str(bid).replace(",", "")) /
                          max(float(str(ask).replace(",", "")), 1), 2)
    except Exception:
        bid_ratio = 0

    tpsl_ctx = _fmt_tpsl(signal)

    if strategy == "S1_GAP_OPEN":
        return (
            f"갭상승 매수 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 갭: {signal.get('gap_pct', 'N/A')}%, "
            f"호가비율: {bid_ratio}, 체결강도: {round(strength, 1)}, 등락: {flu_rt}%, "
            f"규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"매수 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S2_VI_PULLBACK":
        return (
            f"VI 눌림목 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 눌림: {signal.get('pullback_pct', 'N/A')}%, "
            f"동적VI: {signal.get('is_dynamic', False)}, 체결강도: {round(strength, 1)}, "
            f"규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S3_INST_FRGN":
        amt = signal.get("net_buy_amt", 0)
        amt_str = f"{int(amt) // 100_000_000}억" if amt else "N/A"
        return (
            f"외인+기관 순매수 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 순매수: {amt_str}, "
            f"연속일: {signal.get('continuous_days', 'N/A')}일, "
            f"거래량비율: {signal.get('vol_ratio', 'N/A')}x, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S4_BIG_CANDLE":
        return (
            f"장대양봉 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 양봉비율: {signal.get('body_ratio', 'N/A')}, "
            f"거래량비율: {signal.get('vol_ratio', 'N/A')}배, "
            f"신고가: {signal.get('is_new_high', False)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"추가 상승 가능성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S5_PROG_FRGN":
        amt = signal.get("net_buy_amt", 0)
        amt_str = f"{int(amt) // 100_000_000}억" if amt else "N/A"
        return (
            f"프로그램+외인 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 순매수: {amt_str}, "
            f"체결강도: {round(strength, 1)}, 호가비율: {bid_ratio}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S6_THEME_LAGGARD":
        return (
            f"테마 후발주 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 테마: {signal.get('theme_name', 'N/A')}, "
            f"등락: {signal.get('gap_pct', 'N/A')}%, 체결강도: {round(strength, 1)}, "
            f"호가비율: {bid_ratio}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"후발주 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S7_AUCTION":
        return (
            f"동시호가 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 갭: {signal.get('gap_pct', 'N/A')}%, "
            f"호가비율: {bid_ratio}, 거래량순위: {signal.get('vol_rank', 'N/A')}, "
            f"규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"시초가 매수 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S8_GOLDEN_CROSS":
        return (
            f"골든크로스 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), MA5≥MA20 크로스, 등락: {flu_rt}%, "
            f"RSI: {signal.get('rsi', 'N/A')}, 거래량비율: {signal.get('vol_ratio', 'N/A')}x, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S9_PULLBACK_SWING":
        return (
            f"정배열 눌림목 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), MA5 근접 눌림 반등, 등락: {flu_rt}%, "
            f"RSI: {signal.get('rsi', 'N/A')}, 거래량비율: {signal.get('vol_ratio', 'N/A')}x, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S10_NEW_HIGH":
        return (
            f"52주 신고가 돌파 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 등락: {flu_rt}%, "
            f"거래량급증률: {signal.get('vol_surge_rt', 'N/A')}%, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"신고가 돌파 후 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S11_FRGN_CONT":
        return (
            f"외국인 연속 순매수 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 등락: {flu_rt}%, "
            f"D-1순매수: {signal.get('dm1', 'N/A')}, D-2: {signal.get('dm2', 'N/A')}, D-3: {signal.get('dm3', 'N/A')}, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"외국인 수급 기반 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S12_CLOSING":
        return (
            f"종가 강도 확인 매수 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 등락: {flu_rt}%, "
            f"체결강도: {signal.get('cntr_strength', round(strength, 1))}, "
            f"호가비율: {bid_ratio}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"종가 매수 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S13_BOX_BREAKOUT":
        return (
            f"박스권 돌파 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 거래량폭발 돌파, 등락: {flu_rt}%, "
            f"거래량비율: {signal.get('vol_ratio', 'N/A')}x, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"박스권 돌파 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S14_OVERSOLD_BOUNCE":
        return (
            f"과매도 반등 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), RSI: {signal.get('rsi', 'N/A')}(과매도), "
            f"ATR%: {signal.get('atr_pct', 'N/A')}, 조건충족: {signal.get('cond_count', 'N/A')}/3, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"과매도 반등 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    elif strategy == "S15_MOMENTUM_ALIGN":
        return (
            f"다중지표 모멘텀 동조 스윙 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), RSI: {signal.get('rsi', 'N/A')}, "
            f"ATR%: {signal.get('atr_pct', 'N/A')}, 조건충족: {signal.get('cond_count', 'N/A')}/4, "
            f"거래량비율: {signal.get('vol_ratio', 'N/A')}x, "
            f"체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
            f"{tpsl_ctx}"
            f"모멘텀 동조 스윙 진입 적합성과 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."
        )
    else:
        return (
            f"매매 신호 평가:\n"
            f"종목: {stk_nm}({stk_cd}), 전략: {strategy}, "
            f"등락: {flu_rt}%, 체결강도: {round(strength, 1)}, 규칙점수: {rule_score}/100\n"
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
           "adjusted_target_pct": ..., "adjusted_stop_pct": ...}
    """
    # ── R:R 사전 필터 (Claude API 호출 전) ──────────────────────
    # tp_sl_engine이 계산한 rr_ratio (슬리피지 반영 실효값) 기준
    rr_ratio = signal.get("rr_ratio")
    if isinstance(rr_ratio, (int, float)) and rr_ratio < 1.0:
        logger.info(
            "[Analyzer] R:R %.2f < 1.0 → pre-filter CANCEL [%s %s]",
            rr_ratio, signal.get("stk_cd"), signal.get("strategy"),
        )
        return {
            "action":              "CANCEL",
            "ai_score":            round(rule_score * 0.5, 1),  # 페널티 반영
            "confidence":          "HIGH",
            "reason":              f"R:R {rr_ratio:.2f} < 1.0 — 슬리피지 반영 후 손익비 미달, Claude 호출 생략",
            "adjusted_target_pct": None,
            "adjusted_stop_pct":   None,
        }

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
        result = json.loads(raw_text)
        logger.info(
            json.dumps({
                "ts": __import__("time").time(),
                "module": "analyzer",
                "strategy": signal.get("strategy"),
                "stk_cd": signal.get("stk_cd"),
                "action": result.get("action"),
                "ai_score": result.get("ai_score"),
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
        "adjusted_target_pct": None,
        "adjusted_stop_pct":   None,
    }
