# 전략별 TP/SL 비즈니스 로직 구현 계획

> 작성일: 2026-03-31
> 대상 파일: `api-orchestrator/.../service/StrategyService.java`

---

## 1. 이전 작업 검수 – 후보 풀 분리 현황

### 1-1. Redis 후보 풀 (`candidates:s{N}:{market}`) 할당 현황

| 전략 | CandidateService 메서드 | Redis 키 | 소스 API | 상태 |
|------|------------------------|----------|---------|------|
| S1 | `getS1Candidates(market)` | `candidates:s1:{001/101}` | ka10029 갭 3~15% | ✅ |
| S2 | — | — | 이벤트 기반(WebSocket 1h) | ✅ 별도 처리 |
| S3 | — | — | ka10063+ka10131 직접 호출 | ✅ 직접 호출 유지 |
| S4 | `getS12Candidates(market)` 재활용 | `candidates:s12:{001/101}` | ka10032 거래대금 | ✅ 재활용 |
| S5 | — | — | 직접 호출 유지 | ✅ 직접 호출 유지 |
| S6 | — | — | 직접 호출 유지 | ✅ 직접 호출 유지 |
| S7 | `getS7Candidates(market)` | `candidates:s7:{001/101}` | ka10029 갭 2~10% | ✅ |
| S8 | `getS8Candidates(market)` | `candidates:s8:{001/101}` | ka10027 상승 0.5~8% | ✅ |
| S9 | `getS9Candidates(market)` | `candidates:s9:{001/101}` | ka10027 상승 0.3~5% | ✅ |
| S10 | `getS10Candidates(market)` | `candidates:s10:{001/101}` | ka10016 52주신고가 | ✅ |
| S11 | `getS11Candidates(market)` | `candidates:s11:{001/101}` | ka10035 외인연속 | ✅ |
| S12 | `getS12Candidates(market)` | `candidates:s12:{001/101}` | ka10032 거래대금 | ✅ |
| S13 | `getS13Candidates(market)` | `candidates:s13:{001/101}` | S8∪S10 합산 | ✅ |
| S14 | `getS14Candidates(market)` | `candidates:s14:{001/101}` | ka10027 하락 3~10% | ✅ |
| S15 | `getS15Candidates(market)` | `candidates:s15:{001/101}` | S8 재활용 | ✅ |

**검수 결론**: S1~S15 전략 모두 독립적인 후보 풀을 보유하거나 의도적으로 풀 재활용/직접 호출을 유지하고 있다.

---

### 1-2. TP/SL 절대가 (`tp1Price / tp2Price / slPrice`) 구현 현황

| 전략 | 구현 여부 | 현재 로직 요약 | 비고 |
|------|----------|--------------|------|
| S1 | ✅ 구현 | `entry × 1.04 / 1.06 / 0.98` | % 고정 |
| S2 | ✅ 구현 | `entry × 1.03 / 1.045 / 0.98` | % 고정 |
| S3 | ❌ 미구현 | `targetPct=3.5 / stopPct=-2.0` (% 참조만) | 절대가 없음 |
| S4 | ✅ 구현 | `entry × 1.04 / 1.06`, SL=`당일저가 × 0.99` | 기술적 SL 있음 |
| S5 | ❌ 미구현 | `targetPct=3.0 / stopPct=-2.0` | 절대가 없음 |
| S6 | ❌ 미구현 | `targetPct=dynamic / stopPct=-2.0` | 절대가 없음 |
| S7 | ✅ 구현 | `entry × (1 + gapPct×0.8%)`, 동적 TP | 갭 크기 반영 |
| S8 | ✅ 구현 | TP1=10일고가, TP2=TP1×1.05, SL=MA20×0.98 | 기술적 분석 |
| S9 | ✅ 구현 | TP1=10일고가, TP2=20일고가, SL=MA20×0.97 | 기술적 분석 |
| S10 | ✅ 구현 | `entry×1.08 / ×1.15`, SL=`52주고가×0.99` | 기술적 SL |
| S11 | ❌ 미구현 | `targetPct=8.0 / stopPct=-5.0` | 절대가 없음 |
| S12 | ✅ 구현 | `entry × 1.05 / 1.075 / 0.97` | % 고정 |
| S13 | ✅ 구현 | TP1=`entry+boxHeight`, TP2=`entry+boxHeight×2`, SL=`boxHigh×0.99` | 기술적 분석 |
| S14 | ✅ 구현 | TP1=`entry+ATR×3.5`, TP2=`max(MA20, entry+ATR×5)`, SL=`entry-ATR×2` | ATR 기반 |
| S15 | ✅ 구현 | TP1=`max(BBU, entry×1.08)`, TP2=`TP1+ATR×0.5`, SL=`entry-ATR×2` | 볼린저+ATR |

**결론**: S3, S5, S6, S11 — 4개 전략의 절대가 TP/SL이 미구현 상태.

---

## 2. 구현 대상 – S3 / S5 / S6 / S11

### 설계 원칙

- S3/S5/S6/S11은 일봉 캔들 데이터가 현재 StrategyService 메서드 내에서 직접 조회되지 않음
- **단기 방안**: 진입가(`entryPrice`)와 전략별 성격을 반영한 `% 기반 절대가` 계산
- **장기 방안 (Phase 2)**: ka10081 일봉 API 호출 추가 후 기술적 레벨 적용 (별도 계획 수립)

> Phase 1 구현 기준: `entryPrice`와 전략별 R/R 특성을 반영한 절대가 설정

---

## 3. 전략별 TP/SL 비즈니스 로직 상세

### S1 – 갭상승 시초가 매수 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.04` | 갭 상승분의 절반 수준 익절 |
| TP2 | `entry × 1.06` | 갭 전체 확장 시 추가 익절 |
| SL  | `entry × 0.98` | 갭 메꿈 전 빠른 손절 (-2%) |
| R/R | 1 : 2.0 | 단기 갭 특성 |

---

### S2 – VI 눌림목 재진입 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.03` | VI 발동가 근처까지 복귀 |
| TP2 | `entry × 1.045` | VI 발동가 +1.5% 추가 |
| SL  | `entry × 0.98` | 눌림목 추가 이탈 시 손절 |
| R/R | 1 : 1.5 | 단기 이벤트 반응 |

---

### S3 – 외인+기관 동시 순매수 (**신규 구현**)

**배경**: 기관·외인 동시 순매수는 추세 지속 신호. 단기보다 중기 보유 가정.

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.06` | 기관 매수 확인 후 모멘텀 1단계 (+6%) |
| TP2 | `entry × 1.10` | 추세 지속 시 2단계 (+10%) |
| SL  | `entry × 0.97` | 순매수 반전 시 -3% 손절 |
| R/R | 1 : 2.0 | 중기 추세 전략 특성 |

**구현 코드** (`scanInstFrgn()` 내 builder에 추가):
```java
.tp1Price(round(curPrice * 1.06))
.tp2Price(round(curPrice * 1.10))
.slPrice (round(curPrice * 0.97))
```
> `curPrice`는 `item` 의 현재가 또는 `redisService.getTickData(stkCd)` 로 조회

---

### S4 – 장대양봉 추격 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.04` | 양봉 몸통 크기의 절반 수익 |
| TP2 | `entry × 1.06` | 양봉 전체 크기 추가 확장 |
| SL  | `dayLow × 0.99` (or `entry × 0.975`) | 당일 저가 이탈 = 추세 실패 |
| R/R | 1 : 1.6 | 당일 추격 특성 |

---

### S5 – 프로그램+외인 매수 (**신규 구현**)

**배경**: 프로그램·외인 동시 수급은 대형주 중심의 안정적 신호.

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.05` | 프로그램 매수 확인 후 1단계 (+5%) |
| TP2 | `entry × 1.08` | 외인 추가 유입 확인 2단계 (+8%) |
| SL  | `entry × 0.97` | 프로그램 청산 가능 구간 -3% |
| R/R | 1 : 1.67 | 대형주 안정 수익률 특성 |

**구현 코드** (`scanProgramFrgn()` 내 builder에 추가):
```java
.tp1Price(round(curPrice * 1.05))
.tp2Price(round(curPrice * 1.08))
.slPrice (round(curPrice * 0.97))
```

---

### S6 – 테마 후발주 매수 (**신규 구현**)

**배경**: 테마 선도주 등락률(`themeFluRt`)을 기준으로 후발주 목표가를 동적 산출.

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × (1 + min(themeFluRt × 0.5, 6.0) / 100)` | 선도주 상승분의 50% 추종 |
| TP2 | `entry × (1 + min(themeFluRt × 0.7, 9.0) / 100)` | 선도주 상승분의 70% 추종 (최대 9%) |
| SL  | `entry × 0.97` | 테마 훼손 시 -3% 손절 |
| R/R | 가변 (테마강도에 비례) | 동적 R/R |

**구현 코드** (`scanThemeLaggard()` 내 builder에 추가):
```java
double t1Pct = Math.min(themeFluRt * 0.5, 6.0);
double t2Pct = Math.min(themeFluRt * 0.7, 9.0);
.tp1Price(round(curPrice * (1 + t1Pct / 100)))
.tp2Price(round(curPrice * (1 + t2Pct / 100)))
.slPrice (round(curPrice * 0.97))
```
> `themeFluRt`는 기존 `targetPct` 계산에 이미 사용 중인 값 재활용

---

### S7 – 동시호가 매수 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × (1 + min(gapPct×0.8, 5.0) / 100)` | 동적: 갭의 80% 수익 (최대 5%) |
| TP2 | `entry × (1 + min(TP1배율×1.5, 8.0) / 100)` | 동적: TP1의 1.5배 (최대 8%) |
| SL  | `entry × 0.98` | 갭 메꿈 방어 -2% |

---

### S8 – 5일선 골든크로스 스윙 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `max(최근10일고가, entry×1.05)` | 직근 저항 돌파 |
| TP2 | `TP1 × 1.05` | TP1 돌파 후 추가 모멘텀 |
| SL  | `MA20 × 0.98` | 골든크로스 무효화 선 |
| R/R | 1 : 2.5+ | 스윙 3~7일 |

---

### S9 – 정배열 눌림목 반등 스윙 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `max(최근10일고가, entry×1.05)` | 직근 저항 |
| TP2 | `max(최근20일고가, TP1×1.03)` | 직근 20일 저항 |
| SL  | `MA20 × 0.97` | 정배열 붕괴선 |
| R/R | 1 : 2.0+ | 스윙 3~5일 |

---

### S10 – 52주 신고가 돌파 스윙 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.08` | 신고가 돌파 후 8% 확장 |
| TP2 | `entry × 1.15` | 추세 지속 시 15% |
| SL  | `52주고가 × 0.99` | 돌파 무효 = 고점 하회 |
| R/R | 1 : 2.7 | 스윙 |

---

### S11 – 외국인 연속 순매수 스윙 (**신규 구현**)

**배경**: 외인 연속 순매수(3일+)는 중기 추세 신호. 큰 R/R 추구.

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.08` | 외인 매집 완료 후 +8% |
| TP2 | `entry × 1.14` | 기관 동반 유입 가정 +14% |
| SL  | `entry × 0.95` | 외인 이탈 가능 구간 -5% |
| R/R | 1 : 1.6 | 스윙 5~7일 |

> 고정 SL -5%: 외인 연속 매수 종목은 급락 시 빠른 방어 필요

**구현 코드** (`scanFrgnCont()` 내 builder에 추가):
```java
.tp1Price(round(curPrice * 1.08))
.tp2Price(round(curPrice * 1.14))
.slPrice (round(curPrice * 0.95))
```

---

### S12 – 종가 강도 매수 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry × 1.05` | 익일 시초가 갭 + 추가 |
| TP2 | `entry × 1.075` | 익일 강세 지속 |
| SL  | `entry × 0.97` | 익일 약세 전환 -3% |
| R/R | 1 : 1.67 | 단기 1~2일 |

---

### S13 – 박스권 돌파 스윙 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry + boxHeight` | 박스 높이만큼 상승 (1배 확장) |
| TP2 | `entry + boxHeight × 2` | 박스 2배 확장 |
| SL  | `boxHigh × 0.99` | 돌파 무효(박스 상단 하회) |
| R/R | 1 : 2.0 | 스윙 3~7일 |

---

### S14 – 과매도 반등 스윙 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `entry + ATR × 3.5` | 변동성 3.5배 수익 |
| TP2 | `max(MA20, entry + ATR × 5.0)` | MA20 회복 or 5배 ATR |
| SL  | `entry − ATR × 2.0` | 변동성 2배 손절 |
| R/R | 1 : 1.75 | ATR 비대칭 |

---

### S15 – 다중지표 모멘텀 동조 스윙 (이미 구현, 검토용 기준)

| 항목 | 값 | 근거 |
|------|-----|------|
| TP1 | `max(볼린저 상단, entry×1.08)` | 밴드 상단 돌파 또는 8% |
| TP2 | `TP1 + ATR × 0.5` | 상단 돌파 후 추가 |
| SL  | `entry − ATR × 2.0` | 변동성 기반 손절 |
| R/R | 가변 | ATR + 볼린저 동적 |

---

## 4. 구현 계획

### 4-1. 변경 파일

```
api-orchestrator/src/main/java/org/invest/apiorchestrator/service/StrategyService.java
```

### 4-2. 변경 메서드 및 내용

| 메서드 | 변경 내용 | 데이터 소스 |
|--------|----------|------------|
| `scanInstFrgn()` (S3) | builder에 `tp1Price/tp2Price/slPrice` 추가 | `redisService.getTickData(stkCd)` curPrice 조회 필요 |
| `scanProgramFrgn()` (S5) | builder에 `tp1Price/tp2Price/slPrice` 추가 | `redisService.getTickData(stkCd)` curPrice 조회 필요 |
| `scanThemeLaggard()` (S6) | builder에 동적 `tp1Price/tp2Price/slPrice` 추가 | 기존 `targetPct` 산출 변수(`themeFluRt`) 재활용 |
| `scanFrgnCont()` (S11) | builder에 `tp1Price/tp2Price/slPrice` 추가 | `redisService.getTickData(stkCd)` curPrice 조회 필요 |

### 4-3. S3/S5/S11 공통 패턴 – curPrice 조회

S3, S5, S11 메서드는 현재 `TradingSignalDto.entryPrice` 에 실제 현재가가 설정되어 있는지 확인 후,
미설정 시 Redis tick 에서 별도 조회:

```java
// entryPrice가 이미 builder에 설정된 경우
double curPrice = /* 기존 entryPrice 변수 */;

// entryPrice가 없는 경우 tick 조회
var tickOpt = redisService.getTickData(stkCd);
double curPrice = tickOpt.isPresent() ? parseDouble(tickOpt.get(), "cur_prc") : 0.0;
if (curPrice <= 0) continue;  // 현재가 없으면 TP/SL 산출 불가

.tp1Price(round(curPrice * 1.XX))
.tp2Price(round(curPrice * 1.XX))
.slPrice (round(curPrice * 0.XX))
```

### 4-4. S6 – `themeFluRt` 변수 확인

`scanThemeLaggard()` 내에서 `targetPct` 계산에 사용되는 테마 등락률 변수를 확인하여
동일 변수를 TP 계산에 재활용. 예:
```java
double themeFluRt = item.getFluRt() or themeLeaderFluRt;  // 기존 로직에서 추출
double t1Pct = Math.min(themeFluRt * 0.5, 6.0);
double t2Pct = Math.min(themeFluRt * 0.7, 9.0);
.tp1Price(round(curPrice * (1.0 + t1Pct / 100.0)))
.tp2Price(round(curPrice * (1.0 + t2Pct / 100.0)))
.slPrice (round(curPrice * 0.97))
```

---

## 5. 전략 전체 TP/SL 요약표

| 전략 | 유형 | TP1 | TP2 | SL | R/R |
|------|------|-----|-----|-----|-----|
| S1 갭오픈 | 단기 | entry×1.04 | entry×1.06 | entry×0.98 | 1:2.0 |
| S2 VI눌림 | 단기 | entry×1.03 | entry×1.045 | entry×0.98 | 1:1.5 |
| **S3 기관외인** | 중기 | entry×1.06 | entry×1.10 | entry×0.97 | 1:2.0 |
| S4 장대양봉 | 단기 | entry×1.04 | entry×1.06 | dayLow×0.99 | 1:1.6 |
| **S5 프로그램** | 중기 | entry×1.05 | entry×1.08 | entry×0.97 | 1:1.67 |
| **S6 테마후발** | 단기 | entry×(1+테마×0.5%) | entry×(1+테마×0.7%) | entry×0.97 | 가변 |
| S7 동시호가 | 단기 | entry×(1+갭×0.8%) | entry×(1+갭×1.2%) | entry×0.98 | 가변 |
| S8 골든크로스 | 스윙 | max(10일고가, entry×1.05) | TP1×1.05 | MA20×0.98 | 1:2.5+ |
| S9 눌림목 | 스윙 | max(10일고가, entry×1.05) | max(20일고가, TP1×1.03) | MA20×0.97 | 1:2.0+ |
| S10 신고가 | 스윙 | entry×1.08 | entry×1.15 | 52주고가×0.99 | 1:2.7 |
| **S11 외인연속** | 스윙 | entry×1.08 | entry×1.14 | entry×0.95 | 1:1.6 |
| S12 종가강도 | 단기 | entry×1.05 | entry×1.075 | entry×0.97 | 1:1.67 |
| S13 박스돌파 | 스윙 | entry+boxH | entry+boxH×2 | boxHigh×0.99 | 1:2.0 |
| S14 과매도반등 | 스윙 | entry+ATR×3.5 | max(MA20, entry+ATR×5) | entry−ATR×2 | 1:1.75 |
| S15 모멘텀동조 | 스윙 | max(BBU, entry×1.08) | TP1+ATR×0.5 | entry−ATR×2 | 가변 |

> **굵게** 표시된 4개 전략이 이번 구현 대상.

---

## 6. 구현 완료 기준 체크리스트

- [ ] `scanInstFrgn()` (S3) builder에 `tp1Price`, `tp2Price`, `slPrice` 추가
- [ ] `scanProgramFrgn()` (S5) builder에 `tp1Price`, `tp2Price`, `slPrice` 추가
- [ ] `scanThemeLaggard()` (S6) builder에 동적 `tp1Price`, `tp2Price`, `slPrice` 추가
- [ ] `scanFrgnCont()` (S11) builder에 `tp1Price`, `tp2Price`, `slPrice` 추가
- [ ] `toQueuePayload()`에 `tp1_price`, `tp2_price`, `sl_price` 포함 여부 확인 (이미 포함)
- [ ] `toTelegramMessage()`에서 절대가 우선 표시 여부 확인 (이미 구현)
- [ ] `formatter.js` TP/SL 표시 수신 확인
