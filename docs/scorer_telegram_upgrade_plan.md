# scorer.py + telegram-bot 고도화 계획

## 현황 분석

### scorer.py 문제점
1. **S14/S15 케이스 누락** – match 블록에 분기 없음 → 공통 페널티만 적용 → 전략별 점수 무의미
2. **S14/S15 Claude 임계값 누락** – `CLAUDE_THRESHOLDS` 에 없음 → 기본값 65 사용
3. **RSI 미활용** – Java가 signal 에 `rsi` 필드를 포함하지만 scorer가 무시
4. **ATR 미활용** – `atr_pct` 필드 포함되지만 무시
5. **condCount 미활용** – S9 `cond_count`, S13 `cond_count` 등 조건 달성 수 필드 무시
6. **시간대 가중치 없음** – 09:00~09:30 갭전략 고평가, 14:30~15:00 종가전략 고평가 로직 없음

### telegram-bot 문제점

#### formatter.js
1. **S8~S15 지표 미표시** – RSI, ATR%, condCount, holdingDays 등 전략 고유 지표 없음
2. **포지션 크기 제안 없음** – ai_score + confidence 기반 투자비중 안내 없음
3. **전략 설명 없음** – 전략명만 표시, 어떤 신호인지 맥락 없음

#### commands.js
1. **`/filter` strategyMap 불완전** – s8/s9/s11/s13/s14/s15 누락 → 이 전략들 필터 설정 불가
2. **`/help` 전략 목록 구식** – s1~s7, s10, s12만 언급 → s8/s9/s11/s13/s14/s15 없음
3. **`/strategy` 설명** – s1~s7 전용으로 안내되어 있음

---

## 변경 대상 파일
| 파일 | 변경 내용 |
|------|----------|
| `ai-engine/scorer.py` | S14/S15 케이스, RSI/ATR scoring, 시간대 가중치, condCount |
| `telegram-bot/src/utils/formatter.js` | 전략 설명, 지표 표시, 포지션 크기 제안 |
| `telegram-bot/src/handlers/commands.js` | /filter strategyMap, /help, /strategy 설명 |

---

## scorer.py 상세 변경

### 1. S14_OVERSOLD_BOUNCE 스코어링
```
RSI 기반 (최대 40점):
  RSI < 25: +40점 (극심한 과매도)
  RSI < 30: +30점 (과매도)
  RSI < 40: +15점 (조정 구간)
ATR 기반 변동성 (최대 20점):
  atr_pct > 3%: +20점  atr_pct > 2%: +12점  atr_pct > 1%: +5점
체결강도 (최대 25점)
호가비율 (최대 15점)
```

### 2. S15_MOMENTUM_ALIGN 스코어링
```
RSI 모멘텀 정렬 (최대 35점):
  RSI 50~65 (상승 초기): +35점
  RSI 65~75 (상승 중): +20점
  RSI 45~50 (돌파 시도): +10점
거래량 비율 (최대 25점)
체결강도 (최대 25점)
호가비율 (최대 15점)
```

### 3. CLAUDE_THRESHOLDS 추가
```python
"S14_OVERSOLD_BOUNCE": 65,
"S15_MOMENTUM_ALIGN":  70,
```

### 4. 시간대 보정 (공통)
```
09:00~09:30: S1/S7 +5점 보너스 (갭 개장 전략)
09:00~10:30: S8/S9/S13 +5점 (크로스/돌파 초반)
14:30~15:30: S12 +5점 (종가강도 전략)
```

### 5. RSI 공통 활용 (S8/S9/S13)
```
S8: RSI > 50 + 25: +10점 (골든크로스 확증)
S9: RSI 40~60: +10점 (눌림목 진입 구간)
S13: RSI > 60: +10점 (박스 돌파 모멘텀)
```

### 6. condCount 공통 활용
```
cond_count >= 4: +10점 (많은 조건 충족)
cond_count == 3: +5점
```

---

## formatter.js 상세 변경

### 1. 전략 설명 맵 추가
```javascript
const STRATEGY_DESC = {
  S1_GAP_OPEN:        '갭 상승 개장 (전일 대비 갭 3~15%)',
  S8_GOLDEN_CROSS:    'MA5×MA20 골든크로스 + 거래량 확인',
  S9_PULLBACK_SWING:  '정배열 내 5MA 눌림목 반등',
  S13_BOX_BREAKOUT:   '박스권 상단 돌파 + 거래량 폭발',
  S14_OVERSOLD_BOUNCE:'RSI 과매도 반등 (RSI < 35)',
  S15_MOMENTUM_ALIGN: '다중 모멘텀 정렬 상승',
  ...
};
```

### 2. 전략별 지표 표시 추가
```
RSI: 신호에 rsi 있으면 표시
ATR%: atr_pct 있으면 표시
조건충족수: cond_count 있으면 표시
보유목표일: holding_days 있으면 표시
```

### 3. 포지션 크기 제안
```
ai_score≥85 + HIGH = 비중: 대 (full position)
ai_score≥75 + MEDIUM 이상 = 비중: 중
ai_score≥65 = 비중: 소 (half position)
```

---

## commands.js 상세 변경

### 1. /filter strategyMap 완성
```javascript
s8:  'S8_GOLDEN_CROSS',
s9:  'S9_PULLBACK_SWING',
s11: 'S11_FRGN_CONT',
s13: 'S13_BOX_BREAKOUT',
s14: 'S14_OVERSOLD_BOUNCE',
s15: 'S15_MOMENTUM_ALIGN',
```

### 2. /help 전략 목록 업데이트
S8~S15 모두 포함하도록 수정

### 3. /strategy 설명 업데이트
s1~s15 모두 실행 가능하도록 안내

---

## 구현 순서
1. scorer.py – S14/S15, RSI/ATR, 시간대 보정, condCount
2. formatter.js – 전략설명, 지표표시, 포지션크기
3. commands.js – strategyMap, /help, 설명
