"""
ai-engine/telegram_notifier.py
──────────────────────────────────────────────────────────────
StockMate AI – Telegram 직접 알림 모듈

역할
  전략 스캐너가 매수 신호를 감지했을 때 Telegram 봇 API를 통해
  즉시 알림 메시지를 전송한다.

환경변수
  TELEGRAM_BOT_TOKEN        – 봇 토큰 (필수)
  TELEGRAM_CHAT_ID          – 대상 채팅 ID (단일 값 또는 콤마 구분 목록)
  TELEGRAM_ALLOWED_CHAT_IDS – 위 변수 미설정 시 폴백으로 사용
  TELEGRAM_DRY_RUN          – true 설정 시 실제 전송 없이 로그만 출력 (기본: false)
"""

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

STRATEGY_DISPLAY: dict[str, tuple[str, str]] = {
    "S1_GAP_OPEN":          ("🚀 갭상승 시초가",      "갭+체결강도+호가비율 조건 충족"),
    "S2_VI_PULLBACK":       ("🎯 VI 눌림목",          "VI 발동 후 눌림 구간 재진입"),
    "S3_INST_FRGN":         ("🏦 외인+기관 동반",     "외인·기관 3일 연속 순매수"),
    "S4_BIG_CANDLE":        ("📊 장대양봉 추격",      "장대양봉+거래량 급증 돌파"),
    "S5_PROG_FRGN":         ("💻 프로그램+외인",      "프로그램 순매수+외인 동반"),
    "S6_THEME_LAGGARD":     ("🔥 테마 후발주",        "테마 상위+후발주 체결강도 충족"),
    "S7_AUCTION":           ("⚡ 동시호가",            "갭+호가비율 조건 충족"),
    "S8_GOLDEN_CROSS":      ("📈 골든크로스 스윙",    "5일선 골든크로스+거래량 확인"),
    "S9_PULLBACK_SWING":    ("🔄 눌림목 반등 스윙",   "정배열 5MA 근접 눌림 반등"),
    "S10_NEW_HIGH":         ("🏆 52주 신고가 돌파",   "신고가+거래량 급증"),
    "S11_FRGN_CONT":        ("🌏 외인 연속 수급",     "외국인 3일+ 연속 순매수"),
    "S12_CLOSING":          ("🔔 종가 기관수급 강세",  "종가 등락률+체결강도 확인"),
    "S13_BOX_BREAKOUT":     ("📦 박스권 돌파 스윙",   "박스권 상단 거래량 돌파"),
    "S14_OVERSOLD_BOUNCE":  ("↩️ 과매도 반등",        "RSI 과매도+ATR 수렴"),
    "S15_MOMENTUM_ALIGN":   ("⚡ 모멘텀 정렬 스윙",   "다중 지표 동조+거래량 확인"),
}


def _safe_float(val, default=None) -> Optional[float]:
    """None-safe float 변환. 실패 시 default 반환."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _fmt_price(price: Optional[float]) -> str:
    """한국 원화 표기 (예: 12345 → 12,345원). price 가 없으면 '미확인'."""
    if price is None or price <= 0:
        return "미확인"
    return f"{price:,.0f}원"


def _fmt_pct(pct: Optional[float], sign: bool = True) -> str:
    """등락률 표기 (예: 4.0 → '+4.0%', -2.0 → '-2.0%')."""
    if pct is None:
        return "N/A"
    prefix = "+" if sign and pct >= 0 else ""
    return f"{prefix}{pct:.1f}%"


def format_buy_signal(sig: dict) -> str:
    """
    매수 신호 dict 를 Telegram HTML 메시지로 변환.

    sig 에서 사용하는 필드:
      stk_cd, stk_nm, strategy, entry_type,
      cur_prc / entry_price,   ← 진입가 (둘 중 존재하는 것 사용)
      target_pct, target2_pct, ← 1차/2차 목표 비율
      stop_pct,                ← 손절 비율 (음수)
      gap_pct, cntr_strength, bid_ratio, vol_ratio,
      pullback_pct, theme_name,
      score / signal_score     ← 스코어
    """
    strategy_key = sig.get("strategy", "")
    display_name, default_reason = STRATEGY_DISPLAY.get(
        strategy_key, (strategy_key or "전략 미상", "조건 충족")
    )

    stk_cd = sig.get("stk_cd", "N/A")
    stk_nm = sig.get("stk_nm") or ""
    ticker = f"{stk_nm} ({stk_cd})" if stk_nm else stk_cd

    # 진입가
    entry_price = _safe_float(sig.get("cur_prc") or sig.get("entry_price"))
    entry_type  = sig.get("entry_type", "")

    # 비율 값
    target_pct  = _safe_float(sig.get("target_pct"))
    target2_pct = _safe_float(sig.get("target2_pct"))
    if target2_pct is None and target_pct is not None:
        target2_pct = round(target_pct * 1.5, 1)
    stop_pct = _safe_float(sig.get("stop_pct"))

    # 실제 가격 계산 (entry_price 존재 시에만)
    def calc(base, pct):
        if base and pct is not None:
            return round(base * (1 + pct / 100))
        return None

    target1_price = calc(entry_price, target_pct)
    target2_price = calc(entry_price, target2_pct)
    stop_price    = calc(entry_price, stop_pct)

    # 신호 사유 조립
    reason_parts = [default_reason]
    if (v := _safe_float(sig.get("gap_pct"))) is not None:
        reason_parts.append(f"갭{_fmt_pct(v)}")
    if (v := _safe_float(sig.get("cntr_strength"))) is not None:
        reason_parts.append(f"체결강도 {v:.0f}%")
    if (v := _safe_float(sig.get("bid_ratio"))) is not None:
        reason_parts.append(f"호가비 {v:.1f}x")
    if (v := _safe_float(sig.get("vol_ratio"))) is not None:
        reason_parts.append(f"거래량 {v:.1f}x")
    if (v := _safe_float(sig.get("pullback_pct"))) is not None:
        reason_parts.append(f"눌림 {_fmt_pct(v)}")
    if sig.get("theme_name"):
        reason_parts.append(f"테마: {sig['theme_name']}")
    reason = " | ".join(reason_parts)

    score = _safe_float(sig.get("score") or sig.get("signal_score"))

    lines = [
        "🚨 <b>매수 추천 알림</b>",
        "",
        f"📌 <b>전략명</b>: {display_name}",
        f"📈 <b>종목</b>: {ticker}",
    ]

    # 진입가
    entry_line = f"💰 <b>진입가</b>: {_fmt_price(entry_price)}"
    if entry_type:
        entry_line += f"  ({entry_type})"
    lines.append(entry_line)

    # 1차 목표가
    if target1_price:
        lines.append(
            f"🎯 <b>1차 목표가</b>: {_fmt_price(target1_price)}"
            + (f"  ({_fmt_pct(target_pct)})" if target_pct is not None else "")
        )
    elif target_pct is not None:
        lines.append(f"🎯 <b>1차 목표가</b>: {_fmt_pct(target_pct)}")

    # 2차 목표가
    if target2_price:
        lines.append(
            f"🎯 <b>2차 목표가</b>: {_fmt_price(target2_price)}"
            + (f"  ({_fmt_pct(target2_pct)})" if target2_pct is not None else "")
        )
    elif target2_pct is not None:
        lines.append(f"🎯 <b>2차 목표가</b>: {_fmt_pct(target2_pct)}")

    # 손절가
    if stop_price:
        lines.append(
            f"🛑 <b>손절가</b>: {_fmt_price(stop_price)}"
            + (f"  ({_fmt_pct(stop_pct)})" if stop_pct is not None else "")
        )
    elif stop_pct is not None:
        lines.append(f"🛑 <b>손절가</b>: {_fmt_pct(stop_pct)}")

    lines.append(f"📊 <b>사유</b>: {reason}")

    if score is not None:
        lines.append(f"⭐ <b>스코어</b>: {score:.1f}")

    return "\n".join(lines)


class TelegramNotifier:
    """Telegram 봇 API를 통한 비동기 알림 발송기."""

    def __init__(self):
        self.bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")

        # TELEGRAM_CHAT_ID 우선, 없으면 TELEGRAM_ALLOWED_CHAT_IDS 폴백
        raw = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
        self.chat_ids: list[str] = [c.strip() for c in raw.split(",") if c.strip()]
        self.dry_run: bool = os.getenv("TELEGRAM_DRY_RUN", "false").lower() == "true"

        if not self.bot_token:
            logger.warning(
                "[TelegramNotifier] TELEGRAM_BOT_TOKEN 미설정 – 직접 알림 비활성화"
            )
        if not self.chat_ids:
            logger.warning(
                "[TelegramNotifier] TELEGRAM_CHAT_ID / TELEGRAM_ALLOWED_CHAT_IDS 미설정 – 직접 알림 비활성화"
            )

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_ids)

    async def send_message(self, text: str) -> bool:
        """
        설정된 모든 chat_id 에 메시지를 전송한다.
        실패 시 예외를 삼키고 False 를 반환하므로 호출 측 루프가 중단되지 않는다.
        """
        if not self.enabled:
            logger.debug("[TelegramNotifier] 비활성화 상태 – 메시지 스킵")
            return False

        if self.dry_run:
            logger.info("[TelegramNotifier][DRY-RUN] 전송 예정:\n%s", text)
            return True

        url = _TELEGRAM_API_URL.format(token=self.bot_token)
        success = True
        try:
            async with aiohttp.ClientSession() as session:
                for chat_id in self.chat_ids:
                    try:
                        payload = {
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "HTML",
                        }
                        async with session.post(
                            url, json=payload,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                logger.debug(
                                    "[TelegramNotifier] 전송 성공 (chat_id=%s)", chat_id
                                )
                            else:
                                body = await resp.text()
                                logger.warning(
                                    "[TelegramNotifier] 전송 실패 (chat_id=%s, status=%d): %s",
                                    chat_id, resp.status, body[:200],
                                )
                                success = False
                    except aiohttp.ClientError as e:
                        logger.error(
                            "[TelegramNotifier] 네트워크 오류 (chat_id=%s): %s", chat_id, e
                        )
                        success = False
                    except Exception as e:  # noqa: BLE001
                        logger.error(
                            "[TelegramNotifier] 예외 (chat_id=%s): %s", chat_id, e
                        )
                        success = False
        except Exception as e:  # noqa: BLE001
            logger.error("[TelegramNotifier] 세션 생성 실패: %s", e)
            return False

        return success

    async def send_buy_signal(self, sig: dict) -> bool:
        """
        매수 신호 dict 를 포맷하여 Telegram 으로 전송한다.
        format_buy_signal() 로 메시지를 생성하므로 sig 필드에 대한
        상세 설명은 해당 함수의 docstring 참조.
        """
        text = format_buy_signal(sig)
        return await self.send_message(text)
