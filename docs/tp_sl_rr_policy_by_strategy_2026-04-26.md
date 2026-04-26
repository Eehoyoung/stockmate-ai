# 전략별 TP/SL 및 RR 통과 기준 상세 문서

작성일: 2026-04-26  
기준 코드: `ai-engine/tp_sl_engine.py`, `ai-engine/queue_worker.py`, `ai-engine/scorer.py`, `ai-engine/strategy_meta.py`, `ai-engine/analyzer.py`

## 1. 적용 범위

이 문서는 현재 서비스가 매수 신호를 만들고 AI 판단을 통과시키는 과정에서 사용하는 TP/SL 산출 기준과 RR 통과 기준을 정리한다.

핵심 흐름은 다음과 같다.

1. 각 전략 모듈이 신호 후보를 만든다.
2. `calc_tp_sl()`이 전략별 규칙 기반 TP/SL, RR, 메타데이터를 계산한다.
3. `queue_worker`가 1차 규칙 점수와 RR 하드 게이트를 검사한다.
4. 1차를 통과하면 Claude 2차 분석을 호출한다.
5. Claude가 실행 TP/SL(`claude_tp1`, `claude_sl`)을 반환하면 RR을 다시 계산한다.
6. Claude TP/SL 기준 RR이 하드 기준 미만이면 최종 `CANCEL`로 전환한다.

## 2. 공통 TP/SL 산출 원칙

### 2.1 가격 기준

- 진입 기준가는 `cur_prc` 또는 `entry_price`다.
- TP/SL 계산에는 이미 확보된 일봉/분봉/지표 데이터만 사용하며, `tp_sl_engine.py` 자체는 추가 API 호출을 하지 않는다.
- 모든 결과 가격은 `to_signal_fields()`에서 호가 단위로 반올림된다.
- TP2가 있는 스윙 전략은 실행 목표를 단일 TP로 통합한다.

### 2.2 단일 TP 통합

현재 실행 구조는 분할익절이 아니라 단일 TP 중심이다.

- TP2가 있고 `TP2 > TP1`이면 스윙 전략은 `single_tp = int((TP1 + TP2) / 2)`로 통합한다.
- 통합 후 `tp2_price = None`으로 제거한다.
- 통합 TP 기준으로 `rr_ratio`, `effective_rr`, `single_tp_rr`을 다시 계산한다.
- 단타 전략(`S1`, `S2`, `S4`, `S6`)은 TP2 평균 통합을 적용하지 않고 1차 TP를 그대로 실행 목표로 둔다.

### 2.3 RR 계산식

RR은 단순 가격비가 아니라 왕복 비용을 반영한 실효 RR이다.

```text
reward = (TP - entry) / entry - 2 * slip_fee
risk   = (entry - SL) / entry + 2 * slip_fee
rr     = reward / risk
```

시장 구분별 비용 기본값:

| 구분 | 판정 | `slip_fee` |
|---|---|---:|
| KOSPI 추정 | 종목코드가 `0`으로 시작 | `0.0035` |
| KOSDAQ/기타 추정 | 그 외 | `0.0045` |

유효하지 않은 가격 조합은 RR 0.0 및 `skip_entry=True`가 된다. 예를 들어 TP가 진입가 이하이거나 SL이 진입가 이상이면 진입 불가다.

### 2.4 정책 메타데이터

모든 TP/SL 결과에는 다음 메타데이터가 붙는다.

- `min_rr_ratio`: 전략별 최소 실효 RR
- `raw_rr`: 비용 미반영 가격 RR
- `single_tp_rr`: 현재 실행 단일 TP 기준 가격 RR
- `effective_rr`: 비용 반영 실효 RR
- `rr_skip_reason`: RR 또는 손절폭 때문에 진입 불가가 된 사유
- `tp_policy_version`, `sl_policy_version`, `exit_policy_version`: 기본 `ta_v2_2026_04`
- `allow_overnight`, `allow_reentry`
- `time_stop_type`, `time_stop_minutes`, `time_stop_session`
- `trailing_pct`, `trailing_activation`, `trailing_basis`

## 3. RR 통과 기준

### 3.1 TP/SL 엔진 내부 최소 RR

`calc_tp_sl()`은 호출자가 기본값 `MIN_RR_RATIO=1.3`을 넘겼을 때 전략별 최소 RR로 교체한다. 호출자가 별도 `min_rr`을 명시하면 그 값을 우선한다.

| 전략 | 최소 RR | 손절폭 상한 | 오버나잇 | 재진입 | 트레일링 활성화 |
|---|---:|---:|---|---|---:|
| S1_GAP_OPEN | 1.80 | 2.2% | 불가 | 불가 | 없음 |
| S2_VI_PULLBACK | 1.80 | 2.0% | 불가 | 불가 | 없음 |
| S3_INST_FRGN | 1.45 | 없음 | 가능 | 가능 | 1.0R |
| S4_BIG_CANDLE | 1.70 | 2.5% | 불가 | 불가 | 없음 |
| S5_PROG_FRGN | 1.45 | 없음 | 가능 | 가능 | 1.0R |
| S6_THEME_LAGGARD | 1.60 | 3.0% | 불가 | 불가 | 없음 |
| S7_ICHIMOKU_BREAKOUT | 1.55 | 없음 | 가능 | 가능 | 1.5R |
| S8_GOLDEN_CROSS | 1.55 | 없음 | 가능 | 가능 | 1.0R |
| S9_PULLBACK_SWING | 1.55 | 없음 | 가능 | 가능 | 1.0R |
| S10_NEW_HIGH | 1.55 | 없음 | 가능 | 가능 | 1.0R |
| S11_FRGN_CONT | 1.55 | 없음 | 가능 | 가능 | 1.0R |
| S12_CLOSING | 1.45 | 없음 | 가능 | 불가 | 1.0R |
| S13_BOX_BREAKOUT | 1.55 | 없음 | 가능 | 가능 | 1.5R |
| S14_OVERSOLD_BOUNCE | 1.45 | 없음 | 가능 | 가능 | 1.2R |
| S15_MOMENTUM_ALIGN | 1.55 | 없음 | 가능 | 가능 | 1.0R |

전략별 최소 RR 미만이면 `skip_entry=True`가 붙고, `rr_skip_reason`에 `effective_rr x.xx < min_rr y.yy`가 기록된다. 단타 전략은 별도 손절폭 상한도 검사하며, 상한 초과 시 RR과 무관하게 `skip_entry=True`가 된다.

### 3.2 1차 규칙 기반 통과 기준

1차 필터는 `queue_worker`에서 다음 순서로 적용된다.

1. `rule_score(signal, market_ctx)`로 전략별 규칙 점수를 계산한다.
2. `should_skip_ai(score, strategy)`가 참이면 Claude 호출 없이 `CANCEL`한다.
3. 규칙 점수 통과 후 RR 하드 게이트를 검사한다.
4. RR 하드 게이트 통과 후 하드 게이트, 데이터 신선도, Claude 일일 한도를 검사한다.

전략별 Claude 호출 전 규칙 점수 임계값:

| 전략 | 1차 규칙 점수 임계값 |
|---|---:|
| S1_GAP_OPEN | 55 |
| S2_VI_PULLBACK | 65 |
| S3_INST_FRGN | 60 |
| S4_BIG_CANDLE | 65 |
| S5_PROG_FRGN | 65 |
| S6_THEME_LAGGARD | 60 |
| S7_ICHIMOKU_BREAKOUT | 62 |
| S8_GOLDEN_CROSS | 50 |
| S9_PULLBACK_SWING | 45 |
| S10_NEW_HIGH | 48 |
| S11_FRGN_CONT | 58 |
| S12_CLOSING | 60 |
| S13_BOX_BREAKOUT | 55 |
| S14_OVERSOLD_BOUNCE | 50 |
| S15_MOMENTUM_ALIGN | 65 |
| 미등록 전략 | 65 |

RR 하드 게이트:

- `RR_HARD_CANCEL_THRESHOLD`: 기본 `0.8`
- `RR_CAUTION_THRESHOLD`: 기본 `1.2`
- `rr_ratio < 0.8`이면 Claude 호출 전 `RR_TOO_LOW`로 `CANCEL`
- `0.8 <= rr_ratio < 1.2`이면 `rr_quality_bucket="caution"`으로 Claude에는 전달되지만 사전 취소는 하지 않는다.
- `1.2 <= rr_ratio < 1.5`는 `acceptable`
- `rr_ratio >= 1.5`는 `strong`

즉, 실제 통과 구조는 이중이다. TP/SL 엔진은 전략별 적정 최소 RR을 `skip_entry`와 메타데이터로 표시하고, 큐 워커는 별도 하드 기준 0.8 미만만 즉시 취소한다. 0.8 이상이지만 전략별 최소 RR 미만인 신호는 품질 정보와 `rr_skip_reason`이 Claude 판단에 전달될 수 있다.

### 3.3 2차 Claude 기반 통과 기준

Claude 호출 조건:

- 1차 규칙 점수가 전략별 임계값 이상
- RR 하드 게이트 0.8 이상
- 별도 하드 게이트 실패 없음
- 시장 데이터 신선도 취소 없음
- 일일 Claude 호출 한도 미초과

Claude는 `action`, `ai_score`, `confidence`, `reason`, `cancel_reason`, `claude_tp1`, `claude_sl` 등을 반환한다.

Claude가 `ENTER`를 반환하고 `claude_tp1`, `claude_sl`이 존재하면 `queue_worker._apply_claude_rr_override()`가 다음을 수행한다.

1. Claude TP/SL을 실행 기준으로 삼아 `compute_rr()`로 실효 RR을 재계산한다.
2. `rr_ratio`, `effective_rr`, `single_tp_rr`, `raw_rr`을 Claude TP/SL 기준으로 덮어쓴다.
3. `rr_basis="claude_tp_sl"`로 기록한다.
4. 재계산 RR이 `RR_HARD_CANCEL_THRESHOLD=0.8` 미만이면 Claude가 `ENTER`를 줬더라도 최종 `CANCEL`로 전환한다.
5. 재계산 RR이 하드 기준 이상이지만 전략별 `min_rr_ratio` 미만이면 `rr_skip_reason`에 `Claude TP/SL effective_rr x.xx < min_rr y.yy`를 기록한다.

Claude 장애 처리:

- Claude API 오류, 타임아웃, JSON 파싱 실패, 일일 한도 초과는 규칙 기반 ENTER로 대체하지 않는다.
- 이 경우 보수적으로 `CANCEL` 처리한다.

## 4. 전략별 TP/SL 기준

### S1_GAP_OPEN

성격: 갭상승 시초가 단타. 오버나잇 및 재진입 불가.

- 최소 RR: 1.80
- 손절폭 상한: 2.2%
- 시간 청산: 진입 후 30분 또는 당일 종가
- SL:
  - 기본은 진입가 아래 1.2~1.8% 범위의 장중 무효화 가격
  - ATR이 있으면 `ATR * 0.9`를 1.2~1.8% 범위로 제한해 거리 산출
  - 전일 종가가 진입가 아래이고 그 거리가 2.2% 이내면 `prev_close * 0.999`를 갭 지지선으로 사용
  - 예외 시 `entry * 0.982`
- TP:
  - 최근 15봉 내 진입가보다 0.8% 이상 위의 첫 저항
  - 저항이 없으면 ATR 기반 2.5~4.5% 목표
- 기타:
  - SL이 상대적으로 타이트해야 하는 전략이며 손절폭 상한 초과 시 진입 불가

### S2_VI_PULLBACK

성격: VI 발동 후 눌림목 반등 단타. 오버나잇 및 재진입 불가.

- 최소 RR: 1.80
- 손절폭 상한: 2.0%
- 시간 청산: 진입 후 15분 또는 당일 종가
- SL:
  - 진입가 아래 1.0~1.5% 범위
  - ATR이 있으면 `ATR * 0.75`를 1.0~1.5% 범위로 제한
  - 예외 시 `entry * 0.985`
- TP:
  - `vi_price > entry`이면 `vi_price * 1.002`와 `entry * 1.02` 중 큰 값, 단 `entry * 1.035`로 상한
  - VI 가격이 없으면 최근 12봉 내 0.5% 이상 위 첫 저항
  - 그 외 ATR 기반 2.0~3.5% 목표
  - 최종 fallback은 `entry * 1.025`

### S3_INST_FRGN

성격: 기관+외국인 동시 수급 스윙.

- 최소 RR: 1.45
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - `MA20 * 0.99`
  - MA20이 부적합하면 최근 15일 스윙 저점이 진입가의 90% 이상일 때 `swing_low * 0.99`
  - 그 외 `entry - ATR * 1.5`
  - fallback `entry * 0.95`
- TP:
  - 최근 40일 스윙 고점이 Fib 1.272 이상이고 3% 이상 위면 스윙 고점
  - 아니면 최근 20일 저점~현재가 기준 Fib 1.272
  - 그 외 `entry + ATR * 4.0`
  - fallback `entry * 1.08`
- TP2:
  - 두 번째 스윙 고점 또는 Fib 1.618
  - 실행 전 단일 TP로 평균 통합

### S4_BIG_CANDLE

성격: 장대양봉 후속 돌파 단타.

- 최소 RR: 1.70
- 손절폭 상한: 2.5%
- 시간 청산: 진입 후 20분 또는 당일 종가
- 오버나잇/재진입 불가
- SL:
  - 장대양봉 저가가 진입가 아래이고 거리 2.5% 이내면 `max(candle_low * 0.999, entry * 0.98)`
  - 아니면 ATR 기반 1.5~2.0% 손절
  - 예외 시 `entry * 0.98`
- TP:
  - 고가/저가가 있으면 측정 목표: `candle_high + range * 0.8`, 최소 3.5%, 최대 5.5%
  - 고가만 있으면 `candle_high * 1.01`, 최소 3.5%, 최대 5.5%
  - ATR fallback은 3.5~5.5%
  - 최종 fallback `entry * 1.04`

### S5_PROG_FRGN

성격: 프로그램 순매수+외국인 수급 스윙.

- 최소 RR: 1.45
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - `MA20 * 0.99`
  - 최근 10일 스윙 저점이 진입가의 92% 이상이면 `swing_low * 0.99`
  - 그 외 `entry - ATR * 1.5`
  - fallback `entry * 0.95`
- TP:
  - 최근 40일 스윙 고점이 3% 이상 위면 스윙 고점
  - 그 외 `entry + ATR * 3.0`
  - fallback `entry * 1.06`
- TP2:
  - 두 번째 스윙 고점이 있으면 후보로 둔 뒤 단일 TP로 평균 통합

### S6_THEME_LAGGARD

성격: 테마 후발주 단기 매매. 당일 청산 성격.

- 최소 RR: 1.60
- 손절폭 상한: 3.0%
- 시간 청산: 당일 종가
- 오버나잇/재진입 불가
- SL:
  - MA5가 진입가 아래이고 거리 2.5% 이내면 `MA5 * 0.995`
  - 아니면 ATR 기반 2.0~2.5% 손절
  - 예외 시 `entry * 0.975`
- TP:
  - 최근 20봉 첫 저항이 1.5% 이상 위면 사용하되 `entry * 1.06`으로 상한
  - 그 외 ATR 기반 4.0~6.0% 목표
  - fallback `entry * 1.045`

### S7_ICHIMOKU_BREAKOUT

성격: 일목균형표 구름대 돌파 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.5R
- SL:
  - 최근 20일 스윙 저점이 진입가의 88% 이상이면 `swing_low * 0.998`
  - ATR이 있으면 스윙 저점 SL과 `entry - ATR * 1.5` 중 더 높은 가격
  - fallback `entry * 0.95`
- TP:
  - 최근 30일 스윙 고점이 3% 이상 위면 TP1
  - TP2는 스윙 저점~TP1 기준 Fib 1.272 또는 두 번째 스윙 고점
  - 스윙 고점이 없으면 현재가 기준 Fib 1.272, fallback `entry * 1.08`
- 트레일링:
  - 기본 2.5%, 기준 `tp1_or_kijun`
  - MACD 약화 시 트레일링을 0.4%p 좁히고 TP를 보수화

### S8_GOLDEN_CROSS

성격: 골든크로스 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - `MA20 * 0.99`
  - MA20이 없으면 `entry - ATR * 2.0`
  - 그 외 최근 20일 스윙 저점 또는 `entry * 0.95`
- TP:
  - 최근 40일 스윙 고점
  - 없으면 볼린저 상단
  - 없으면 `entry + ATR * 3.0`
  - fallback `entry * 1.10`
- 트레일링: 2.5%, 기준 `tp1_hit`

### S9_PULLBACK_SWING

성격: 눌림목 반등 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - 최근 15일 스윙 저점 `* 0.99`
  - 없으면 `MA20 * 0.99`
  - 없으면 `entry - ATR * 2.0`
  - fallback `entry * 0.96`
- TP:
  - 최근 40일 스윙 고점
  - 없으면 `MA60 * 1.05`
  - 없으면 `entry + ATR * 2.5`
  - fallback `entry * 1.06`
- 트레일링: 2.5%, 기준 `tp1_hit`

### S10_NEW_HIGH

성격: 신고가 돌파 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - 최근 60일 이전 고점이 현재가 아래면 `prev_high * 0.98`
  - 없으면 `entry - ATR * 2.0`
  - fallback `entry * 0.94`
- TP:
  - 최근 20일 저점~현재가 기준 Fib 1.272
  - TP2는 Fib 1.618
  - TP1이 현재가 이하이면 `entry * 1.08`, TP2는 `entry * 1.15`
- 트레일링: 2.0%, 기준 `tp1_hit`

### S11_FRGN_CONT

성격: 외국인 지속 매수 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - MA20과 현재가 괴리가 6% 초과면 최근 15일 스윙 저점 `* 0.99`
  - 스윙 저점이 부적합하면 `entry * 0.94`
  - MA20 괴리가 6% 이하이면 `MA20 * 0.98`
  - MA20이 없으면 최근 20일 스윙 저점 `* 0.99` 또는 `entry * 0.95`
- TP:
  - 볼린저 상단이 현재가 위면 볼린저 상단
  - 아니면 최근 40일 스윙 고점
  - 없으면 `entry * 1.08`
- 트레일링: 2.5%, 기준 `tp1_hit`

### S12_CLOSING

성격: 종가 강도 기반 익일 오전까지의 스윙.

- 최소 RR: 1.45
- 오버나잇 가능, 재진입 불가
- 시간 청산: 익일 오전
- 트레일링 활성화: 1.0R
- SL:
  - 최근 5일 스윙 저점이 진입가의 92% 이상이면 `swing_low * 0.99`
  - 아니면 `MA5 * 0.99`
  - 아니면 당일 저가 `* 0.995`, 단 최대 손실 6% 캡 적용
  - 아니면 `MA20 * 0.99`
  - fallback `entry * 0.97`
- TP:
  - 최근 40일 스윙 고점이 3% 이상 위면 스윙 고점
  - 스윙 고점이 너무 가까우면 Fib 1.272로 보완
  - 없으면 Fib 1.272
  - 없으면 `entry + ATR * 3.0`, TP2는 `entry + ATR * 5.0`
  - fallback `entry * 1.05`
- 트레일링: 1.5%, 기준 `tp1_hit`

### S13_BOX_BREAKOUT

성격: 박스권 돌파 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.5R
- SL:
  - 최근 15일 박스 상단 `box_high * 0.99`
  - SL이 현재가 이상이면 `entry - ATR * 1.5`
  - ATR이 없으면 `entry * 0.95`
- TP:
  - 박스 저점~박스 상단 기준 Fib 1.272
  - TP2는 Fib 1.618
  - TP1이 현재가 이하이면 `entry * 1.08`, TP2는 `entry * 1.15`
- 트레일링: 2.0%, 기준 `tp1_hit`

### S14_OVERSOLD_BOUNCE

성격: 과매도 반등 스윙.

- 최소 RR: 1.45
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.2R
- SL:
  - 최근 10일 스윙 저점이 진입가의 90% 이상이면 `swing_low * 0.99`
  - 아니면 `MA20 * 0.99`
  - 아니면 `entry - ATR * 1.5`
  - fallback `entry * 0.95`
- TP:
  - 최근 40일 스윙 고점
  - 없으면 MA60 저항
  - 없으면 `entry + ATR * 3.5`
  - fallback `entry * 1.08`
- 트레일링: 1.5%, 기준 `tp1_hit`

### S15_MOMENTUM_ALIGN

성격: 모멘텀 정렬 스윙.

- 최소 RR: 1.55
- 오버나잇/재진입 가능
- 트레일링 활성화: 1.0R
- SL:
  - 최근 15일 스윙 저점이 진입가의 87% 이상이면 `swing_low * 0.99`
  - 아니면 `MA20 * 0.99`
  - 아니면 `entry - ATR * 1.5`
  - fallback `entry * 0.95`
- TP:
  - 최근 60일 스윙 고점이 Fib 1.272 이상이고 3% 이상 위면 스윙 고점
  - 아니면 최근 20일 저점~현재가 기준 Fib 1.272
  - 아니면 볼린저 상단이 5% 이상 위면 볼린저 상단
  - 아니면 `entry + ATR * 5.0`
  - fallback `entry * 1.12`
  - TP가 3% 미만이면 Fib 1.272, ATR 4.0배, 10% fallback 순으로 최소 거리 보정
- 트레일링: 2.5%, 기준 `tp1_hit`

## 5. 공통 스윙 보정

스윙 전략은 `_finalize_swing_result()`에서 다음 보정을 거친다.

- TP1이 현재가 대비 3% 이하이면 최소 `entry * 1.03`으로 보정한다.
- TP2가 TP1 이하이면 `TP1 * 1.04`로 보정한다.
- 트레일링 시작가는 기본적으로 `entry + 1R`이다.
- 전략 정책에 `trail_activation_r`이 있으면 해당 R 배수로 활성화 가격을 다시 계산한다.
- MACD histogram이 음수이거나 MACD line이 signal 아래이면 약화로 보고:
  - 트레일링 폭을 0.4%p 축소하되 최소 0.8%
  - TP2가 있으면 TP1과 TP2의 중간 쪽으로 낮춘다.
  - TP2가 없고 TP1만 있으면 현재가와 TP1의 중간으로 낮추되 최소 3% 위를 유지한다.

## 6. 운영상 해석 기준

- `rr_ratio`는 비용 반영 실효 RR이므로 단순 `(TP-entry)/(entry-SL)`보다 낮다.
- `raw_rr`와 `single_tp_rr`는 가격 구조를 보기 위한 보조값이다.
- `rr_quality_bucket="caution"`은 즉시 취소가 아니라 Claude 2차 판단 대상이다.
- Claude가 더 공격적인 TP 또는 더 타이트한 SL을 제안하면 RR이 개선될 수 있다.
- 반대로 Claude가 보수적인 TP/SL을 제시해 RR이 0.8 미만으로 떨어지면 최종 취소된다.
- Claude 실패 시 규칙 기반 결과로 자동 진입하지 않는다. 현재 서비스는 AI 장애를 진입 취소 사유로 본다.

## 7. 관련 코드 위치

- `ai-engine/tp_sl_engine.py`: 전략별 TP/SL, RR 계산, 단일 TP 통합, 정책 메타데이터
- `ai-engine/queue_worker.py`: 1차 규칙 점수 후 RR 하드 게이트, Claude 호출, Claude TP/SL RR 재계산
- `ai-engine/scorer.py`: 전략별 규칙 점수 및 Claude 호출 전 점수 컷
- `ai-engine/strategy_meta.py`: 전략별 Claude 호출 임계값
- `ai-engine/analyzer.py`: Claude 신호 분석 프롬프트, 응답 정규화, TP/SL 반환 필드
