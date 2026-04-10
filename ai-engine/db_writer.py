"""
db_writer.py
Python ai-engine → PostgreSQL 직접 쓰기 모듈 (asyncpg 기반).

연결 풀은 engine.py 시작 시 초기화하여 전달받는다.
Java Hibernate가 아닌 Python이 소유한 컬럼만 UPDATE/INSERT한다.

쓰기 책임 정리:
  - update_signal_score()        → trading_signals (rule_score ~ scored_at, *_at_signal, market_*)
  - insert_score_components()    → signal_score_components
  - record_overnight_eval()      → open_positions overnight_verdict/score
  - upsert_daily_indicators()    → daily_indicators
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 1. trading_signals — Python 소유 컬럼 UPDATE
# ──────────────────────────────────────────────────────────────────────────────

async def update_signal_score(
    pool,
    signal_id: int,
    *,
    rule_score:     float,
    ai_score:       float,
    rr_ratio:       Optional[float],
    action:         str,          # ENTER / CANCEL
    confidence:     str,          # HIGH / MEDIUM / LOW
    ai_reason:      str,
    tp_method:      Optional[str],
    sl_method:      Optional[str],
    skip_entry:     bool,
    # 기술지표 스냅샷 (없으면 None)
    ma5:            Optional[float] = None,
    ma20:           Optional[float] = None,
    ma60:           Optional[float] = None,
    rsi14:          Optional[float] = None,
    bb_upper:       Optional[float] = None,
    bb_lower:       Optional[float] = None,
    atr:            Optional[float] = None,
    # 시장 컨텍스트
    market_flu_rt:  Optional[float] = None,
    news_sentiment: Optional[str]   = None,
    news_ctrl:      Optional[str]   = None,
) -> bool:
    """
    Python 스코어링 완료 후 trading_signals 를 UPDATE.
    signal_id 가 없으면 (None/0) 조용히 스킵한다.
    """
    if not signal_id:
        return False
    try:
        now = datetime.now(timezone.utc)
        await pool.execute(
            """
            UPDATE trading_signals SET
                rule_score       = $2,
                ai_score         = $3,
                rr_ratio         = $4,
                action           = $5,
                confidence       = $6,
                ai_reason        = $7,
                tp_method        = $8,
                sl_method        = $9,
                skip_entry       = $10,
                scored_at        = $11,
                ma5_at_signal    = $12,
                ma20_at_signal   = $13,
                ma60_at_signal   = $14,
                rsi14_at_signal  = $15,
                bb_upper_at_sig  = $16,
                bb_lower_at_sig  = $17,
                atr_at_signal    = $18,
                market_flu_rt    = $19,
                news_sentiment   = $20,
                news_ctrl        = $21
            WHERE id = $1
            """,
            signal_id,
            round(rule_score, 2),
            round(ai_score, 2),
            round(rr_ratio, 2) if rr_ratio is not None else None,
            action,
            confidence,
            ai_reason,
            tp_method,
            sl_method,
            skip_entry,
            now,
            int(ma5)     if ma5     is not None else None,
            int(ma20)    if ma20    is not None else None,
            int(ma60)    if ma60    is not None else None,
            round(rsi14, 2) if rsi14 is not None else None,
            int(bb_upper) if bb_upper is not None else None,
            int(bb_lower) if bb_lower is not None else None,
            round(atr, 2) if atr is not None else None,
            round(market_flu_rt, 3) if market_flu_rt is not None else None,
            news_sentiment,
            news_ctrl,
        )
        logger.debug("[DBWriter] signal_id=%d score=%.1f action=%s 저장", signal_id, rule_score, action)
        return True
    except Exception as e:
        logger.error("[DBWriter] update_signal_score 오류 signal_id=%s: %s", signal_id, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 1-b. trading_signals — Python 단독 신호 INSERT (Java id 없을 때)
# ──────────────────────────────────────────────────────────────────────────────

async def insert_python_signal(
    pool,
    signal: dict,
    *,
    action:       str,
    confidence:   str,
    rule_score:   float,
    ai_score:     float,
    ai_reason:    str,
    skip_entry:   bool,
) -> Optional[int]:
    """
    Python strategy_runner 가 생성한 신호(Java id 없음)를 trading_signals 에 INSERT.
    성공 시 생성된 id 반환, 실패 시 None.
    """
    def _sf(v, default=None):
        try:
            f = float(str(v).replace(",", "").replace("+", ""))
            return f if f == f else default  # NaN 방어
        except (TypeError, ValueError):
            return default

    now    = datetime.utcnow()  # TIMESTAMP WITHOUT TIME ZONE 컬럼 호환
    status = "SENT" if action == "ENTER" else "CANCELLED"
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO trading_signals (
                stk_cd, strategy, signal_status, action, confidence,
                rule_score, ai_score, signal_score, ai_reason, skip_entry,
                entry_price, target_price, stop_price,
                tp1_price, tp2_price, sl_price,
                gap_pct, vol_ratio, cntr_strength, bid_ratio, pullback_pct,
                entry_type, theme_name, market_type,
                created_at, scored_at
            ) VALUES (
                $1,$2,$3,$4,$5,
                $6,$7,$8,$9,$10,
                $11,$12,$13,
                $14,$15,$16,
                $17,$18,$19,$20,$21,
                $22,$23,$24,
                $25,$26
            ) RETURNING id
            """,
            signal.get("stk_cd", ""),
            signal.get("strategy", ""),
            status, action, confidence,
            round(rule_score, 2), round(ai_score, 2), round(ai_score, 2),
            ai_reason, skip_entry,
            _sf(signal.get("entry_price") or signal.get("cur_prc")),
            _sf(signal.get("target_price") or signal.get("tp1_price")),
            _sf(signal.get("stop_price") or signal.get("sl_price")),
            _sf(signal.get("tp1_price")),
            _sf(signal.get("tp2_price")),
            _sf(signal.get("sl_price")),
            _sf(signal.get("gap_pct")),
            _sf(signal.get("vol_ratio")),
            _sf(signal.get("cntr_strength") or signal.get("cntr_str")),
            _sf(signal.get("bid_ratio")),
            _sf(signal.get("pullback_pct")),
            signal.get("entry_type"),
            signal.get("theme_name"),
            signal.get("market_type"),
            now,
            now,
        )
        new_id = row["id"] if row else None
        logger.debug("[DBWriter] Python신호 INSERT id=%s [%s %s] action=%s score=%.1f",
                     new_id, signal.get("stk_cd"), signal.get("strategy"), action, ai_score)
        return new_id
    except Exception as e:
        logger.error("[DBWriter] insert_python_signal 오류 [%s %s]: %s",
                     signal.get("stk_cd"), signal.get("strategy"), e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 2. signal_score_components — INSERT
# ──────────────────────────────────────────────────────────────────────────────

async def insert_score_components(
    pool,
    signal_id:   int,
    strategy:    str,
    components:  dict,
    total_score: float,
    threshold:   float,
) -> bool:
    """
    scorer.py 가 반환한 컴포넌트 dict 를 signal_score_components 에 INSERT.

    components 구조 (모든 키 Optional):
    {
        "base_score":      float,
        "time_bonus":      float,
        "vol_score":       float,
        "momentum_score":  float,
        "technical_score": float,
        "demand_score":    float,
        "risk_penalty":    float,
        "strategy_specific": dict,  # 전략별 추가 데이터 (JSONB 저장)
    }
    """
    if not signal_id:
        return False
    try:
        sg = components.get("strategy_specific", {})
        await pool.execute(
            """
            INSERT INTO signal_score_components
                (signal_id, strategy,
                 base_score, time_bonus, vol_score, momentum_score,
                 technical_score, demand_score, risk_penalty,
                 strategy_components,
                 total_score, threshold_used, passed_threshold,
                 computed_at)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13, NOW())
            ON CONFLICT (signal_id) DO UPDATE SET
                total_score      = EXCLUDED.total_score,
                passed_threshold = EXCLUDED.passed_threshold,
                computed_at      = NOW()
            """,
            signal_id,
            strategy,
            _opt_num(components.get("base_score")),
            _opt_num(components.get("time_bonus")),
            _opt_num(components.get("vol_score")),
            _opt_num(components.get("momentum_score")),
            _opt_num(components.get("technical_score")),
            _opt_num(components.get("demand_score")),
            _opt_num(components.get("risk_penalty")),
            json.dumps(sg, ensure_ascii=False) if sg else None,
            round(total_score, 2),
            round(threshold, 2),
            total_score >= threshold,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] insert_score_components 오류 signal_id=%s: %s", signal_id, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 3. open_positions — overnight 결과 UPDATE
# ──────────────────────────────────────────────────────────────────────────────

async def record_overnight_eval(
    pool,
    signal_id:       int,
    verdict:         str,   # HOLD / FORCE_CLOSE
    overnight_score: float,
) -> bool:
    """
    overnight_worker 가 HOLD/FORCE_CLOSE 결정 후 open_positions 에 기록.
    """
    if not signal_id:
        return False
    try:
        await pool.execute(
            """
            UPDATE open_positions SET
                overnight_verdict = $2,
                overnight_score   = $3,
                is_overnight      = TRUE,
                status            = CASE
                    WHEN $2 = 'HOLD' THEN 'OVERNIGHT'
                    ELSE status
                END
            WHERE signal_id = $1
              AND status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
            """,
            signal_id,
            verdict,
            round(overnight_score, 2),
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] record_overnight_eval 오류 signal_id=%s: %s", signal_id, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 3b. overnight_evaluations — INSERT
# ──────────────────────────────────────────────────────────────────────────────

async def insert_overnight_eval(
    pool,
    signal_id:       int,
    position_id:     Optional[int],
    stk_cd:          str,
    strategy:        str,
    verdict:         str,         # HOLD / FORCE_CLOSE
    final_score:     float,
    confidence:      str,
    reason:          str,
    *,
    pnl_pct:         Optional[float] = None,
    flu_rt:          Optional[float] = None,
    cntr_strength:   Optional[float] = None,
    rsi14:           Optional[float] = None,
    ma_alignment:    Optional[str]   = None,
    bid_ratio:       Optional[float] = None,
    entry_price:     Optional[float] = None,
    cur_price:       Optional[float] = None,
    score_components: Optional[dict] = None,
) -> bool:
    """overnight_evaluations 에 평가 결과 INSERT."""
    if not signal_id:
        return False
    try:
        import json as _json
        sc_json = _json.dumps(score_components) if score_components else None
        await pool.execute(
            """
            INSERT INTO overnight_evaluations
                (signal_id, position_id, stk_cd, strategy,
                 verdict, final_score, confidence, reason,
                 pnl_pct, flu_rt, cntr_strength, rsi14,
                 ma_alignment, bid_ratio, entry_price, cur_prc_at_eval,
                 score_components, evaluated_at)
            VALUES
                ($1,  $2,  $3,  $4,
                 $5,  $6,  $7,  $8,
                 $9,  $10, $11, $12,
                 $13, $14, $15, $16,
                 $17::jsonb, NOW())
            """,
            signal_id, position_id, stk_cd, strategy,
            verdict, round(final_score, 2), confidence, reason,
            round(pnl_pct, 4)       if pnl_pct       is not None else None,
            round(flu_rt, 4)        if flu_rt         is not None else None,
            round(cntr_strength, 2) if cntr_strength  is not None else None,
            round(rsi14, 2)         if rsi14          is not None else None,
            ma_alignment,
            round(bid_ratio, 3)     if bid_ratio      is not None else None,
            int(entry_price)        if entry_price     is not None else None,
            int(cur_price)          if cur_price       is not None else None,
            sc_json,
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] insert_overnight_eval 오류 signal_id=%s: %s", signal_id, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 4. daily_indicators — UPSERT
# ──────────────────────────────────────────────────────────────────────────────

async def upsert_daily_indicators(pool, stk_cd: str, date_str: str, ind: dict) -> bool:
    """
    기술지표 계산 결과를 daily_indicators 에 UPSERT (date + stk_cd UNIQUE 기반).
    date_str: 'YYYY-MM-DD' 형식
    ind: {close_price, ma5, ma20, ma60, rsi14, bb_upper, bb_lower, atr14, ...}
    """
    try:
        await pool.execute(
            """
            INSERT INTO daily_indicators
                (date, stk_cd,
                 close_price, open_price, high_price, low_price, volume, volume_ratio,
                 ma5, ma20, ma60, ma120, vol_ma20,
                 rsi14, stoch_k, stoch_d,
                 bb_upper, bb_mid, bb_lower, bb_width_pct, pct_b,
                 atr14, atr_pct,
                 macd_line, macd_signal, macd_hist,
                 is_bullish_aligned, is_above_ma20, is_new_high_52w, golden_cross_today,
                 swing_high_20d, swing_low_20d, swing_high_60d, swing_low_60d,
                 computed_at)
            VALUES
                ($1, $2,
                 $3,  $4,  $5,  $6,  $7,  $8,
                 $9,  $10, $11, $12, $13,
                 $14, $15, $16,
                 $17, $18, $19, $20, $21,
                 $22, $23,
                 $24, $25, $26,
                 $27, $28, $29, $30,
                 $31, $32, $33, $34,
                 NOW())
            ON CONFLICT (date, stk_cd) DO UPDATE SET
                close_price        = EXCLUDED.close_price,
                ma5                = EXCLUDED.ma5,
                ma20               = EXCLUDED.ma20,
                ma60               = EXCLUDED.ma60,
                rsi14              = EXCLUDED.rsi14,
                bb_upper           = EXCLUDED.bb_upper,
                bb_lower           = EXCLUDED.bb_lower,
                atr14              = EXCLUDED.atr14,
                is_bullish_aligned = EXCLUDED.is_bullish_aligned,
                golden_cross_today = EXCLUDED.golden_cross_today,
                swing_high_20d     = EXCLUDED.swing_high_20d,
                swing_low_20d      = EXCLUDED.swing_low_20d,
                computed_at        = NOW()
            """,
            date_str, stk_cd,
            _opt_int(ind.get("close_price")),  _opt_int(ind.get("open_price")),
            _opt_int(ind.get("high_price")),   _opt_int(ind.get("low_price")),
            ind.get("volume"),                  _opt_num(ind.get("volume_ratio")),
            _opt_int(ind.get("ma5")),   _opt_int(ind.get("ma20")),
            _opt_int(ind.get("ma60")),  _opt_int(ind.get("ma120")),
            ind.get("vol_ma20"),
            _opt_num(ind.get("rsi14")),  _opt_num(ind.get("stoch_k")),  _opt_num(ind.get("stoch_d")),
            _opt_int(ind.get("bb_upper")), _opt_int(ind.get("bb_mid")),  _opt_int(ind.get("bb_lower")),
            _opt_num(ind.get("bb_width_pct")),  _opt_num(ind.get("pct_b")),
            _opt_num(ind.get("atr14")),          _opt_num(ind.get("atr_pct")),
            _opt_num(ind.get("macd_line")),      _opt_num(ind.get("macd_signal")),
            _opt_num(ind.get("macd_hist")),
            ind.get("is_bullish_aligned"), ind.get("is_above_ma20"),
            ind.get("is_new_high_52w"),    ind.get("golden_cross_today"),
            _opt_int(ind.get("swing_high_20d")), _opt_int(ind.get("swing_low_20d")),
            _opt_int(ind.get("swing_high_60d")), _opt_int(ind.get("swing_low_60d")),
        )
        return True
    except Exception as e:
        logger.error("[DBWriter] upsert_daily_indicators 오류 %s %s: %s", stk_cd, date_str, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _opt_num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _opt_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None
