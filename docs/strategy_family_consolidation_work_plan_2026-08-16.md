# 16개 전략 → 7개 전략군 통합 작업계획서

- 작성일: 2026-08-16
- 상태: 구현·전체 회귀·Docker 실전 canary 배포 완료, 5거래일 관찰 진행
- 범위: `api-orchestrator`, `ai-engine`, `websocket-listener`, `telegram-bot`, PostgreSQL, Redis, Kiwoom/Toss 조회 계약
- 배포 원칙: 구현·테스트·롤백 리허설 완료 후 Docker 실전 canary로 배포한다. 전용 shadow 배포는 하지 않되 dual-score 계측은 유지한다.

### 배포 기록

- 배포 시각: 2026-08-16 23:37~23:38 KST
- 적용 DB: Flyway V56, 기존 `strategy` 보존 및 G family·version·source 계보 additive backfill 4,064건 확인
- 활성 플래그: lineage=true, shadow-scoring=true, live-routing=true. 여기서 shadow-scoring은 비교 관측값일 뿐 주문 모드는 live다.
- 전체 회귀: AI engine 1,108 passed, WebSocket 99 passed, Java 전체 test 성공, Telegram formatter 36 + limiter 22 passed
- 복구점: `backups/strategy-family-live-canary-20260816-2340/`의 PostgreSQL custom archive, Redis RDB, 배포 전 `.env`, Git HEAD, 이미지 목록
- 이미지 롤백 tag: API/AI/Telegram 각각 `pre-family-20260816`
- 카나리 거래일: KRX 개장일 기준 첫 5일. 2026-08-17은 광복절 대체휴일이므로 예상 관찰일은 8월 18·19·20·21·24일이며 실제 세션 상태로 최종 판정한다.

## 1. 결정 요약

16개 기존 전략을 삭제하거나 번호를 재사용하지 않고, 외부 운용 단위인 7개 `family_id` 아래에 영구적인 `setup_id`로 보존한다.

| 신규 No | 신규 전략군 코드 | 한글명 | 기존 setup_id | 통합 성격 |
|---|---|---|---|---|
| G01 | `SESSION_EVENT` | 세션·이벤트 | S1, S2, S12 | 공통 오케스트레이션만 통합 |
| G02 | `FLOW_TREND` | 수급추세 | S3, S5, S11 | 후보·수급 피처·확증 통합 |
| G03 | `ACCUMULATION_CONFIRM` | 축적확인 | S16 | 독립 상태기계, G02/G05 보조 확증 가능 |
| G04 | `TREND_PHASE` | 추세단계 | S8, S9, S15 | 형성→눌림→재가속 상태 통합 |
| G05 | `STRUCTURAL_BREAKOUT` | 구조돌파 | S7, S10, S13 | 차트·돌파·실행품질 엔진 통합 |
| G06 | `INTRADAY_THEME_MOMENTUM` | 장중급등·테마 | S4, S6 | 장중 위험예산만 공유, setup 규칙 분리 |
| G07 | `REVERSAL_BOUNCE` | 역추세반등 | S14 | 독립 역추세 논리 |

`strategy` 컬럼과 기존 S코드는 과거 호환을 위해 즉시 덮어쓰지 않는다. 목표 계약은 다음과 같다.

```text
family_id=G04
family_name=TREND_PHASE
setup_id=S9_PULLBACK_SWING
setup_version=s9_vNext
family_policy_version=family_v1
```

## 2. 조사 범위와 확인된 제약

### 2.1 실행·점수·청산

- `strategy_runner.py`에는 S1, S3~S16의 시간표가 있고 S2는 `vi_watch_worker`의 이벤트 경로다. G01을 하나의 스케줄 함수로 만들면 안 된다.
- 현재 중복키는 전략별 `scanner:dedup:{strategy}:{stk_cd}`다. DB 활성 포지션 검사도 있지만, 복수 전략 신호의 확증·우선순위를 표현하는 family arbitration은 없다.
- `strategy_meta.py`의 RR hard gate와 `tp_sl_engine.py`의 전략 정책에 수치 차이가 있다. 통합 구현 전에 하나의 버전된 정책 레지스트리로 수렴해야 한다.
- `scorer.py`는 전략별 서로 다른 점수 범위와 보너스를 더한 뒤 0~100으로 제한한다. 현재 원점수의 10점이 모든 전략에서 같은 증거강도를 뜻하지 않는다.
- Claude의 `HOLD`는 높은 AI 점수만으로 `ENTER`로 자동 승격되지 않는다. 새 설계도 이를 유지한다.
- TP1 처리 주석과 실제 포지션 종료 동작이 어긋날 수 있다. 부분청산 설계를 적용하기 전에 `ACTIVE → PARTIAL_TP → CLOSED` 런타임 검증이 필요하다.

### 2.2 데이터·API

- Kiwoom은 토큰, KRX/NXT 실시간 `0B` 체결·`0D` 호가·`0H` 예상체결·`1h` VI와 전략별 REST 랭킹/차트의 기준 소스다.
- Toss는 현재 조회·분석 전용이다. 후보 랭킹 보강, 더 완전한 일봉 전체 대체, 시장 지수/투자자 수급, 종목별 공매도·신용·대차·매수 유의사항에 적합하다.
- Toss REST는 Kiwoom 실시간 체결과 호가를 대체하지 않는다. Toss 주문·계좌 API는 이번 범위 밖이며 도입하지 않는다.
- Toss 토큰 발급 주체는 Java 단독이어야 한다. Python은 Redis `toss:token`을 읽기만 한다.
- Kiwoom HTTP 200도 본문 오류일 수 있으므로 `return_code`와 `error`를 검증해야 한다.
- Kiwoom 캔들과 Toss 캔들을 부분 봉 단위로 섞지 않는다. Toss가 더 완전할 때 동일 시계열 전체를 교체하고 `data_source`를 기록한다.

### 2.3 영속성·전달

영향 대상은 `trading_signals`, `signal_score_components`, `trade_plans`, `trade_outcomes`, `strategy_daily_stats`, `strategy_param_history`, 후보 이력, Redis 후보 풀/큐, Telegram formatter와 관리 API다. 모든 producer/consumer가 새 필드를 모르는 기간을 고려해 additive migration과 dual-read/write가 필요하다.

현재 `trading_signals.strategy` CHECK와 Java `StrategyType`은 기존 S literal을 전제로 한다. G01~G07을 그 컬럼에 바로 쓰면 insert 실패 또는 역직렬화 실패가 날 수 있으므로, 기존 `strategy`에는 primary setup을 유지하고 별도 `strategy_family`를 추가하는 schema-first 전환이 필수다.

또한 전략 카탈로그가 중앙화되어 있지 않다. `candidates_builder.py`와 `claude_analyst.py` 일부 숫자 범위 순회가 `range(1, 16)` 형태여서 S16이 빠질 수 있는 반면, 일부 Java scheduler는 S1~S16을 명시한다. 구현 전 `StrategyCatalog` 단일 소스를 도입하고 다음 소비자를 전수 대조한다.

- 후보 생성·live reprioritize·watchlist
- scanner schedule·manual run·S2 event worker
- prompt/persona/threshold·Toss swing scope
- day/swing dedup TTL·position sizing·overnight·position monitor
- DB CHECK/enum/DTO/filter·성과 및 cleanup scheduler
- Redis status/pipeline key·Telegram filter/formatter·대시보드

## 3. 트레이더 자문·토론 결과

### 3.1 합의

1. 7개 번호는 기존 S번호와 충돌하지 않는 G01~G07을 사용한다.
2. 기존 전략은 `setup_id`로 영구 보존한다. 과거 데이터의 일괄 재분류는 금지한다.
3. setup hard gate를 먼저 통과한 경우에만 family score를 계산한다.
4. 복수 setup 충족은 주문 수량이나 점수의 단순 합산 근거가 아니다.
5. 동일 데이터 계보의 확증은 상관 할인한다. 두 번째 setup은 최대 +4, 세 번째는 최대 +2이며 총 확증 보너스는 +8 이하다.
6. 필수 Kiwoom 실시간 데이터 결측은 `BLOCK`; 보조 Toss 결측은 `DEGRADED`와 무가점이다.
7. TP/SL은 family 평균이 아니라 승리한 setup의 시장가설 무효화선과 저항 구조를 사용한다.

### 3.2 반대 의견과 해소

- G01의 S1·S2·S12는 시간과 overnight 정책이 달라 직접 합치기 어렵다. 따라서 family는 세션 라우터와 위험예산만 공유한다.
- G06의 S4와 S6도 발생 원인이 다르다. 동일 테마·동일 종목의 장중 모멘텀 중복 노출을 통제하기 위한 묶음이며 점수식은 setup별이다.
- G03과 G07은 사실상 독립 전략이다. 7개 운영 카탈로그를 유지하되 다른 family의 평균 점수에 흡수하지 않는다.

## 4. 공통 의사결정 계약

### 4.1 처리 순서

```text
raw universe
→ source validation/freshness
→ setup candidate gate
→ setup hard gate
→ family feature normalization
→ family rule score
→ TP/SL and cost-adjusted effective RR hard gate
→ stock-level portfolio arbitration
→ AI review
→ ENTER | WATCH | CANCEL
→ plan/order lineage and outcome measurement
```

AI는 후보 생성, 가격 보정, hard gate 우회 또는 주문 수량 확대 권한이 없다.

### 4.2 공통 rule score 100점

| 컴포넌트 | 배점 | 의미 |
|---|---:|---|
| `setup_edge` | 35 | setup 고유 진입 근거 |
| `execution_quality` | 20 | 체결강도, 호가, 스프레드, VWAP, 추격 위험 |
| `regime_timing` | 15 | 장세·세션·시간대 정합성 |
| `liquidity_data_quality` | 10 | 거래대금·봉 완전성·freshness·source 상태 |
| `risk_structure` | 20 | 구조무효화선, 저항 여유, 변동성, 유의종목 위험 |

규칙:

- 각 컴포넌트는 범위를 넘지 못하게 개별 clamp한다.
- hard reject 사유는 음수 점수로 상쇄하지 않고 별도 `blocking_reasons`로 처리한다.
- 결측 필수 필드는 0점이 아니라 `BLOCK`이다.
- 선택 필드 결측은 가점하지 않고 `degraded_reasons`에 기록한다.
- `rule_score = sum(components) + confirmation_bonus`, 최종 0~100 clamp.
- `confirmation_bonus <= 8`; 같은 source/indicator lineage면 상관 할인한다.

### 4.3 AI 점수와 최종 판정

- AI 입력 전 최소 rule threshold: G01 70, G02 70, G03 78, G04 70, G05 74, G06 72, G07 75.
- `final_score = round(0.70 × rule_score + 0.30 × ai_score, 2)`는 표시·랭킹용이다.
- ENTER는 산술점수만으로 결정하지 않는다. `hard_gates_passed=true`, effective RR 충족, 필수 freshness 충족, AI `ENTER`, 포트폴리오 arbitration 통과가 모두 필요하다.
- AI `HOLD`는 항상 `WATCH`, AI 오류/timeout/JSON 오류는 `CANCEL` 또는 기존 fail-closed 정책을 따른다.
- G03도 최종 실전 canary 대상이지만 상태전이·최소관찰일·RR·실행품질 hard gate를 생략하지 않는다.

## 5. 전략군별 상세 설계

### 5.1 G01 `SESSION_EVENT`

setup별로 정책을 선택하며 단일 TP/SL을 만들지 않는다.

| setup | 핵심 rule 35점 | SL | TP | 최소 effective RR | 시간청산 |
|---|---|---|---|---:|---|
| S1 | 갭 품질 12, 예상체결 지속 8, 첫 1~3분 안착 10, VWAP 5 | 첫 3분 저가/VWAP/ATR 중 가장 가까운 유효 무효화선, 최대 -2.2% | 장중 첫 저항 TP1, 다음 매물대 TP2 | 1.50 | 30분 또는 당일 종가 |
| S2 | VI 유형·거래량 12, 눌림 깊이 8, 재탈환 10, 2차 VI 위험 5 | VI 눌림 저점/해제가 기준, 최대 -2.0% | VI 발동가·직전 고점 TP1, 확장저항 TP2 | 1.80 | 15분 또는 당일 종가 |
| S12 | 종가 수급 12, 체결강도 8, 종가 위치 8, 익일 갭 여지 7 | 당일 구조저점/ATR·MA 지지 | 익일 첫 저항 TP1, 스윙저항 TP2 | 1.50 | 익일 오전 |

Kiwoom primary: S1 `ka10029/0H/0B/0D/ka10080`, S2 `1h/ka10054/0B/0D/ka10055`, S12 `ka10032/ka10065 계열/0B/0D`. Toss는 장 운영 캘린더와 유의사항 보조만 사용하며 실시간 진입 확증을 대신하지 않는다.

### 5.2 G02 `FLOW_TREND`

- setup edge: 동시 수급 12, 지속성 8, 프로그램/투자자 교차확인 8, 가격 동행 7.
- S3/S5/S11이 같은 종목에서 겹치면 한 신호에 `confirmed_by`로 합친다.
- SL: MA20, 최근 스윙 저점, 수급 유입 기준봉 저점 중 가설을 가장 먼저 무효화하는 유효선. 임의로 더 넓은 SL 선택 금지.
- TP1: 가장 가까운 유효 스윙 저항/볼린저 상단. TP2: 다음 고점 또는 1.272 확장.
- 최소 effective RR: S3 1.50, S5 1.50, S11 1.55.
- trailing activation: +1R, overnight 허용, 재진입은 새 수급 snapshot과 cooldown을 요구한다.
- Kiwoom: `ka10065`, `ka10063`, `ka90003~05/08/09/13`, `ka10035`, `ka10131`, `0w`, `0B/0D`.
- Toss: investor-trading/program-trades로 일별 교차검증, 공매도·신용·대차·warnings로 risk component만 보정한다. 당일 Kiwoom 수급과 충돌하면 자동 ENTER하지 않고 `SOURCE_CONFLICT` WATCH.

### 5.3 G03 `ACCUMULATION_CONFIRM`

- 상태: `ACCUMULATING → ARMED → TRIGGERED`; 최소 관찰일을 생략하지 않는다.
- rule 35점: 박스·저점상승 12, 상승/하락 거래량 구조 8, 누적 수급 10, 트리거 근접 5.
- SL: 박스 하단과 최근 구조저점 중 위험한도를 만족하는 무효화선.
- TP1: 박스 높이 0.5배 확장 또는 +5% 중 구조적으로 유효한 가까운 값. TP2: 박스 높이 1배 또는 다음 저항.
- 최소 effective RR: shadow 1.60 기록, `CONFIRM_BUY` 후보는 1.80.
- 실전 canary에서 상태전이와 최소관찰일을 통과한 TRIGGERED만 진입 가능하다. 단순 ARMED/ACCUMULATING은 계속 WATCH다.
- Kiwoom: 일봉, 체결강도, 호가, 투자자·프로그램 수급. Toss: 일봉 완전성 폴백, 장기 수급/공매도/신용/대차/warnings.

### 5.4 G04 `TREND_PHASE`

- 상태: `FORMING(S8) → PULLBACK_READY(S9) → REACCELERATING(S15)`; 모든 단계를 반드시 거칠 필요는 없지만 경로를 기록한다.
- setup edge: MA/크로스 구조 10, 눌림 품질 10, 모멘텀 재정렬 10, 다중시간대 정합 5.
- SL: 선택 setup의 MA/매수존/최근 스윙 저점 무효화선.
- TP1: 근접 스윙저항/볼린저 상단, TP2: 다음 구조저항 또는 fib 확장.
- 최소 effective RR: S8 1.50, S9 1.55, S15 1.55.
- 동일 지표를 재사용한 S8+S15는 독립 확증으로 전점 가산하지 않는다.
- Kiwoom: `ka10027`, `ka10032`, `ka10081`, `ka10080`, `0B/0D`. Toss: ranking 보강, 완전 일봉 폴백, 스윙 종목 위험.

### 5.5 G05 `STRUCTURAL_BREAKOUT`

- setup edge: 구조 돌파 12, 거래량 확장 8, 돌파 유지 8, 상단 여유 7.
- SL: S7 구름/기준선, S10 돌파 전 고점·MA20, S13 박스 상단 재이탈/박스 내부 구조선.
- TP1: 가장 가까운 매물대·스윙저항, TP2: 신고가 가격발견이면 ATR/fib 확장.
- 최소 effective RR: S7 1.80, S10 1.55, S13 1.55. S13 trailing은 +1.5R.
- 윗꼬리, 돌파선 재이탈, 매도벽, 과도한 스프레드, 추격 위험은 hard gate다.
- Kiwoom: S7 일봉·일목/VWAP, S10 `ka10016/ka10018/ka10025`, S13 `ka10023/ka10055`, 공통 `ka10080/81/0B/0D`.
- Toss: ranking으로 universe 보강, 일봉 전체 폴백, warnings/공매도·신용·대차 risk. 가격 돌파 사실은 Kiwoom 실시간으로 재확인한다.

### 5.6 G06 `INTRADAY_THEME_MOMENTUM`

- S4와 S6은 동일 점수식을 쓰지 않는다. 동일 종목·동일 테마 위험예산과 실행품질만 공유한다.
- S4 edge: 장대양봉 구조 12, 거래량 8, 다음 봉 안착/재돌파 10, 소진 없음 5.
- S6 edge: 테마 강도 10, 대장 생존 8, 후발 위치 8, 순환 유입 9.
- SL: S4 기준봉/VWAP/ATR, 최대 -2.5%; S6 테마/개별 구조저점, 최대 -3.0%.
- TP: 당일 근접 저항 TP1, 테마/기준봉 확장 TP2.
- 최소 effective RR: S4 1.70, S6 1.60. overnight와 재진입은 기본 금지.
- Kiwoom: `ka10023`, `ka90001/02`, `ka10080`, `0B/0D`. Toss ranking은 보조 후보로만 사용하고 테마 대장/후발 관계는 Kiwoom으로 확정한다.

### 5.7 G07 `REVERSAL_BOUNCE`

- setup edge: 과매도 위치 10, 복수 오실레이터 탈출 10, 장기추세 생존 8, 실제 매수세 회복 7.
- RSI가 낮다는 이유만으로 진입하지 않는다. 반등 조건 2개 이상과 체결/호가 회복이 필요하다.
- SL: 최근 패닉 저점/매수존 하단/ATR 무효화선.
- TP1: MA20·볼린저 중심·근접 매물대 중 첫 저항, TP2: 상단 밴드/다음 스윙저항.
- 최소 effective RR 1.50, trailing activation +1.2R.
- 급락장 신규진입 금지; bear 장세에서도 시장 폭과 회복 신호가 없으면 WATCH/CANCEL.
- Kiwoom: `ka10027` 하락풀, `ka10081`, `0B/0D`. Toss: 신용·대차·공매도·정리매매/투자경고를 강한 위험 필터로 사용한다.

## 6. TP/SL/RR 공통 산출 규칙

1. `entry_price`는 분석 시세가 아니라 주문 가능한 최신 호가를 기준으로 산출하고 source timestamp를 기록한다.
2. SL 후보는 setup 구조선, ATR 보조선, 최대손실 cap을 함께 계산한다. 구조를 살리려고 cap보다 넓히면 CANCEL한다.
3. TP1은 가장 가까운 유효 저항, TP2는 다음 구조저항이다. 고정 퍼센트는 구조 데이터가 없을 때도 자동 ENTER용 폴백으로 쓰지 않는다.
4. `raw_rr`, `single_tp_rr`, 비용·슬리피지 반영 `effective_rr`를 모두 저장한다.
5. KOSPI/KOSDAQ 비용, 예상 스프레드, 시장충격을 반영한다.
6. 동일 종목 복수 setup이면 SL을 평균내지 않는다. 최종 선택된 `primary_setup_id`의 SL을 쓰며, 다른 setup과 충돌하면 WATCH한다.
7. TP1 부분청산 목표는 50%, 잔여 50%는 breakeven/구조 trailing을 설계 기본값으로 하되, 실제 partial 상태기계가 검증되기 전에는 활성화하지 않는다.

## 7. AI 스코어링 프롬프트 계약

시스템 프롬프트 핵심:

```text
당신은 한국 주식 트레이딩 리스크 심사역이다. 입력된 family와 setup의 규칙 점수,
원천 데이터 시각, TP/SL/RR, 장세, 실행품질만 평가한다. 데이터에 없는 사실을 만들지 않는다.
hard gate를 우회하거나 TP/SL을 더 유리하게 조작하지 않는다. 필수 데이터 결측,
source 충돌, stale, effective RR 미달이면 ENTER를 반환하지 않는다. 복수 setup은
독립 데이터 계보일 때만 제한적으로 확증한다. HOLD는 WATCH이며 자동 ENTER 승격이 아니다.
반드시 지정 JSON 스키마만 반환하고 모든 설명은 한국어로 쓴다.
```

필수 입력:

- identity: `family_id/name`, `primary_setup_id`, `matched_setup_ids`, 정책 버전
- market: KST 시각, session, market, regime, breadth, index/flow source와 age
- price/execution: bid/ask, spread, depth, strength, VWAP, chase risk와 source age
- setup features: 원시값, 단위, source, timestamp, freshness 상태
- scoring: component별 점수와 hard/degraded 사유
- plan: entry, TP1/TP2/SL, 각 method, effective RR, 비용 가정
- Toss risk: warnings, short/credit/lending와 관측일
- portfolio: 기존 포지션, 종목/테마 노출, cooldown

필수 출력:

```json
{
  "action": "ENTER|HOLD|CANCEL",
  "ai_score": 0,
  "confidence": "HIGH|MEDIUM|LOW",
  "reason": "한국어 근거",
  "cancel_reason": null,
  "validated_family_id": "G01",
  "validated_setup_id": "S1_GAP_OPEN",
  "independent_confirmations": [],
  "data_quality": "OK|DEGRADED|BLOCKED",
  "risk_flags": [],
  "tp1_price": 0,
  "tp2_price": 0,
  "sl_price": 0,
  "effective_rr": 0.0
}
```

AI가 제안한 가격은 규칙 엔진 범위 안의 검증값만 채택하며, 가격이 잘못된 tick/상하한 범위이거나 RR을 악화시키면 규칙 계획을 유지하거나 CANCEL한다.

## 8. 데이터 소스 배합 정책

| 목적 | Primary | Secondary | 충돌/결측 정책 |
|---|---|---|---|
| 실시간 현재가·체결·호가 | Kiwoom WS 0B/0D/0H | Kiwoom REST snapshot | stale이면 BLOCK; Toss로 자동진입 금지 |
| VI | Kiwoom 1h + ka10054 | Toss warning | Toss는 보조 경고만 |
| 전략 raw universe | Kiwoom 전략별 ranking | Toss ranking | 합집합 후 동일 품질 gate, source 기록 |
| 일봉 | Kiwoom ka10081 | Toss candles | 부분병합 금지, 더 완전한 전체 시계열만 대체 |
| 분봉 | Kiwoom ka10080/WS | Toss 1분봉 진단 | 진입 직전 Kiwoom 확인 필수 |
| 시장지수·시장수급 | Toss market indicators | Kiwoom 업종/투자자 API | source age와 시장구분 일치 검사 |
| 종목 수급 | Kiwoom intraday | Toss daily trend | 당일/일별 horizon을 섞지 않음 |
| 공매도·신용·대차·warnings | Toss | Kiwoom 가용 위험 API | stale이면 무가점, severe warning은 BLOCK 후보 |
| 주문·체결 사실 | 기존 승인된 실행 경로 | 없음 | Toss 주문 API는 본 계획 범위 밖 |

freshness 목표 초안: 현행 경계는 hoga caution/cancel 1초/2초, tick 3초/5초, strength 5초/10초, active VI 3초/5초, released VI 10초/20초이므로 이를 회귀 기준선으로 먼저 고정한다. expected, 분봉, 후보 meta, 일봉 및 Toss 위험정보는 별도 source-age 계약을 확정한다. 단순 TTL 존재를 freshness로 보지 않는다.

## 9. 포트폴리오 중복·충돌 정책

- dedup 키 목표: `signal:family:{family_id}:{stk_cd}:{direction}`와 별도 stock-level reservation.
- 동일 종목 ENTER는 하나의 `primary_setup_id`만 주문 계획을 소유한다.
- 우선순위: hard gate 품질 → effective RR → execution quality → 독립 확증 → rule score.
- 기존 활성 포지션 `ACTIVE/PARTIAL_TP/OVERNIGHT`가 있으면 새 setup은 증거 업데이트로 저장하고 신규 주문하지 않는다.
- G04/G05 동시 충족 등 family 간 충돌도 포지션 하나로 합치고 `confirmed_by_family_ids`를 저장한다.
- 같은 테마·섹터 노출 한도와 장중/overnight 위험예산을 별도로 둔다.

## 10. 구현 작업 패키지

### WP-00 기준선·동결

- clean/dirty status, 현재 테스트, 전략별 20거래일 신호·reject·timeout·source-age·성과 스냅샷.
- 후보→신호→판정→주문→ACK→fill→exit lineage 결측률 확인.
- 산출물: baseline JSON/SQL, 회귀 fixture, 정책 freeze tag.

### WP-01 정책 레지스트리

- G01~G07와 setup mapping, score/TP/SL/RR/version을 단일 schema로 정의.
- `strategy_meta`와 `tp_sl_engine` RR 불일치를 실패 테스트로 고정 후 수렴.
- 숫자 범위 순회와 분산된 enum/map을 중앙 `StrategyCatalog`로 치환하는 영향 목록 작성. S16 포함 16/16 회귀를 먼저 만든다.

### WP-02 additive 데이터 모델

- `family_id`, `family_name`, `primary_setup_id`, `matched_setup_ids`, `family_policy_version`, `data_lineage`, `blocking_reasons`, `degraded_reasons`, `final_score` 추가 설계.
- enum/check constraint는 dual-write 완료 전 강제하지 않는다.

### WP-03 후보·API 계층

- 전략별 Kiwoom API 공유 fetch/cache, Toss supplement, source status와 `updated_at_ms` 표준화.
- API별 rate limit·budget·deadline·fallback matrix 테스트.

### WP-04 family scanner/router

- 기존 setup scanner를 먼저 그대로 호출하는 compatibility adapter.
- G01 event router, G02 flow intersection, G04 state, G05 breakout, G06 intraday exposure arbitration.

### WP-05 정규화 rule scorer

- 공통 5개 컴포넌트 100점과 setup별 35점 rubric 구현.
- 기존 점수와 신규 점수를 shadow dual-compute하고 분포/순위/판정 차이를 기록.

### WP-06 TP/SL/RR

- 구조 후보·비용·tick rounding·상하한·최대손실·시간청산을 단일 버전 계약으로 계산.
- TP1 partial 처리의 실제 상태전이를 실패 테스트부터 복구.

### WP-07 AI 프롬프트·검증

- family 공통 prompt + setup rubric, JSON Schema, price/RR post-validation.
- prompt injection 성격의 종목명/뉴스 문자열은 데이터로 격리.

### WP-08 portfolio arbitration·dedup

- stock/family/setup 예약 순서, active status 확인, 동일 종목·테마 위험한도, 원자적 Redis/DB 정책.

### WP-09 소비자 전환

- DB writer/reader, API DTO, 성과 집계, Telegram formatter, `/strategy`, `/perf`, 대시보드 dual-read.
- 기존 S별 조회와 신규 G별 조회를 동시에 제공.

### WP-10 shadow 검증

- 배포 후 5거래일 live canary를 운영하고, 각 setup 독립 표본과 bull/sideways/bear 및 KOSPI/KOSDAQ 결과를 가능한 범위에서 분리한다.
- 누락 0, 중복주문 0, 필수 stale ENTER 0, lineage 결측 0을 요구.

### WP-11 단계적 활성화·롤백

- 사전 리플레이·dry-run은 수행하되 배포 모드는 live canary다. 기존보다 주문 비중을 키우지 않고 kill switch를 즉시 사용할 수 있어야 한다.
- G03/G07은 마지막에 검토. 기존 S 경로 kill switch와 1-command 논리 롤백을 보존.

### WP-12 문서·운영 인계

- 환경변수, Redis/DB schema, API, Telegram 예시, 런북, 장애/rollback, 데이터 보존 정책 갱신.

## 11. 테스트와 승인 게이트

### 정적·단위

- 모든 S1~S16이 정확히 하나의 G family에 매핑된다.
- 알 수 없는 family/setup은 fail closed.
- score component 합계·clamp·상관 할인·결측 정책 경계값.
- TP/SL tick rounding, 상하한, 수수료/슬리피지, RR 경계값.
- Toss/Kiwoom source 변환과 부분 캔들 혼합 금지.

### 통합·리플레이

- 16개 setup fixture를 후보부터 Telegram payload까지 리플레이.
- S2 event 경로, S12 overnight, TP1 partial, 재시작·중복·Redis 장애·API 200 오류 본문.
- 동일 종목 2~4 setup 동시 충족 시 주문 계획 1개.
- ACTIVE/PARTIAL_TP/OVERNIGHT 상태에서 재진입 없음.

### 승격 기준

- 데이터 lineage/family/setup 누락 0건.
- 중복 신규 주문 0건.
- 필수 stale/invalid source ENTER 0건.
- hard gate 우회 0건.
- 기존 대비 비용 반영 기대값·PF·MAE가 열화하지 않고 신뢰구간을 보고한다.
- 전략별 표본이 부족하면 `INSUFFICIENT_SAMPLE`이며 통합 성공으로 간주하지 않는다.
- 사용자 승인에 따라 운영 판단 창은 5거래일이다. 표본 수는 성공을 과장하지 않도록 그대로 보고하며, 5일 종료 시 기대값·PF·MFE/MAE·중복 감소·체결 품질이 기준 미달이면 즉시 롤백한다.
- 기대값 차이는 비용 반영 walk-forward와 95% bootstrap 신뢰구간으로 제시하고, AI 점수는 calibration error 또는 Brier score를 함께 본다.

## 12. 롤백·금지 규칙

- 레거시 S코드, 통계, 파라미터 이력 삭제 금지.
- 과거 row를 새 family 성과로 소급 덮어쓰기 금지.
- Toss 장애 시 Kiwoom hard gate 완화 금지.
- AI가 hard gate, SL cap, RR 미달을 우회하는 로직 금지.
- 병합 직후 AUTO_FULL 금지.
- 코드 테스트만으로 트레이딩 성과 검증 완료 선언 금지.

family 주문 라우팅은 feature flag로 즉시 차단할 수 있어야 한다. 중복 포지션, setup 계보 누락, stale ENTER, hard gate 우회, RR 미달 주문, family/setup exit 오적용은 각각 1건만 발생해도 즉시 rollback 조건이다. 주문 ACK/체결 매핑 누락률 0.5% 초과 또는 AI JSON 실패율 1% 초과도 rollback 검토 기준으로 둔다.

## 13. 완료 정의

구현은 다음이 모두 확인될 때만 완료다.

1. 16개 setup 보존과 7개 family 운용이 DB·Redis·API·Telegram·성과 집계에서 일치한다.
2. Kiwoom/Toss 데이터의 source, timestamp, freshness, fallback 사유가 신호까지 전파된다.
3. setup별 TP/SL/시간청산과 family arbitration이 리플레이로 검증된다.
4. 중복주문·stale ENTER·lineage 누락이 0이다.
5. shadow 성과와 기존 전략 대비표가 있으며 불충분 표본을 성공으로 포장하지 않는다.
6. kill switch와 레거시 경로 롤백이 실제 운영 리허설로 검증된다.

## 14. 현재 단계 결론

구현과 최종 Docker live canary가 승인됐다. 배포 전 전체 테스트·DB 백업·rollback 리허설과 실전 설정 preflight를 완료해야 하며, 5거래일 평가 후 유지 또는 롤백한다.
