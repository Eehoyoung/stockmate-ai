# TP/SL RR 정책 문서 및 기능 다중 에이전트 토론 결과

작성일: 2026-04-26  
대상 문서: `docs/tp_sl_rr_policy_by_strategy_2026-04-26.md`  
검토 대상 코드: `ai-engine/tp_sl_engine.py`, `ai-engine/queue_worker.py`, `ai-engine/scorer.py`, `ai-engine/strategy_meta.py`, `ai-engine/analyzer.py`, `ai-engine/claude_analyst.py`, `ai-engine/position_monitor.py`, `ai-engine/redis_reader.py`, `ai-engine/db_writer.py`

## 1. 참여 에이전트

| 에이전트 | 역할/페르소나 | 핵심 관점 |
|---|---|---|
| Agent 1 | 퀀트 전략 검증가 | 전략별 TP/SL 수치, RR 정책, 실제 진입 게이트 정합성 |
| Agent 2 | 리스크 매니저 | 손절폭, 시간청산, 트레일링, 오버나잇, 실제 강제 리스크 |
| Agent 3 | 백엔드/데이터 파이프라인 엔지니어 | 저장 필드, DB 반영, cancel audit, payload와 DB 불일치 |
| Agent 4 | AI/Claude 프롬프트 감사자 | 자동 Claude와 수동 Claude 분리, 응답 스키마, override 흐름 |
| Agent 5 | 운영/장애 대응 담당자 | cancel reason, freshness, Redis key, 장애 runbook |
| Agent 6 | 문서 품질/제품 사용자 리뷰어 | 가독성, 용어 정의, 운영자 사용성, 흐름도/예시 |

## 2. 12회 토론 라운드 요약

### Round 1. 문서 목적과 독자 정의

- 문서 품질 리뷰어: 현재 문서는 코드 정책을 기록하지만 운영자, 개발자, 전략 검수자, 장애 대응자가 각각 언제 쓰는지 명확하지 않다.
- 운영 담당자: 운영 중에는 "왜 CANCEL됐는지"가 먼저 필요하므로 독자별 사용 시나리오가 있어야 한다.
- 결론: 문서 초반에 "운영자는 취소 사유 해석, 개발자는 정책 변경 기준, 전략 검수자는 전략별 TP/SL 검증"이라는 사용 목적을 추가한다.

### Round 2. 전략별 최소 RR의 의미

- 퀀트 검증가: `min_rr`는 `tp_sl_engine.py`에서 `skip_entry=True`와 `rr_skip_reason`을 남기지만, `queue_worker.py`의 실제 즉시 취소는 `rr_ratio < 0.8`만 본다.
- 리스크 매니저: 문서가 "최소 RR 통과 기준"이라고 쓰면 강제 게이트처럼 보인다.
- Claude 감사자: Claude override 후에도 전략별 `min_rr_ratio` 미만은 `rr_skip_reason`만 기록하고 자동 `CANCEL`은 아니다.
- 결론: 문서에서 `전략별 min_rr`는 현재 구현상 "목표/경고/메타데이터 기준"이고, 강제 하드 취소 기준은 `0.8`이라고 명시한다.

### Round 3. 실제 기능 버그 후보: Claude RR override 후 action 불일치

- 백엔드 엔지니어: `_apply_claude_rr_override(enriched)`가 `enriched["action"]`을 `CANCEL`로 바꿀 수 있지만, 이후 DB 저장과 `confirm_open_position()`은 기존 지역 변수 `action`을 계속 사용한다.
- 퀀트 검증가: 이 경우 Redis payload는 `CANCEL`인데 DB나 포지션 확정은 `ENTER`로 남을 수 있다.
- 리스크 매니저: 기능 보완 1순위다. 문서 문제가 아니라 실제 진입 리스크다.
- 결론: override 직후 `action`, `confidence`, `cancel_reason`, `display_reason`을 `enriched` 기준으로 재동기화해야 한다.

### Round 4. 스윙 TP 보정 후 RR 재계산 누락

- 퀀트 검증가: `_finalize_swing_result()`는 TP1 최소 3% 보정 또는 MACD 약화 보정으로 TP를 바꾸지만, 그 함수 안에서는 RR을 재계산하지 않는다.
- 리스크 매니저: TP가 바뀐 뒤 `rr_ratio/effective_rr`가 이전 TP 기준이면 운영 판단이 틀어질 수 있다.
- 백엔드 엔지니어: 저장되는 `rr_ratio`, `effective_rr`, `single_tp_rr`도 영향을 받는다.
- 결론: 최종 TP/SL 보정과 단일 TP 통합이 모두 끝난 뒤 RR을 한 번 더 계산하는 구조가 필요하다.

### Round 5. `skip_entry` 소비 여부

- 퀀트 검증가: `skip_entry=True`는 TP/SL 엔진이 만든 플래그지만 `queue_worker`가 직접 하드 게이트로 사용하지 않는다.
- 리스크 매니저: 손절폭 상한 초과나 `effective_rr < min_rr`가 있어도 `rr_ratio >= 0.8`이면 Claude로 넘어갈 수 있다.
- Claude 감사자: 의도적으로 Claude에게 판단을 맡기는 구조라면 문서 표현을 낮춰야 하고, 강제 차단 의도라면 코드가 보완되어야 한다.
- 결론: 제품 정책 결정이 필요하다. 현재 상태를 유지하려면 `skip_entry`는 "참고/경고 플래그"라고 문서화한다. 강제 정책으로 바꾸려면 queue gate를 추가한다.

### Round 6. Claude 자동 신호와 수동 `/claude` 분석 분리

- Claude 감사자: `analyzer.py`는 자동 매수 신호 2차 심사용이고, `claude_analyst.py`는 수동 `/claude` 분석용이다.
- 운영 담당자: 실패 처리도 다르다. 자동 신호는 실패 시 `CANCEL`, 수동 분석은 정보성 `HOLD`에 가깝다.
- 문서 품질 리뷰어: 현재 문서는 Claude 기반 판단을 하나로 설명해 혼동 가능성이 있다.
- 결론: 문서에 "자동 신호 Claude"와 "수동 `/claude` 분석"을 별도 섹션으로 분리한다.

### Round 7. Claude TP/SL 미반환과 TP2 폐기

- Claude 감사자: Claude가 `ENTER`를 주고도 `claude_tp1` 또는 `claude_sl`을 주지 않으면 RR override는 수행되지 않고 규칙 TP/SL이 유지된다.
- 백엔드 엔지니어: `claude_tp2`는 프롬프트/스키마에는 있지만 `queue_worker`에서 `None`으로 고정되어 자동 실행에 반영되지 않는다.
- 퀀트 검증가: 문서상 "Claude TP/SL 기준 RR 재계산"은 조건부라고 써야 정확하다.
- 결론: "Claude TP1/SL 둘 다 있을 때만 RR override, TP2는 현재 자동 실행에서 사용하지 않음"을 문서에 추가한다.

### Round 8. 저장 필드와 감사 한계

- 백엔드 엔지니어: `rr_basis="claude_tp_sl"`는 payload에는 남지만 DB 컬럼에는 없다.
- 운영 담당자: 나중에 DB만 보고 Claude TP/SL override 여부를 감사하기 어렵다.
- 문서 품질 리뷰어: "기록된다"는 표현은 어디에 기록되는지 구체화해야 한다.
- 결론: 문서에는 `rr_basis`가 현재 Redis/raw payload 성격의 transient field라고 명시한다. 장기 감사가 필요하면 DB 컬럼 추가를 별도 개선으로 둔다.

### Round 9. 시간청산과 청산 실행 정책

- 리스크 매니저: 문서는 S1 30분, S2 15분처럼 단순히 쓰지만 실제 `position_monitor.py`는 TP 미도달과 수익률 가드도 함께 본다.
- 퀀트 검증가: 스윙 전략은 TP/SL 엔진 정책에 time stop이 없어도 `position_monitor.py` 기본 보유기간이 적용된다.
- 결론: 문서에 "계산 정책", "진입 게이트", "청산 실행 정책"을 분리하고, 기본 보유기간 및 수익률 가드 조건을 추가한다.

### Round 10. 트레일링 우선순위

- 리스크 매니저: 문서는 TP1 도달 후 트레일링처럼 읽힐 수 있지만 실제 코드는 `trailing_activation` 이상이면 ACTIVE/OVERNIGHT 상태에서도 트레일링이 동작한다.
- 운영 담당자: TP1 직전 되돌림이 `TRAILING_STOP`으로 종료될 수 있으므로 운영 해석에 필요하다.
- 결론: 트레일링은 "TP1 이후 전용"이 아니라 "활성화 가격 도달 후 고점 대비 하락"으로 설명한다.

### Round 11. 운영/장애 대응 기준

- 운영 담당자: 문서에는 `RULE_THRESHOLD`, `RR_TOO_LOW`, `HARD_GATE`, `FRESHNESS_STALE`, `AI_UNAVAILABLE`, `AI_DAILY_LIMIT` 분류가 부족하다.
- 백엔드 엔지니어: `AI_UNAVAILABLE`, `AI_DAILY_LIMIT`는 AI성 원인이지만 `cancel_type`이 있으므로 `rule_cancel_signal`에 저장될 수 있다.
- 문서 품질 리뷰어: 운영자는 cancel taxonomy와 확인 위치가 필요하다.
- 결론: cancel reason taxonomy, 저장 테이블, Redis key, 장애별 1차 조치 runbook을 문서에 추가한다.

### Round 12. Freshness와 모니터링 기준

- 운영 담당자: 실제 freshness cutoff는 `hoga=2s`, `tick=5s`, `strength=10s`, `vi_active=5s`, `vi_released=20s` 취소 기준이다.
- 백엔드 엔지니어: missing timestamp는 배포 호환성을 위해 즉시 취소가 아니라 `missing` 상태다.
- 리스크 매니저: WS heartbeat warning과 freshness cancel의 관계를 구분해야 한다.
- 결론: 문서에 freshness 수치, missing/stale 차이, 주요 Redis key와 시스템 알림 임계값을 추가한다.

## 3. 최종 보완사항 목록

### P0. 기능 보완 필요

1. `queue_worker.py`에서 Claude RR override 후 지역 변수 재동기화
   - 현상: `enriched["action"]`이 `CANCEL`로 바뀌어도 이후 `action` 지역 변수는 기존 `ENTER`일 수 있다.
   - 위험: Redis/score queue와 DB/포지션 확정 상태가 어긋날 수 있다.
   - 제안: `_apply_claude_rr_override()` 직후 `action = enriched.get("action", action)` 등으로 재동기화하고 `display_reason`, `cancel_reason`, metrics, DB 저장 분기를 같은 기준으로 맞춘다.

2. 최종 TP/SL 보정 후 RR 재계산
   - 현상: `_finalize_swing_result()`가 TP1/TP2를 바꾼 뒤 RR을 재계산하지 않는다.
   - 위험: 저장 RR과 실제 실행 TP가 불일치할 수 있다.
   - 제안: finalization, MACD guard, 단일 TP 통합 이후 `rr_ratio`, `raw_rr`, `single_tp_rr`, `effective_rr`, `skip_entry`를 재산출한다.

3. `min_rr_ratio`와 `skip_entry`의 정책 결정
   - 현재: 전략별 최소 RR은 최종 하드 게이트가 아니다.
   - 선택지 A: 현재 유지. 문서에는 경고/메타데이터로 표기.
   - 선택지 B: 강제 정책. `queue_worker`가 `skip_entry` 또는 `effective_rr < min_rr_ratio`를 hard cancel로 소비하도록 수정.

### P1. 문서 정확성 보완

1. "전략별 최소 RR"을 "실제 하드 취소 RR 0.8"과 분리한다.
2. `rr_quality_bucket` 기준표를 추가한다: hard_cancel, caution, acceptable, strong.
3. 자동 신호 Claude(`analyzer.py`)와 수동 `/claude` 분석(`claude_analyst.py`)을 분리한다.
4. Claude TP1/SL 미반환 시 규칙 TP/SL fallback 경로를 추가한다.
5. Claude TP2와 `adjusted_target_pct`, `adjusted_stop_pct`가 현재 자동 실행 RR 재계산에 쓰이지 않는다고 명시한다.
6. `rr_basis`는 DB 컬럼이 아니라 payload 성격임을 명시한다.
7. 저장 테이블별 반영 위치를 추가한다: `trading_signals`, `trade_plans`, `position_state_events`, `ai_cancel_signal`, `rule_cancel_signal`.
8. cancel reason taxonomy와 저장 위치를 표로 추가한다.

### P2. 운영 문서 보완

1. freshness 기준 수치 추가:
   - `hoga`: caution 1초, cancel 2초
   - `tick`: caution 3초, cancel 5초
   - `strength`: caution 5초, cancel 10초
   - `vi_active`: caution 3초, cancel 5초
   - `vi_released`: caution 10초, cancel 20초
2. missing timestamp는 즉시 cancel이 아니라 `missing` 상태임을 명시한다.
3. 주요 Redis key 추가:
   - `pipeline_daily:{date}:{strategy}`
   - `status:decisions_10m:{strategy}:{action}`
   - `telegram_queue`
   - `ai_scored_queue`
   - `error_queue`
   - `ws:py_heartbeat`
   - `claude:daily_calls:{YYYYMMDD}`
   - `claude:daily_tokens:{YYYYMMDD}`
4. 장애별 1차 조치 runbook 추가:
   - `AI_UNAVAILABLE` 급증: API key/env, 네트워크, JSON parse, `error_queue` 확인
   - `FRESHNESS_STALE` 급증: websocket-listener health, Redis `updated_at_ms`, Kiwoom WS 연결 확인
   - `AI_DAILY_LIMIT`: `MAX_CLAUDE_CALLS_PER_DAY`, Redis daily calls key 확인

### P3. 문서 사용성 보완

1. 문서 초반에 독자별 사용 목적을 추가한다.
2. 전략 코드명, 한글명, 매매유형 색인표를 추가한다.
3. RR 계산 숫자 예시를 추가한다.
4. `raw_rr`, `single_tp_rr`, `effective_rr`, `rr_ratio`, `skip_entry`, `rr_skip_reason` 용어 정의표를 추가한다.
5. Mermaid 또는 의사결정 표로 ENTER/CANCEL 흐름을 시각화한다.
6. 전략별 섹션 앞에 요약 표를 추가한다.
7. 기술 용어집을 추가한다: ATR, Fib, MA, Bollinger, swing high/low, 1R, trailing activation.

## 4. 기능 개선 후보 상세

### 4.1 Claude RR override 후 action 재동기화

현재 확인된 흐름:

1. `enriched` 생성 시 `action` 지역 변수 값이 들어간다.
2. `_apply_claude_rr_override(enriched)`가 Claude TP/SL 기준 RR을 재계산한다.
3. RR이 0.8 미만이면 `enriched["action"] = "CANCEL"`로 바뀐다.
4. 이후 `push_score_only_queue()`는 `enriched`를 사용하므로 CANCEL이 나갈 수 있다.
5. 하지만 DB 저장, `confirm_open_position()`, metrics는 지역 변수 `action`을 계속 본다.

권장 수정:

```python
enriched = _apply_claude_rr_override(enriched)
action = enriched.get("action", action)
confidence = enriched.get("confidence", confidence)
cancel_reason = enriched.get("cancel_reason")
display_reason = _resolve_display_reason(action, enriched.get("ai_reason", reason), cancel_reason)
enriched["ai_reason"] = display_reason
```

실제 수정 시 metrics와 cancel_type 재분류까지 함께 점검해야 한다. Claude RR override로 인한 취소는 `cancel_type`을 `RR_TOO_LOW` 또는 별도 `CLAUDE_RR_TOO_LOW`로 남기는 편이 감사에 유리하다.

### 4.2 최종 TP/SL 후 RR 재계산

현재 위험:

- `_finalize_swing_result()`에서 TP1 최소 3% 보정
- MACD 약화 시 TP1/TP2 보수화
- 이후 `_consolidate_single_tp()`는 TP2가 있는 경우만 RR을 다시 계산
- TP2가 없거나 MACD guard로 TP1만 바뀐 경우 RR이 stale일 수 있다.

권장 수정:

- `_finalize_swing_result()`는 가격 보정만 담당한다.
- `calc_tp_sl().finalize()`의 마지막 단계에서 모든 전략에 대해 현재 `tp1_price`, `sl_price` 기준 RR을 재계산한다.
- 이후 `_apply_policy_metadata()`가 `raw_rr`, `single_tp_rr`, `effective_rr`, `skip_entry`, `rr_skip_reason`을 최종값 기준으로 기록한다.

## 5. 결론

현재 문서는 전략별 TP/SL 계산 기준을 상세히 담고 있지만, 다중 검토 결과 다음 두 가지 축의 보완이 필요하다.

1. 문서 보완: 실제 하드 게이트와 경고 기준을 분리하고, 운영자가 cancel reason과 저장 위치를 추적할 수 있게 해야 한다.
2. 기능 보완: Claude RR override 후 action 불일치 가능성과 최종 TP 보정 후 RR 재계산 누락은 실제 매매/저장 정합성에 영향을 줄 수 있어 우선 수정 대상이다.

가장 먼저 처리할 순서는 다음이 합리적이다.

1. `queue_worker.py` action 재동기화 버그 수정
2. `tp_sl_engine.py` 최종 RR 재계산 보강
3. 원 문서에 RR 기준/Claude 경로/운영 취소 분류 보완
4. 전략별 요약표와 운영 runbook 추가
