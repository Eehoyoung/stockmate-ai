# StockMate G01~G07 통합 신호 파이프라인

- 기준일: 2026-08-17
- 상태: Docker live canary 운영 문서
- 기준 코드: `ai-engine`, `api-orchestrator`, `websocket-listener`, `telegram-bot`
- 선행 문서: `signal_pipeline_2026-07-26.html`, `strategy_family_consolidation_work_plan_2026-08-16.md`
- 정책 버전: `family_v1_2026_08_16` / `family_score_v1_2026_08_16` / `family_prompt_v1_2026_08_16`

> 이 문서는 설계 희망사항과 현재 런타임을 섞지 않는다. **현재 구현**은 코드로 확인된 동작이고, **권장 표시 확장안**은 후속 Telegram UI 변경안이다. G 번호는 운용 전략군이며 기존 S1~S16은 진입 논리·성과 귀속·프롬프트를 소유하는 불변 setup이다.

## 1. 이번 통합으로 달라진 신호의 의미

```text
Kiwoom/Toss 후보 수집
  → 기존 S setup hard gate
  → G family 계보·정규화 점수
  → 구조 기반 TP1/TP2/SL
  → 비용·슬리피지 반영 effective RR
  → 종목·family·포지션 원자적 중복 방지
  → setup persona + family guard AI 심사
  → ENTER | HOLD(WATCH) | CANCEL/BLOCK
  → Telegram → DB → 주문/ACK/fill → TP1/PARTIAL_TP → TP2/SL/시간청산
```

변경 핵심은 전략 수를 물리적으로 16개에서 7개로 줄인 것이 아니다. 후보와 위험을 G01~G07 단위로 조정하되, 실제 진입 근거·RR·청산·AI 전문성은 대표 S setup에 남는다. 복수 setup 충족은 `matched_setup_ids`와 `confirmed_by`로 보존되며 점수나 주문 수량을 단순 합산하지 않는다.

## 2. HOLD(관심종목)와 ENTER 메시지 폼

### 2.1 현재 구현에서 실제로 달라진 부분

일반 `formatSignal()` 메시지는 다음 계보를 추가 표시한다.

- `strategy_family`와 `strategy_family_name`
- `primary_setup_id`
- 두 개 이상이면 `confirmed_by` 또는 `matched_setup_ids`
- 기존 AI 점수·규칙 점수·TP1/TP2/SL·RR·기술지표·스윙 Toss 위험정보

이번 변경으로 별도 `formatHoldWatch()` 관심종목 알림에도 통합전략, 대표·확인 세부전략, 보유 유형, 시장, 1·2차 목표가, 손절가, 손익비, 데이터 출처와 관측 경과시간을 표시한다. 기간을 가진 프로그램·외국인·기관 및 Toss 위험 추이는 payload에 실제 시계열이 있을 때만 표시한다.

### 2.2 현재 판정 의미

| 표시 | 내부 의미 | 주문 가능 여부 | 후속 처리 |
|---|---|---:|---|
| `ENTER` | 모든 hard gate, freshness, RR, 포트폴리오 arbitration, AI ENTER 통과 | 가능 | 최신 Kiwoom 실행가능 호가로 주문 경로 진행 |
| `HOLD` | AI 또는 규칙의 WATCH 판단 | 불가 | 관심종목 모니터에서 조건 개선 추적 |
| `ENTER_CANDIDATE` | 빠른 후보 검토 단계 | 불가 | 사람이 확인할 후보이지 ENTER가 아님 |
| `CANCEL/BLOCK` | 데이터·규칙·RR·포지션·AI schema 중 하나 이상 실패 | 불가 | 실패 사유와 계보만 저장 |
| `HOLD_RELEASED` | 관심 조건이 개선되지 않아 관찰 종료 | 불가 | 별도 해제 알림 및 dedup 처리 |

AI `HOLD`는 점수가 높아도 자동 ENTER로 승격하지 않는다. 관심종목이 ENTER로 바뀌려면 새 snapshot으로 hard gate와 실행품질·RR을 다시 계산하고 AI가 ENTER를 반환해야 한다.

### 2.3 권장 확장 ENTER 폼

```text
✅ [ENTER] G05 구조돌파 / S13_BOX_BREAKOUT
종목: 예시종목 (123456) · 시장: 코스닥 · 보유 유형: 스윙형
대표 세부전략: S13 · 함께 확인된 세부전략: S10 / 독립 확인 +4 / 상관 할인 적용

점수: 규칙 82.0 · AI 78.0 · 종합 80.8
판정 상태: 필수조건 통과 · 데이터 정상 · 중복·노출 검사 통과
진입가: 10,000원 (출처 Kiwoom 최우선 매도호가 · 관측 후 430밀리초 경과)
1차 목표가: 10,600원 (+6.0%, 최근 매물대) · 50% 부분청산
2차 목표가: 11,200원 (+12.0%, 박스 높이 1배 확장) · 잔여 추적
손절가: 9,650원 (-3.5%, 박스 재진입 무효화선)
손익 계획: 기본 손익비 1.71 · 비용 반영 손익비 1.55 · 최소 기준 1.55

실행: 체결강도 128 · 호가비율 1.73 · 매수·매도 가격차 0.20% · 추격 위험 낮음
수급: 외국인 5D 증가 · 기관 3D 증가 · 프로그램 4/5구간 순매수
위험(T+1): 공매도율 2.1% ↘ · 신용잔고율 1.8% → · 대차잔고 3D ↘
경고: 없음 · Toss 관측일 2026-08-14 · 실시간 진입판정에는 미사용
장세: KOSDAQ bull · 지수 Toss age 32s / 종목 실시간 Kiwoom
무효화: 박스 상단 재이탈 또는 SL 도달
```

### 2.4 권장 확장 HOLD 폼

```text
⏸️ [HOLD/WATCH] G02 수급추세 / S5_PROG_FRGN
종목: 예시종목 (123456) · 유형: 스윙
현재가: 10,000원 · 관찰 만료: 14:00 또는 setup TTL
점수: 규칙 76.0 · AI 81.0 · 종합 77.5
보류 사유: 프로그램 순매수는 유지되나 비용 반영 손익비 1.37 < 최소 기준 1.50

조건부 계획: 1차 목표가 10,500 · 2차 목표가 11,000 · 손절가 9,650
필요 개선: 최우선 매도호가와 매수·매도 가격차 정상화, 진입가 9,920 이하 또는 유효 저항 상향
수급: 프로그램 최근 3구간 +,+,- · 외국인 당일 순매수
데이터: Kiwoom hoga OK 620ms · strength CAUTION 6.2s · Toss risk DEGRADED
주의: HOLD는 주문이 아니며 점수만으로 ENTER 승격되지 않음
```

이 확장안에서 “추이”는 최소 두 관측점 이상의 방향과 관측 기간이 있을 때만 `↗/→/↘`로 표시한다. 단일 snapshot을 추이로 표현해서는 안 된다.

### 2.5 사용자 Telegram 실제 출력 예시

아래 예시는 `formatter.js`에 전달되는 대표 payload를 기준으로 한 사용자 표시 형태다. 내부 필드명은 노출하지 않고 한국어 의미로 변환한다.

#### ENTER 알림

```text
📦 [S13_BOX_BREAKOUT] 예시종목 (123456)
통합전략: G05 구조돌파
대표 세부전략: S13_BOX_BREAKOUT · 스윙형
함께 확인된 세부전략: S13_BOX_BREAKOUT, S10_NEW_HIGH
박스권 상단 돌파 + 거래량 폭발

진입 판단: 진입 조건 통과
점수: 규칙 82.0점 · AI 78.0점 · 종합 80.8점
신뢰도: 높음 · 보유 유형: 스윙형
판정 상태: 필수조건 통과 · 데이터 상태 정상 · 중복·노출 검사 통과
진입가: 10,000원 · 출처 키움 실시간 · 관측 후 430밀리초 경과
1차 목표가: 10,600원 (+6.0%) · 산출 근거 최근 매물대
2차 목표가: 11,200원 (+12.0%) · 산출 근거 박스 높이 1배 확장
손절가: 9,650원 (-3.5%) · 산출 근거 박스 상단 재이탈
손익 계획: 기본 손익비 1.71 · 비용 반영 손익비 1.55 · 최소 기준 1.55
실행 상태: 체결강도 128% · 호가비율 1.73
추천 이유: 구조 돌파와 거래량 확장을 확인

진입 체크포인트
1. 진입가 부근에서 호가와 체결강도 유지 확인
2. 계획 비중 이내로 진입하고 손절가 기준 손실폭을 먼저 확정
3. 1차 목표가에서 일부 매도하고 2차 목표가까지 잔여분 추적
4. 손절가 이탈 시 전략 전제 훼손으로 대응
```

#### HOLD 관심종목 알림

```text
🔎 [조건부 진입 (관심종목)] S5_PROG_FRGN
종목: 예시종목 (123456)
통합전략: G02 수급추세
대표 세부전략: S5_PROG_FRGN · 스윙형
함께 확인된 세부전략: S5_PROG_FRGN, S11_FRGN_CONT
진입 관찰가: 10,000원 · 출처 키움 실시간 · 관측 후 620밀리초 경과
점수: 규칙 76.0점 · AI 81.0점 · 종합 77.5점
판정 상태: 필수조건 통과 · 데이터 상태 보조정보 부족 · 중복·노출 검사 통과
1차 목표가: 10,500원 · 산출 근거 최근 매물대
2차 목표가: 11,000원 · 산출 근거 다음 구조저항
손절가: 9,650원 · 산출 근거 수급 유입 구조선
손익 계획: 기본 손익비 1.43 · 비용 반영 손익비 1.37 · 최소 기준 1.50

관망 사유: 비용 반영 손익비 1.37이 최소 기준 1.50에 미달
조건이 개선되면 전체 조건을 다시 심사해 진입 알림으로 전환하거나 관심 해제로 안내합니다.
```

## 3. G01~G07 카탈로그와 보유 성격

| Family | 이름 | setup | 운용 성격 | 보유 분류 | family rule threshold |
|---|---|---|---|---|---:|
| G01 | 세션·이벤트 | S1, S2, S12 | 일정 공유 금지, 공통 orchestration만 | S1/S2 단기, S12 스윙·익일 | 70 |
| G02 | 수급추세 | S3, S5, S11 | 수급 피처·확증 공유 | 스윙 | 70 |
| G03 | 축적확인 | S16 | 상태기계 wrapper | 스윙 | 78 |
| G04 | 추세단계 | S8, S9, S15 | 형성·눌림·재가속 router | 스윙 | 70 |
| G05 | 구조돌파 | S7, S10, S13 | 구조·돌파·실행품질 공유 | 스윙 | 74 |
| G06 | 장중급등·테마 | S4, S6 | 장중 위험예산만 공유 | 단기, overnight 금지 | 72 |
| G07 | 역추세반등 | S14 | 독립 역추세 wrapper | 스윙 | 75 |

현재 중앙 카탈로그에서 day setup은 S1·S2·S4·S6이고 나머지는 기본 swing이다. G01처럼 서로 다른 보유주기를 가진 family에 family 공통 시간청산을 적용하면 안 된다.

## 4. setup별 RR·TP·SL·시간 정책

아래 RR은 live family routing에서 사용하는 목표 effective RR 하한이다. 장세별 multiplier는 대표 setup별로 적용하며 family 평균으로 덮어쓰지 않는다.

| G | setup | 유형 | effective RR | SL 산출 | TP1 / TP2 산출 | 시간·추적 |
|---|---|---|---:|---|---|---|
| G01 | S1 갭오픈 | 단기 | 1.50 | 첫 3분 저가·VWAP·5분 ATR 중 가까운 구조선, 손실 cap | 첫 장중 저항 / 다음 매물대 | 약 30분 또는 당일 종료 |
| G01 | S2 VI눌림 | 단기 이벤트 | 1.80 | VI 눌림 저점·해제가, 5분 ATR 보조 | VI 발동가·직전고점 / 확장저항 | 약 15분 또는 당일 종료 |
| G01 | S12 종가 | 스윙·익일 | 1.50 | 당일 구조저점·ATR·MA 지지 | 익일 첫 저항 / 다음 스윙저항 | 익일 오전 중심 |
| G02 | S3 기관외인 | 스윙 | 1.50 | 수급 유입봉 저점·MA20·swing low | 근접 swing/BB 상단 / 다음 고점·1.272 | +1R trailing, overnight 가능 |
| G02 | S5 프로그램외인 | 스윙 | 1.50 | 프로그램 유입 구조·MA20·swing low | 근접 저항 / 다음 구조저항 | 새 수급 snapshot 후 재진입 |
| G02 | S11 외인연속 | 스윙 | 1.55 | 연속 수급 가설 무효화선 | 근접 저항 / 다음 고점 | overnight 가능 |
| G03 | S16 축적확인 | 스윙 상태형 | 1.80 | 박스 하단·최근 구조저점·최대손실 cap | box 0.5x 또는 +5% / box 1.0x 또는 다음 저항 | ACCUMULATING→ARMED→TRIGGERED |
| G04 | S8 골든크로스 | 스윙 | 1.50 | MA20·매수존·swing low | swing/BB 저항 / 다음 구조저항 | 추세 형성 단계 |
| G04 | S9 눌림스윙 | 스윙 | 1.55 | MA5/지지박스/최근 저점 | 복귀 저항 / 다음 swing | PULLBACK_READY |
| G04 | S15 모멘텀정렬 | 스윙 | 1.55 | MA·ATR·구조저점 | 근접 저항 / fib·다음 저항 | REACCELERATING |
| G05 | S7 일목돌파 | 스윙 | 1.80 | 구름 상단·기준선·ATR | 매물대 / fib·ATR 확장 | 돌파 실패 시 즉시 무효 |
| G05 | S10 신고가 | 스윙 | 1.55 | 돌파 전 고점·MA20·ATR | 가격발견 첫 확장 / 다음 ATR·fib | 과확장·윗꼬리 차단 |
| G05 | S13 박스돌파 | 스윙 | 1.55 | 박스 상단 재이탈·박스 내부 구조선 | 근접 매물 / box·fib 확장 | +1.5R trailing |
| G06 | S4 장대양봉 | 단기 | 1.70 | 기준봉 저가·VWAP·5분 ATR, 손실 cap | 당일 저항 / 기준봉 확장 | 당일청산·재진입 제한 |
| G06 | S6 테마후발 | 단기 | 1.60 | 테마 붕괴·개별 구조저점 | 테마 내 저항 / 리더 확장 연동 저항 | overnight 금지 |
| G07 | S14 과매도반등 | 스윙 | 1.50 | 패닉저점·매수존 하단·ATR | MA20/BB중심/매물대 / BB상단·swing | +1.2R trailing |

### 4.1 공통 산식

```text
risk_price       = entry - SL
reward_price     = TP1 - entry
raw_RR           = reward_price / risk_price
net_reward_rate  = (TP1-entry)/entry - round_trip_cost
net_risk_rate    = (entry-SL)/entry + round_trip_cost
effective_RR     = net_reward_rate / net_risk_rate
display_score    = round(0.70 × family_rule_score + 0.30 × ai_score, 2)
```

`round_trip_cost`에는 수수료, 매도세금 해당분, spread, slippage와 시장충격 가정이 포함된다. 가격은 KRX 호가단위로 반올림하고 `TP2 ≥ TP1 > entry > SL`을 만족하지 않으면 ENTER가 아니다. 구조적 SL을 손실 cap 밖으로 넓혀 RR을 인위적으로 개선하는 행위와 서로 다른 setup의 SL 평균은 금지한다.

TP1 도달 시 현재 런타임은 50% 부분청산 후 `PARTIAL_TP`, 잔여는 TP2/SL/trailing/시간청산으로 관리한다. TP2가 없는 single-TP 계획은 TP1에서 전량 종료한다.

## 5. 규칙기반 점수 100점

| 컴포넌트 | 배점 | 포함 정보 |
|---|---:|---|
| setup edge | 35 | 각 S setup 고유 가격·수급·이벤트·구조 조건 |
| execution quality | 20 | 체결강도, bid/ask depth, spread, VWAP, 추격 위험 |
| regime & timing | 15 | KOSPI/KOSDAQ 장세, 세션, 실행 시간대 |
| liquidity & data quality | 10 | 거래대금, 봉 완전성, source age, fallback 상태 |
| risk & structure | 20 | SL 무효화 품질, 상단 여유, 변동성, 경고·군집위험 |

필수 데이터 결측은 0점이 아니라 `BLOCK`이다. Toss 같은 선택 데이터 결측은 `DEGRADED_NO_BONUS`이며 좋거나 나쁘다고 추정하지 않는다. 복수 setup 확증은 최대 +8이고 같은 데이터 계보를 재사용하면 두 번째 +4, 세 번째 +2 수준으로 상관 할인한다. 점수는 최종 0~100으로 clamp한다.

## 6. AI 스코어링 구조

### 6.1 실제 프롬프트 계층

현재 AI는 G별 독립 모델 7개가 아니다.

1. `strategy_meta.py`의 S1~S16 setup persona가 고유 진입 논리를 심사한다.
2. live family guard가 family/setup 일치, hard gate, source freshness, effective RR, 포지션 충돌을 강제한다.
3. AI 출력 JSON을 후검증하고 잘못된 가격관계·누락·enum·식별자는 `AI_SCHEMA_INVALID`로 fail closed한다.

즉 G prompt는 setup prompt를 대체하거나 여러 setup 규칙을 섞는 프롬프트가 아니라 공통 위험 심사 envelope다.

### 6.2 공통 system prompt 계약

```text
당신은 한국 주식 실전 진입 리스크 심사역이다. 입력 JSON에 있는 사실만 사용한다.
validated_family_id와 validated_setup_id를 그대로 반환한다. setup hard gate, 데이터
freshness, effective RR, 포지션·테마 한도를 우회할 수 없다. 필수 데이터 결측·stale,
source 충돌, 가격관계 오류, RR 미달이면 ENTER를 반환하지 않는다. Toss T+1 위험자료를
실시간 호가나 체결 사실처럼 사용하지 않는다. HOLD는 WATCH이며 점수만으로 승격하지 않는다.
반드시 지정된 JSON 한 개만 반환하고 이유와 무효화 조건은 한국어로 쓴다.
```

필수 출력은 `action`, `ai_score`, `confidence`, `reason`, `cancel_reason`, `validated_family_id`, `validated_setup_id`, `independent_confirmations`, `data_quality`, `risk_flags`, `claude_tp1`, `claude_tp2`, `claude_sl`, `effective_rr`다.

### 6.3 G별 AI 심사 프롬프트 rubric

#### G01 세션·이벤트

```text
대표 setup의 시간 경계를 먼저 확인한다. S1은 갭 이후 첫 1~3분 안착·VWAP·예상체결
괴리와 추격 위험, S2는 실제 Kiwoom VI 이벤트·눌림 저점·재탈환·2차 VI 위험,
S12는 종가 수급·종가 위치·overnight gap 위험을 각각 독립 평가한다. S12의 overnight
논리를 S1/S2에 적용하거나 S1/S2의 장중 SL을 S12에 적용하면 CANCEL한다.
```

#### G02 수급추세

```text
기관·외국인·프로그램의 방향뿐 아니라 지속성, 가격 동행, 최신성을 평가한다.
당일 Kiwoom 종목 수급과 Toss 일별 수급의 horizon을 섞지 않는다. S3/S5/S11 중
독립 데이터로 확인된 setup만 confirmation으로 인정한다. 프로그램·외국인 유입이
둔화되거나 가격이 반대로 움직이면 HOLD/CANCEL한다.
```

#### G03 축적확인

```text
ACCUMULATING, ARMED, TRIGGERED 상태와 최소 관찰일을 확인한다. 박스·저점상승,
상승/하락 거래량 비대칭, 누적 수급, trigger 품질을 평가한다. ARMED를 ENTER로
추정하지 않는다. TRIGGERED라도 box 무효화 SL과 effective RR 1.80을 충족해야 한다.
```

#### G04 추세단계

```text
S8 형성, S9 눌림, S15 재가속 중 대표 setup의 현재 단계를 판정한다. MA, RSI,
거래량 등 동일 계보를 중복 확증으로 세지 않는다. 눌림이 추세 훼손인지 건강한
재진입인지, 재가속이 과열 추격인지 구분하고 대표 setup 구조선만 TP/SL에 사용한다.
```

#### G05 구조돌파

```text
일목·신고가·박스 중 대표 구조의 실제 Kiwoom 돌파, 거래량 확장, 유지력, 상단 여유를
평가한다. 윗꼬리, 돌파선 재이탈, 매도벽, 넓은 spread, 과도한 MA20/ATR 이격은
강한 위험이다. Toss ranking 발견 사실만으로 돌파를 확정하지 않는다.
```

#### G06 장중급등·테마

```text
S4 장대양봉과 S6 테마후발을 하나의 setup으로 혼합하지 않는다. S4는 기준봉 이후
안착·재돌파·거래량 소진을, S6은 테마 강도·대장 생존·후발 위치·순환 유입을 본다.
동시 충족은 확증 태그일 뿐 TP/SL 또는 비중 확대 사유가 아니다. overnight는 금지한다.
```

#### G07 역추세반등

```text
RSI 저점만으로 ENTER하지 않는다. 복수 오실레이터 탈출, 장기 추세 생존, 실제 체결·호가
회복을 확인한다. 신용 군집, 대차·공매도 증가, 투자경고, 시장 폭 악화는 rebound 실패
위험으로 평가한다. 상승 family와 동일 종목 충돌 시 신규 역추세 진입을 BLOCK한다.
```

## 7. 신용·대차·공매도·프로그램 추이 사용 여부

결론은 **사용한다. 다만 모든 family에서 같은 방법으로 쓰지 않으며, 실시간 주문 원천으로 사용하지 않는다.**

| 데이터 | 주 source | 시간축 | 적용 | 금지사항 |
|---|---|---|---|---|
| 프로그램 순매수·시간대별 추이 | Kiwoom `ka90003/08/09` 등 | 장중 | G02 핵심, G03/G06 보조 | Toss 일별값으로 장중값 대체 금지 |
| 외국인·기관 종목 수급 | Kiwoom 종목별 API/WS | 장중·일별 | G02/G03 핵심, G04/G05 보조 | 서로 다른 기간의 순매수를 합산 금지 |
| 공매도 | Toss read-only risk | 주로 T+1 | swing G02~G05/G07 위험 가감 | day setup 진입 타이밍 근거 금지 |
| 신용거래·신용잔고 | Toss read-only risk | T+1 | crowding·반대매매 위험 | 낮은 값 결측을 호재로 추론 금지 |
| 대차잔고 | Toss read-only risk | T+1 | 잠재 매도압력·short crowding | 단일 snapshot을 추이로 표기 금지 |
| 투자경고·과열·정리매매 | Toss warnings | 공시/상태 | severe -25 또는 veto 후보, caution -6 범위 | S2 실제 VI를 warning으로 대체 금지 |

Toss risk 조회는 공매도·신용·대차 1,800초 cache, warnings 600초 cache를 사용하며 token/429/partial 실패는 `DEGRADED`로 기록한다. day setup(S1/S2/S4/S6)에는 Toss T+1 수치를 진입 타이밍 또는 양의 확증으로 사용하지 않는다. swing setup에서만 risk component와 AI 문맥에 포함한다.

프로그램 “추이”는 `latest_net_buy_amt`, `positive_count`, `avg_net_buy_amt` 및 source timestamp를 함께 전달할 수 있다. 외국인·기관·공매도·신용·대차 역시 최소 관측일, 시작값, 종료값, 증감률을 보존해야 하며 날짜 없는 화살표 표시는 금지한다.

## 8. Kiwoom과 Toss 역할 분담

| 목적 | 권위 source | 보조 source | 실패 정책 |
|---|---|---|---|
| 주문가격·ACK·fill·position | Kiwoom/기존 실행경로 | 없음 | 실패 시 BLOCK |
| 실시간 tick·호가·체결강도 | Kiwoom WS | bounded Kiwoom REST | stale/cancel 경계 초과 시 BLOCK |
| VI | Kiwoom `1h`, `ka10054` | Toss warning | Toss 단독 ENTER 금지 |
| 후보 랭킹 | Kiwoom 전략 API | Toss ranking union | 동일 hard gate 재검증 |
| 일·분봉 | Kiwoom | Toss full-series fallback | 부분 봉 혼합 금지 |
| 시장지수·시장수급 | Toss canonical | Kiwoom ETF proxy | source·age 표시 |
| 종목 risk | Toss | Kiwoom 가용 자료 | 결측은 degraded/no bonus |

실시간 종목 수치 충돌 우선순위는 fresh Kiwoom WS → bounded Kiwoom REST → payload다. 시장지수는 fresh Toss canonical → Kiwoom ETF proxy다. 서로 다른 값을 평균내지 않는다. 모든 fallback은 `data_source`, `source_timestamp`, `source_age_ms`, `fallback_reason`으로 남긴다.

freshness 기준선은 호가 caution/cancel 1초/2초, tick 3초/5초, 체결강도 5초/10초, active VI 3초/5초, released VI 10초/20초다. Redis TTL이 남아 있다는 사실만으로 fresh로 판단하지 않는다.

## 9. ENTER 결정식과 절대 차단 조건

```text
ENTER = setup_hard_gate_pass
      AND family_rule_score >= family_threshold
      AND required_source_fresh
      AND effective_RR >= setup_live_RR
      AND stock/family reservation acquired
      AND no ACTIVE/PARTIAL_TP/OVERNIGHT position
      AND theme/sector/exposure limits pass
      AND AI.action == ENTER
      AND AI output schema and price relation valid
```

다음 중 하나라도 있으면 점수와 무관하게 ENTER가 아니다.

- 필수 Kiwoom data missing/stale
- `TP2 < TP1`, `TP1 ≤ entry`, `SL ≥ entry`
- 비용 반영 effective RR 미달
- 동일 종목 활성 포지션 또는 Redis reservation 충돌
- G07과 상승 추세 family의 동일 종목 충돌
- S2 실제 VI 계보 누락
- S16 최소 관찰일·상태전이 누락
- AI JSON/schema/identity 오류
- 구조적 SL이 최대 손실 cap을 벗어남

## 10. 저장·추적 필드

각 신호는 기존 `strategy`와 함께 다음을 보존한다.

```json
{
  "family_id": "G05",
  "family_name": "STRUCTURAL_BREAKOUT",
  "primary_setup_id": "S13_BOX_BREAKOUT",
  "matched_setup_ids": ["S13_BOX_BREAKOUT", "S10_NEW_HIGH"],
  "confirmed_by_family_ids": [],
  "family_policy_version": "family_v1_2026_08_16",
  "rule_score_version": "family_score_v1_2026_08_16",
  "prompt_version": "family_prompt_v1_2026_08_16",
  "data_source": {"hoga": "kiwoom_ws", "risk": "toss"},
  "source_timestamp": {"hoga": "...", "risk": "..."},
  "source_age_ms": {"hoga": 430, "risk": 86400000},
  "fallback_reason": {},
  "correlation_id": "...",
  "arbitration_decision": "PRIMARY"
}
```

성과는 G family와 S setup 양쪽으로 집계한다. family 성과만 남기고 setup 기여도를 지우거나 과거 S 신호를 새 G 신호로 덮어쓰지 않는다.

## 11. 운영자가 메시지에서 확인할 순서

1. `ENTER`인지 `HOLD/WATCH`인지 확인한다.
2. G family와 대표 S setup이 기대한 조합인지 본다.
3. 데이터 품질과 Kiwoom source age를 확인한다.
4. TP1/TP2/SL 가격관계와 각각의 구조 method를 본다.
5. raw RR이 아닌 비용 반영 effective RR과 setup 하한을 비교한다.
6. 프로그램·외국인·기관 추이는 시간축과 source를 함께 확인한다.
7. 공매도·신용·대차는 T+1 risk 문맥이며 실시간 매수 신호가 아님을 확인한다.
8. 기존 포지션·동일 종목·테마 노출과 arbitration 결과를 확인한다.
9. AI 이유보다 hard gate와 무효화 조건을 우선한다.

## 12. 현재 한계와 후속 개선

- 일반 진입과 관심종목 formatter 모두 통합전략·2차 목표가·출처 경과시간을 표시한다.
- 데이터 payload가 단일 risk snapshot만 갖는 경우 “추이”를 정확히 표시할 수 없다.
- G별 prompt는 공통 family guard와 setup persona의 2계층이며, 7개의 완전 독립 프롬프트 파일은 아니다.
- 5거래일 live canary가 아직 완료되지 않아 새 점수와 RR의 성과 우월성은 입증되지 않았다.
- 메시지 정보량을 늘릴 때 Telegram 길이 제한을 고려해 핵심 본문과 상세 펼침/명령을 분리하는 것이 안전하다.

후속 개선은 `기간이 있는 risk trend 표준화 → 메시지 길이 제한에 따른 상세정보 접기 → 실사용 피드백 반영` 순서가 적절하다. 실전 메시지 포맷 변경은 5거래일 성과 관찰과 별도 변경으로 추적해야 전후 비교가 흐려지지 않는다.
