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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import anthropic
from strategy_meta import get_persona
from strategy_meta import SWING_STRATEGIES as _TOSS_SWING_STRATEGIES
from strategy_catalog import ALL_SETUP_IDS, family_for_setup, family_live_routing_enabled
from toss_client import fetch_stock_risk_context as _toss_fetch_stock_risk_context

logger = logging.getLogger(__name__)
KST    = timezone(timedelta(hours=9))

CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS      = 512   # TP/SL 절대가 출력을 위한 공간 확보
CLAUDE_TIMEOUT  = float(os.getenv("CLAUDE_ANALYST_TIMEOUT_SEC", "30"))
ENABLE_STRATEGY_PERSONA_INJECTION = (
    os.getenv("ENABLE_STRATEGY_PERSONA_INJECTION", "true").lower() in {"1", "true", "yes", "on"}
)

# 수수료+세금+슬리피지 합산 (왕복 기준, KOSPI 0.35%, KOSDAQ 0.45%)
SLIP_FEE = {"KOSPI": 0.0035, "KOSDAQ": 0.0045}  # KOSDAQ: 거래세 0.15% 포함


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

_STRATEGY_PROMPT_FILES: dict[str, str] = {
    "S1_GAP_OPEN":          "signal_analysis_s1_gap_open.txt",
    "S2_VI_PULLBACK":       "signal_analysis_s2_vi_pullback.txt",
    "S3_INST_FRGN":         "signal_analysis_s3_inst_frgn.txt",
    "S4_BIG_CANDLE":        "signal_analysis_s4_big_candle.txt",
    "S5_PROG_FRGN":         "signal_analysis_s5_prog_frgn.txt",
    "S6_THEME_LAGGARD":     "signal_analysis_s6_theme_laggard.txt",
    "S7_ICHIMOKU_BREAKOUT": "signal_analysis_s7_ichimoku_breakout.txt",
    "S8_GOLDEN_CROSS":      "signal_analysis_s8_golden_cross.txt",
    "S9_PULLBACK_SWING":    "signal_analysis_s9_pullback_swing.txt",
    "S10_NEW_HIGH":         "signal_analysis_s10_new_high.txt",
    "S11_FRGN_CONT":        "signal_analysis_s11_frgn_cont.txt",
    "S12_CLOSING":          "signal_analysis_s12_closing.txt",
    "S13_BOX_BREAKOUT":     "signal_analysis_s13_box_breakout.txt",
    "S14_OVERSOLD_BOUNCE":  "signal_analysis_s14_oversold_bounce.txt",
    "S15_MOMENTUM_ALIGN":   "signal_analysis_s15_momentum_align.txt",
    "S16_ACCUMULATION_SHADOW": "signal_analysis_s16_accumulation_shadow.txt",
}

_STRATEGY_PROMPTS: dict[str, str] = {}
for _strat, _fname in _STRATEGY_PROMPT_FILES.items():
    try:
        _STRATEGY_PROMPTS[_strat] = (_PROMPT_DIR / _fname).read_text(encoding="utf-8")
    except Exception as _exc:
        logger.warning("[AI] %s prompt load failed, using default: %s", _strat, _exc)
        _STRATEGY_PROMPTS[_strat] = _SYS_PROMPT


def _get_system_prompt(strategy: str | None) -> str:
    if strategy and strategy in _STRATEGY_PROMPTS:
        return _STRATEGY_PROMPTS[strategy]
    return _SYS_PROMPT


def _build_system_prompt(signal: dict) -> str:
    """기본 시스템 프롬프트에 전략별 페르소나를 자동 주입한다."""
    strategy = signal.get("strategy")
    base = _get_system_prompt(strategy)
    sections = [base]
    if ENABLE_STRATEGY_PERSONA_INJECTION:
        persona = signal.get("persona") or get_persona(strategy)
        if persona:
            sections.append(f"[전략별 자동주입 페르소나]\n{persona}")
    if family_live_routing_enabled() and strategy in ALL_SETUP_IDS:
        family = family_for_setup(strategy)
        matched = signal.get("matched_setup_ids") or [strategy]
        sections.append(
            "[STRATEGY FAMILY LIVE GUARD]\n"
            f"family_id={family.family_id}; family_name={family.name}; "
            f"primary_setup_id={strategy}; matched_setup_ids={json.dumps(matched, ensure_ascii=False)}\n"
            "The setup-specific prompt above remains authoritative. The family is an "
            "orchestration and attribution layer, not permission to blend setup rules, "
            "TP/SL policies, scores, or position sizes.\n"
            "Never override a failed hard gate, stale or missing required Kiwoom data, "
            "effective-RR gate, session gate, active-position guard, or risk limit. "
            "Toss data is supplementary and never an execution-price, order, fill, VI, "
            "or real-time quote source. Do not average Toss and Kiwoom values.\n"
            "Do not infer missing fields. Correlated setup confirmations may explain a "
            "decision but must not increase quantity. If any required guard is failed or "
            "unknown, return CANCEL. For ENTER, prices must satisfy "
            "claude_tp2 >= claude_tp1 > entry_price > claude_sl; otherwise return CANCEL."
        )
    return "\n\n".join(sections)


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
        round_trip_cost = 2 * slip
        eff_target = raw_target - round_trip_cost
        eff_risk   = raw_risk   + round_trip_cost
        if eff_risk > 0:
            eff_rr = eff_target / eff_risk
            parts.append(f"실질R:R={eff_rr:.2f}({'주의' if eff_rr < 1.0 else 'OK'})")

    return " | ".join(parts) + "\n" if parts else ""


_ZONE_ANALYZER_STRATEGIES = frozenset({
    "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S13_BOX_BREAKOUT",
    "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN",
})


def _fmt_zone_ctx(signal: dict) -> str:
    """
    존 분석 컨텍스트 블록 생성 (S8/S9/S13/S14/S15 전용).
    Claude가 지지/저항 존 품질을 평가하고 TP/SL을 구조적으로 제안하도록 유도.
    """
    if signal.get("strategy") not in _ZONE_ANALYZER_STRATEGIES:
        return ""

    strategy   = signal.get("strategy")
    buy_zone   = signal.get("buy_zone")
    sell_zone1 = signal.get("sell_zone1")
    zone_rr    = signal.get("zone_rr")
    is_s8_support_zone = (
        strategy == "S8_GOLDEN_CROSS"
        and signal.get("s8_buy_zone_role") == "support_zone"
    )

    if not isinstance(buy_zone, dict):
        return ""

    entry  = float(signal.get("cur_prc") or signal.get("entry_price") or 0)
    bz_low  = int(buy_zone.get("low", 0) or 0)
    bz_high = int(buy_zone.get("high", 0) or 0)
    bz_str  = int(buy_zone.get("strength", 0) or 0)
    bz_anch = buy_zone.get("anchors") or []

    if bz_low <= 0 or bz_high <= 0:
        return ""

    # 현재가 위치 레이블
    if entry > 0:
        if entry < bz_low:
            pos_label = "지지 구간 하단 이탈" if is_s8_support_zone else "박스 미진입"
        elif entry > bz_high:
            if is_s8_support_zone:
                gap_pct = (entry - bz_high) / max(bz_high, 1) * 100
                pos_label = f"지지 구간 상단 {gap_pct:.1f}% 위"
            else:
                pos_label = "박스 상단 초과"
        else:
            pct = (entry - bz_low) / max(bz_high - bz_low, 1) * 100
            top_q = bz_low + 0.75 * (bz_high - bz_low)
            if is_s8_support_zone:
                pos_label = f"지지 구간 내부 상단 ({pct:.0f}%)" if entry >= top_q else f"지지 구간 내부 하단 ({pct:.0f}%)"
            else:
                pos_label = f"박스 내부 상단 ({pct:.0f}%)" if entry >= top_q else f"박스 내부 하단 ({pct:.0f}%)"
    else:
        pos_label = "N/A"

    if is_s8_support_zone:
        lines = [
            "[S8 지지/눌림 분석]",
            f"지지 구간: {bz_low:,}원 ~ {bz_high:,}원 (강도 {bz_str}/5)",
            f"  근거: {' · '.join(bz_anch) if bz_anch else 'N/A'}",
            f"현재가 위치: {pos_label}",
            "해석: 이 구간은 즉시 매수 박스가 아니라 눌림 지정가와 손절 기준으로 사용합니다.",
        ]
        entry_policy = signal.get("s8_zone_entry_policy")
        if entry_policy:
            lines.append(f"S8 진입 정책: {entry_policy}")
        caution = signal.get("s8_zone_caution_reason")
        if caution:
            lines.append(f"S8 주의: {caution}")
    else:
        lines = [
            "[존 분석]",
            f"매수 박스: {bz_low:,}원 ~ {bz_high:,}원 (강도 {bz_str}/5)",
            f"  근거: {' · '.join(bz_anch) if bz_anch else 'N/A'}",
            f"현재가 위치: {pos_label}",
        ]

    if isinstance(sell_zone1, dict):
        sz_low  = int(sell_zone1.get("low", 0) or 0)
        sz_high = int(sell_zone1.get("high", 0) or 0)
        sz_anch = sell_zone1.get("anchors") or []
        if sz_low > 0 and sz_high > 0:
            lines += [
                "",
                f"매도 박스1: {sz_low:,}원 ~ {sz_high:,}원",
                f"  근거: {' · '.join(sz_anch) if sz_anch else 'N/A'}",
            ]

    if zone_rr is not None:
        lines.append(f"\n존 기반 R:R (최악진입 기준): {float(zone_rr):.2f}")

    return "\n".join(lines) + "\n"


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
    conc = sig.get("buy_concentration_pct", 0)
    smtm = "✓" if sig.get("inst_frgn_smtm") else ""
    return (
        f"외인+기관 순매수 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 순매수: {amt_str}, "
        f"연속일: {sig.get('continuous_days', 'N/A')}일, "
        f"외인+기관동시{smtm} 집중도: {conc}%, "
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
    pct_ma5     = sig.get("pct_ma5", "N/A")
    pct_zone    = sig.get("pct_ma5_zone", "N/A")
    stoch_gc    = "골든크로스" if sig.get("stoch_gc") else "미확인"
    vol_quality = "약함(1.1~1.3배)" if sig.get("vol_weak") else "정상"
    return (
        f"정배열 눌림목 스윙 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 등락: {c['flu_rt']}%\n"
        f"MA 정렬: MA5>MA20>MA60 정배열, MA5 이격: {pct_ma5}%({pct_zone})\n"
        f"RSI: {sig.get('rsi', 'N/A')}, 스토캐스틱: {stoch_gc}, "
        f"거래량: {sig.get('vol_ratio', 'N/A')}x({vol_quality})\n"
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

def _s16_body(sig, c) -> str:
    return (
        f"세력 매집 관찰 후 트리거 신호 평가:\n"
        f"종목: {c['stk_nm']}({c['stk_cd']}), 상태: {sig.get('s16_state', 'N/A')}, "
        f"매집점수: {sig.get('accumulation_score', 'N/A')}, 수급점수: {sig.get('supply_score', 'N/A')}, "
        f"트리거점수: {sig.get('trigger_score', 'N/A')}, 리스크점수: {sig.get('risk_score', 'N/A')}\n"
        f"박스: {sig.get('box_low', 'N/A')}~{sig.get('box_high', 'N/A')}, "
        f"현재가: {sig.get('cur_prc', 'N/A')}, 거래량비율: {sig.get('vol_ratio', 'N/A')}x, "
        f"체결강도: {c['strength']}, 호가비율: {c['bid_ratio']}, RR: {sig.get('effective_rr', sig.get('rr_ratio', 'N/A'))}\n"
        f"근거: {sig.get('s16_reason', '')}\n"
        f"규칙점수: {c['rule_score']}/100\n"
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
    "S16_ACCUMULATION_SHADOW": (_s16_body, "세력 매집 트리거가 실제 ENTER 가능한 자리인지 판단하고 최종 TP1/TP2/SL(원화)을 JSON으로 답하세요."),
}


# 전략별 압축 프롬프트 생성기
def _fmt_eok(amount) -> str | None:
    """원화 정수 문자열 → 억원 단위 부호 포함 문자열. 파싱 실패 시 None."""
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return None
    eok = val / 1_0000_0000.0
    return f"{eok:+,.0f}억"


def _fmt_investor_flow_line(flow: dict | None) -> str:
    """시장 전체(코스피/코스닥) 투자자 순매수 — 토스 market-indicators 전용,
    Kiwoom에는 없던 데이터. 참고정보일 뿐 어떤 게이트에도 쓰이지 않는다."""
    if not flow:
        return ""
    parts = []
    for market, label in (("kospi", "코스피"), ("kosdaq", "코스닥")):
        data = flow.get(market)
        if not isinstance(data, dict):
            continue
        foreign = _fmt_eok(data.get("foreigner_net"))
        inst = _fmt_eok(data.get("institution_net"))
        if foreign is not None or inst is not None:
            parts.append(f"{label}(외인{foreign or 'N/A'}/기관{inst or 'N/A'})")
    if not parts:
        return ""
    return "시장수급: " + " ".join(parts) + "\n"


def _fmt_investor_flow_trend_line(trend: dict | None) -> str:
    """최근 30분간 시장 전체 수급 추세(가속/둔화) — 지수 분단위 시계열(토스
    TossMarketScheduler가 1분마다 기록) 기반. 스윙 전략에서만 채워지며 toss_risk와
    같은 게이트를 공유한다. 참고정보일 뿐 어떤 게이트에도 쓰이지 않는다."""
    if not trend:
        return ""
    parts = []
    for market, label in (("kospi", "코스피"), ("kosdaq", "코스닥")):
        data = trend.get(market)
        if not isinstance(data, dict):
            continue
        f_delta = _fmt_eok(data.get("foreigner_net_delta"))
        i_delta = _fmt_eok(data.get("institution_net_delta"))
        if f_delta is not None or i_delta is not None:
            parts.append(f"{label}(외인{f_delta or 'N/A'}/기관{i_delta or 'N/A'}, 최근30분 변화)")
    if not parts:
        return ""
    return "시장수급추세: " + " ".join(parts) + "\n"


def _fmt_toss_risk_line(risk: dict | None) -> str:
    """종목별 공매도/신용거래/대차거래 — 토스 전용, Kiwoom에는 없던 데이터.
    세 데이터 모두 확정치 반영이 느려(당일 저녁~T+1) 장중에는 보통 전일자다.
    참고정보일 뿐 어떤 게이트에도 쓰이지 않는다."""
    if not risk:
        return ""
    parts = []
    ss = risk.get("short_selling")
    if isinstance(ss, dict):
        rate = ss.get("shortSellingAmountRate")
        try:
            if rate is not None:
                parts.append(f"공매도비중{float(rate) * 100:.1f}%({ss.get('date', '')})")
        except (TypeError, ValueError):
            pass
    credit = risk.get("credit_trades")
    if isinstance(credit, dict):
        margin = (credit.get("marginLoan") or {})
        rate = margin.get("balanceRate")
        try:
            if rate is not None:
                parts.append(f"신용융자잔고비율{float(rate) * 100:.2f}%({credit.get('date', '')})")
        except (TypeError, ValueError):
            pass
    lending = risk.get("securities_lending")
    if isinstance(lending, dict) and lending.get("balanceQuantity"):
        parts.append(f"대차잔고{lending.get('balanceQuantity')}주({lending.get('date', '')})")
    warnings = risk.get("warnings")
    if isinstance(warnings, list) and warnings:
        types = ",".join(sorted({w.get("warningType", "") for w in warnings if isinstance(w, dict)}))
        if types:
            parts.append(f"매수유의사항[{types}]")
    if not parts:
        return ""
    return "종목리스크(토스): " + ", ".join(parts) + "\n"


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
    ask  = hoga.get("total_sel_bid_req", "0")
    try:
        bid_val = float(str(bid).replace(",", "") or 0)
        ask_val = float(str(ask).replace(",", "") or 0)
        if bid_val > 0 and ask_val > 0:
            bid_ratio = round(bid_val / ask_val, 2)
        elif signal.get("bid_ratio") is not None:
            bid_ratio = round(float(str(signal.get("bid_ratio")).replace(",", "")), 2)
        else:
            bid_ratio = 0
    except Exception:
        try:
            bid_ratio = round(float(str(signal.get("bid_ratio")).replace(",", "")), 2)
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
    zone_ctx = _fmt_zone_ctx(signal)
    quality_ctx = (
        f"신호품질: {signal.get('signal_quality_score', 'N/A')}/100"
        f"({signal.get('signal_quality_bucket', 'N/A')}), "
        f"RR품질: {signal.get('rr_quality_bucket', 'N/A')}, "
        f"성과EV: {signal.get('strategy_ev_pct', signal.get('expected_value', 'N/A'))}, "
        f"표본수: {signal.get('strategy_sample_count', signal.get('sample_n', 'N/A'))}\n"
    )

    # 시장 컨텍스트: 지수 등락률, 거래대금, 시가총액
    _kospi = market_ctx.get("kospi_flu_rt")
    _kosdaq = market_ctx.get("kosdaq_flu_rt")
    _mktcap = market_ctx.get("market_cap_eok")
    # Kiwoom realtime FID 14 is expressed in KRW millions.
    # Missing data must not be rendered as a real zero-liquidity observation.
    _acc_prica_raw = tick.get("acc_trde_prica", "")
    try:
        _acc_million = float(str(_acc_prica_raw).replace(",", "").replace("+", ""))
        _acc_eok = _acc_million / 100.0 if _acc_million > 0 else None
    except (TypeError, ValueError):
        _acc_eok = None
    _idx_str = ""
    if _kospi is not None or _kosdaq is not None:
        _idx_str += "지수: "
        if _kospi is not None:
            _idx_str += f"KOSPI{_kospi:+.2f}% "
        if _kosdaq is not None:
            _idx_str += f"KOSDAQ{_kosdaq:+.2f}%"
        _idx_str = _idx_str.strip() + ", "
    _acc_text = (
        f"당일거래대금: {_acc_eok:,.1f}억원"
        if _acc_eok is not None
        else "당일거래대금: 확인불가(0억원 아님)"
    )
    _market_ctx_line = (
        f"{_idx_str}"
        f"{_acc_text}"
        + (f", 시총: {_mktcap}억" if _mktcap else "")
        + "\n"
    ) if (_idx_str or _acc_eok is not None or _mktcap) else ""

    _market_ctx_line += _fmt_investor_flow_line(market_ctx.get("investor_flow"))

    # 스윙 전략 전용 종합 블록 — 시장수급 추세(지수 분단위 시계열) + 종목별
    # 공매도/신용/대차/매수유의사항을 하나로 묶어 Claude가 함께 판단하게 한다.
    # 둘 다 같은 스윙 게이트를 공유하므로 데이트레이딩 전략에서는 항상 빈 문자열.
    _swing_block = (
        _fmt_investor_flow_trend_line(market_ctx.get("investor_flow_trend"))
        + _fmt_toss_risk_line(market_ctx.get("toss_risk"))
    )
    if _swing_block:
        _market_ctx_line += "[스윙 참고 — 시장수급 추세 및 종목 리스크(토스)]\n" + _swing_block

    tpl = _STRATEGY_TEMPLATES.get(strategy)
    if tpl:
        body_fn, question = tpl
        return body_fn(signal, ctx) + _market_ctx_line + quality_ctx + tpsl_ctx + zone_ctx + question

    # 미등록 전략 – 범용 폴백
    return (
        f"매매 신호 평가:\n"
        f"종목: {ctx['stk_nm']}({ctx['stk_cd']}), 전략: {strategy}, "
        f"등락: {ctx['flu_rt']}%, 체결강도: {ctx['strength']}, 규칙점수: {rule_score}/100\n"
        f"{_market_ctx_line}"
        f"{quality_ctx}"
        f"{tpsl_ctx}"
        f"{zone_ctx}"
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
    today_str = datetime.now(KST).strftime("%Y%m%d")
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
    설정된 타임아웃 또는 오류 시 규칙 스코어 폴백.
    rdb: Redis 클라이언트 (토큰 사용량 추적용, 선택)
    반환: {"action": ..., "ai_score": ..., "confidence": ..., "reason": ...,
           "cancel_reason": ..., "adjusted_target_pct": ..., "adjusted_stop_pct": ...}
    """
    client = _get_claude_client()
    # 스윙 전략(strategy_meta.SWING_STRATEGIES)만 조회 — queue_worker._build_market_ctx의
    # _TOSS_RISK_STRATEGIES와 동일 범위를 유지해야 한다. 데이트레이딩 전략까지 여기서
    # 무조건 재조회하면 범위가 암묵적으로 넓어져(2026-08-11 점검에서 발견) 설계 의도와
    # 어긋나고 Toss STOCK 레이트리밋(5/s) 예산을 불필요하게 쓴다.
    if "toss_risk" not in market_ctx and signal.get("strategy") in _TOSS_SWING_STRATEGIES:
        # queue_worker._build_market_ctx가 이미 채워둔 경우 재조회하지 않는다
        # (rule scoring과 Claude 프롬프트가 같은 Redis 캐시 결과를 공유).
        toss_risk = await _toss_fetch_stock_risk_context(rdb, str(signal.get("stk_cd", "")))
        if toss_risk:
            market_ctx = {**market_ctx, "toss_risk": toss_risk}
    user_message = _build_user_message(signal, market_ctx, rule_score)
    system_prompt = _build_system_prompt(signal)

    raw_text = ""
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model      = CLAUDE_MODEL,
                max_tokens = MAX_TOKENS,
                system     = system_prompt,
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
                "vol_ratio": signal.get("vol_ratio"),
                "volume_ratio_source": signal.get("volume_ratio_source"),
            })
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("[AI] Claude 타임아웃 (%ds) [%s %s] – CANCEL",
                       CLAUDE_TIMEOUT, signal.get("stk_cd"), signal.get("strategy"))
        return _ai_failure_cancel(rule_score, "AI analysis timeout")
    except json.JSONDecodeError as e:
        logger.error("[AI] JSON 파싱 실패: %s / raw=%.200s", e, raw_text)
        return _ai_failure_cancel(rule_score, "AI response JSON parse failed")
    except anthropic.APIError as e:
        logger.warning("[AI] Claude API 오류: %s – CANCEL", e)
        return _ai_failure_cancel(rule_score, "AI API error")
    except Exception as e:
        logger.warning("[AI] 예기치 않은 오류: %s – CANCEL", e)
        return _ai_failure_cancel(rule_score, "AI analysis unavailable")

def _ai_failure_cancel(rule_score: float, cancel_reason: str) -> dict:
    return {
        "action":              "CANCEL",
        "ai_score":            rule_score,
        "confidence":          "LOW",
        "reason":              cancel_reason,
        "cancel_reason":       cancel_reason,
        "cancel_type":         "AI_UNAVAILABLE",
        "adjusted_target_pct": None,
        "adjusted_stop_pct":   None,
        "claude_tp1":          None,
        "claude_tp2":          None,
        "claude_sl":           None,
    }


def _fallback(rule_score: float) -> dict:
    """Claude API 실패 시 보수적으로 CANCEL한다."""
    return _ai_failure_cancel(rule_score, "AI analysis unavailable")


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
    if action in ("HOLD", "CANCEL"):
        result = {
            **result,
            "claude_tp1": None,
            "claude_tp2": None,
            "claude_sl": None,
        }

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
