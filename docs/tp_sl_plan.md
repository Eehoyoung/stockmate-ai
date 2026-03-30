# TP/SL 전략적 산출 및 Claude 최종화 구현 계획

## 개요

매수 추천 신호에 포함되는 TP1(1차 목표가), TP2(2차 목표가), SL(손절가)을 두 단계로 부여한다.

```
Phase 1 (규칙 기반 – Java StrategyService)
  → 전략별 기술적 분석 기반 TP1/TP2/SL 절대가격 계산
  → 텔레그램 컨펌 요청 메시지에 포함

Phase 2 (Claude AI – confirm_worker.py)
  → 사용자 컨펌 후 Claude API 호출 시 규칙 기반 TP/SL 포함 전달
  → Claude가 최종 TP1/TP2/SL 반환
  → 최종 ENTER 메시지에 "Claude 최종가" 로 표시
```

---

## 전략별 규칙 기반 TP/SL 산출 기준

| 전략 | TP1 | TP2 | SL | 기준 데이터 |
|------|-----|-----|-----|------------|
| **S1 갭오픈** | 진입가 × 1.05 | 진입가 × 1.10 | 진입가 × 0.97 | % 고정 |
| **S2 VI 눌림** | 진입가 × 1.06 | 진입가 × 1.10 | 진입가 × 0.97 | % 고정 |
| **S3 기관외인** | 진입가 × 1.08 | 진입가 × 1.13 | 진입가 × 0.95 | % 고정 |
| **S4 장대양봉** | 진입가 × 1.08 | 진입가 × 1.15 | 당일 저가 × 0.99 | 당일 저가 |
| **S5 프로그램** | 진입가 × 1.07 | 진입가 × 1.12 | 진입가 × 0.96 | % 고정 |
| **S6 테마후발** | 진입가 × 1.08 | 진입가 × 1.15 | 진입가 × 0.95 | % 고정 |
| **S7 동시호가** | 진입가 × 1.05 | 진입가 × 1.10 | 진입가 × 0.97 | % 고정 |
| **S8 골든크로스** | 최근 10일 고가 (저항) | TP1 × 1.05 | MA20 × 0.98 | 일봉 candle |
| **S9 눌림목** | 최근 10일 고가 | 최근 20일 고가 | MA20 × 0.97 | 일봉 candle |
| **S10 신고가** | 진입가 × 1.08 | 진입가 × 1.15 | 진입가 × 0.96 | % 고정 |
| **S11 외인연속** | 진입가 × 1.08 | 진입가 × 1.12 | 진입가 × 0.95 | % 고정 |
| **S12 종가매수** | 진입가 × 1.05 | 진입가 × 1.08 | 진입가 × 0.97 | % 고정 |
| **S13 박스돌파** | 진입가 + 박스높이 | 진입가 + 박스높이 × 2 | 박스 상단 × 0.99 | 일봉 candle |
| **S14 과매도반등** | 진입가 + ATR × 3.5 (기존) | MA20 가격 | 진입가 − ATR × 2.0 (기존) | ATR + MA20 |
| **S15 모멘텀** | 볼린저 상단 (BBU) | BBU + ATR × 0.5 | 진입가 − ATR × 2.0 | Bollinger + ATR |

> 모든 절대가는 호가단위 반올림 없이 `Math.round()` 적용

---

## 변경 파일 목록

### 1. `api-orchestrator/.../dto/req/TradingSignalDto.java`
- 필드 추가: `tp1Price`, `tp2Price`, `slPrice` (Double)
- `toQueuePayload()`: `tp1_price`, `tp2_price`, `sl_price` 추가
- `toTelegramMessage()`: 규칙 기반 TP/SL 절대가 표시 라인 추가

### 2. `api-orchestrator/.../service/StrategyService.java`
- 각 전략 scan 메서드 builder에 `.tp1Price(..)`, `.tp2Price(..)`, `.slPrice(..)` 추가
- S8/S9: 최근 고가 배열에서 저항 수준 계산 → TP1/TP2
- S13: `boxHigh`(기존 계산값) → SL, `closes[0] + (closes[0] - boxLow)` → TP1
- S14: 기존 `targetPrice`/`stopPrice` → `tp1Price`/`slPrice`, MA20 → `tp2Price`
- S15: Bollinger 상단 산출 → `tp1Price`, BBU + ATR×0.5 → `tp2Price`

### 3. `ai-engine/analyzer.py`
- `_SYS_PROMPT`: JSON 스키마에 `claude_tp1`, `claude_tp2`, `claude_sl` (절대가) 추가
- `_build_user_message()`: 각 전략 프롬프트에 규칙 기반 TP/SL + 진입가 컨텍스트 포함
- `MAX_TOKENS`: 256 → 512 (TP/SL 숫자 출력 공간 확보)

### 4. `ai-engine/confirm_worker.py`
- `enriched` 딕셔너리에 `claude_tp1`, `claude_tp2`, `claude_sl` 추가 추출

### 5. `telegram-bot/src/utils/formatter.js`
- `formatSignal()`:
  - **기존 하드코딩 제거**: `Math.round(curPrc * 1.08)`, `Math.round(curPrc * 0.97)`
  - 규칙 기반 표시: `tp1_price`, `tp2_price`, `sl_price` 사용
  - Claude 확정 표시: `human_confirmed=true`일 때 `claude_tp1`, `claude_tp2`, `claude_sl` 별도 라인

### 6. `telegram-bot/src/handlers/signals.js`
- `sendConfirmRequest()`: 컨펌 요청 메시지에 규칙 기반 TP/SL 표시 추가
  - `항목.tp1_price`, `항목.tp2_price`, `항목.sl_price`

---

## 메시지 UX 흐름

### 컨펌 요청 메시지 (signals.js)
```
🔔 [매매 신호 컨펌 요청]

종목: 005930 삼성전자
전략: S8_GOLDEN_CROSS
규칙 스코어: 72.5점

📐 규칙 기반 목표가 (기술적 분석)
  TP1: 78,500원  (+6.8%)
  TP2: 82,400원  (+12.0%)
  SL:  72,200원  (-1.8%)

신호: 📈 [S8_GOLDEN_CROSS] 005930 ...
Claude AI 분석을 진행하시겠습니까?
```

### ENTER 메시지 (formatter.js) – Claude 미확정
```
📈 [S8_GOLDEN_CROSS] 005930 삼성전자
✅ 진입 | 신뢰도: 🔴 높음
AI 스코어: 78.0점 (규칙: 72.5점)
진입방식: 당일종가_또는_익일시가

📐 목표가 (규칙 기반)
  TP1: 78,500원 (+6.8%)
  TP2: 82,400원 (+12.0%)
  SL:  72,200원 (-1.8%)
  R/R: 1:3.8
```

### ENTER 메시지 – Claude 확정 후 (`human_confirmed=true`)
```
📈 [S8_GOLDEN_CROSS] 005930 삼성전자
✅ 진입 | 신뢰도: 🔴 높음
AI 스코어: 82.0점

🤖 Claude 최종 목표가
  TP1: 79,000원 (+7.5%)
  TP2: 84,000원 (+14.3%)
  SL:  71,800원 (-2.3%)
  R/R: 1:4.2

📐 규칙 기반 (참고)
  TP1: 78,500원 / TP2: 82,400원 / SL: 72,200원
```

---

## 구현 순서

1. `TradingSignalDto.java` – 필드 + payload + 메시지 수정
2. `StrategyService.java` – 전략별 TP/SL 계산 삽입
3. `analyzer.py` – 시스템 프롬프트 + 토큰 확장
4. `confirm_worker.py` – Claude 결과 필드 추출
5. `formatter.js` – 하드코딩 제거 + TP/SL 표시 개선
6. `signals.js` – 컨펌 요청 메시지에 TP/SL 추가
