# StockMate AI – Claude API 사용 명세

## 개요

StockMate AI는 `ai-engine` 모듈에서 Claude API를 **두 가지 목적**으로 호출한다.

| 호출 목적 | 담당 모듈 | 호출 시점 |
|---|---|---|
| 매매 신호 최종 판단 (2차 분석) | `analyzer.py` | 규칙 스코어가 임계값 이상일 때 |
| 시장 뉴스 분석 및 매매 제어 | `news_analyzer.py` | 뉴스 스케줄러 주기 실행 시 |

---

## 1. 매매 신호 분석 (`analyzer.py`)

### 역할

Java `api-orchestrator`가 생성한 매매 신호를 최종 검증하는 2차 필터.
규칙 기반 1차 스코어링(`scorer.py`)을 통과한 신호에 대해서만 Claude를 호출하여 비용을 절감한다.

### 호출 흐름

```
telegram_queue (Redis)
  ↓ RPOP
queue_worker.py
  ↓ 1차: rule_score() → 전략별 임계값 미달 시 CANCEL (Claude 미호출)
  ↓ 2차: check_daily_limit() → 일별 상한 초과 시 규칙 스코어 폴백
  ↓ 3차: analyze_signal() → Claude API 호출
ai_scored_queue (Redis)
  ↓ LPUSH
telegram-bot (Node.js) → Telegram 발송
```

### 전략별 Claude 호출 임계값

규칙 점수가 아래 임계값 미만이면 Claude를 호출하지 않고 즉시 `CANCEL` 처리한다.

| 전략 코드 | 전략명 | Claude 호출 최소 점수 |
|---|---|---|
| S1_GAP_OPEN | 갭상승 시초가 | 70점 |
| S2_VI_PULLBACK | VI 눌림목 | 65점 |
| S3_INST_FRGN | 외인+기관 동반 | 60점 |
| S4_BIG_CANDLE | 장대양봉 추격 | 75점 |
| S5_PROG_FRGN | 프로그램+외인 | 65점 |
| S6_THEME_LAGGARD | 테마 후발주 | 60점 |
| S7_ICHIMOKU_BREAKOUT | 일목균형표 구름대 돌파 스윙 | 62점 |
| S10_NEW_HIGH | 52주 신고가 | 65점 |
| S11_FRGN_CONT | 외국인 연속 순매수 | 60점 |
| S12_CLOSING | 종가 강도 확인 | 65점 |

### 시스템 프롬프트 (`prompts/signal_analysis.txt`)

Claude에게 **한국 주식 단타 트레이딩 전문 AI 분석가** 역할을 부여한다.

**판단 기준:**
1. 시장 전체 흐름 (코스피/코스닥 지수 방향)
2. 해당 종목의 체결강도 추세 (최근 5개 평균)
3. 호가 매수/매도 비율
4. 갭 또는 상승률의 과열 여부 (10% 초과 갭 → 위험)
5. VI 발동 이력 (당일 2회 이상 → 변동성 주의)

### 사용자 메시지 구성 (`_build_user_message`)

전략별로 압축된 단일 줄 메시지를 생성한다. 공통 포함 정보:
- 종목코드 / 종목명
- 전략 핵심 지표 (갭비율, 체결강도, 호가비율, 거래량비율 등)
- 규칙 기반 1차 점수 (`rule_score / 100`)

토큰 절감을 위해 전략과 무관한 필드는 제외하고 핵심 지표만 전달한다.

### API 파라미터

| 항목 | 값 |
|---|---|
| 모델 | `CLAUDE_MODEL` 환경변수 (기본: `claude-sonnet-4-20250514`) |
| `max_tokens` | 256 |
| 타임아웃 | 10초 |
| `parse_mode` | JSON 강제 (시스템 프롬프트에서 지정) |

### Claude 응답 형식

```json
{
  "action": "ENTER | HOLD | CANCEL",
  "ai_score": 0~100,
  "confidence": "HIGH | MEDIUM | LOW",
  "reason": "한국어 2~3줄 근거",
  "adjusted_target_pct": null,
  "adjusted_stop_pct": null
}
```

- `action`: 최종 매매 결정. `ENTER`인 경우에만 Telegram 알림 발송
- `adjusted_target_pct / adjusted_stop_pct`: Claude가 원본 목표가/손절가를 조정할 경우 설정

### 폴백 처리

Claude 호출 실패(타임아웃, API 오류, JSON 파싱 실패) 시 규칙 스코어로 대체한다.

```
rule_score >= 70 → ENTER
rule_score >= 50 → HOLD
rule_score < 50  → CANCEL
confidence = LOW (항상)
```

---

## 2. 뉴스 분석 및 매매 제어 (`news_analyzer.py`)

### 역할

주기적으로 수집한 금융 뉴스를 Claude에 배치로 전달하여 **시장 심리 평가 + 매매 중단 여부**를 결정한다.
분석 결과는 Redis에 저장되며, 이후 모든 신호 처리 시 최우선으로 참조된다.

### 호출 흐름

```
news_scheduler.py (주기 실행, 기본 30분)
  ↓ collect_news() → 금융 뉴스 수집
  ↓ analyze_news() → Claude API 호출
  ↓ 결과를 Redis에 저장
      news:trading_control  → "CONTINUE | CAUTIOUS | PAUSE"
      news:analysis         → 전체 JSON 결과
```

**queue_worker.py에서의 참조:**
각 신호 처리 시작 시 `news:trading_control` 값을 확인한다.
값이 `PAUSE`이면 Claude 분석 없이 즉시 `CANCEL` 처리한다.

### 시스템 프롬프트 (`prompts/news_analysis.txt`)

**매매 제어 결정 기준:**

| 결정 | 조건 예시 |
|---|---|
| `PAUSE` (매매 중단) | 지정학적 긴장, 금리 쇼크, 서킷브레이커, 외국인 1조 이상 순매도, 금융 시스템 리스크 |
| `CAUTIOUS` (신중 매매) | 혼조 장세, 섹터 순환, 선거/FOMC 불확실성, 코스피 -1.5% 이상 |
| `CONTINUE` (정상 매매) | 위 조건에 해당하지 않는 일반 장세 |

### API 파라미터

| 항목 | 값 |
|---|---|
| 모델 | `CLAUDE_MODEL` 환경변수 (기본: `claude-sonnet-4-20250514`) |
| `max_tokens` | 512 |
| 타임아웃 | 30초 (신호 분석보다 넉넉하게) |

### Claude 응답 형식

```json
{
  "market_sentiment": "BULLISH | NEUTRAL | BEARISH",
  "trading_control": "CONTINUE | CAUTIOUS | PAUSE",
  "recommended_sectors": ["반도체", "방산"],
  "risk_factors": ["리스크1", "리스크2"],
  "summary": "한국어 2~3줄 시장 상황 요약",
  "confidence": "HIGH | MEDIUM | LOW"
}
```

### 폴백 처리

Claude 호출 실패 시 기본값(`NEUTRAL`, `CONTINUE`)으로 대체하여 매매를 중단하지 않는다.

---

## 비용 제어 메커니즘

### 신호 분석 (1번 호출)

| 방법 | 상세 |
|---|---|
| 규칙 1차 필터 | 전략별 임계값 미달 신호는 Claude 미호출 |
| 일별 호출 상한 | `MAX_CLAUDE_CALLS_PER_DAY` (기본: 100회/일) |
| Redis 카운터 키 | `claude:daily_calls:{YYYYMMDD}` (24시간 TTL) |
| 토큰 추적 키 | `claude:daily_tokens:{YYYYMMDD}` (24시간 TTL) |
| 압축 프롬프트 | `max_tokens=256`, 전략별 핵심 지표만 전달 |
| 뉴스 PAUSE 시 | 신호 전체를 Claude 없이 즉시 CANCEL |

### 뉴스 분석 (2번 호출)

| 방법 | 상세 |
|---|---|
| 주기 실행 | `NEWS_INTERVAL_MIN` 환경변수 (기본: 30분) |
| 일별 호출 상한 | `MAX_NEWS_CLAUDE_CALLS` (기본: 48회/일) |
| Redis 카운터 키 | `claude_news_calls:{YYYYMMDD}` (25시간 TTL) |

---

## 환경변수 정리

| 변수명 | 기본값 | 설명 |
|---|---|---|
| `CLAUDE_API_KEY` | 없음 (필수) | Anthropic API 키 |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | 사용 모델 |
| `AI_SCORE_THRESHOLD` | `60.0` | 전략 미지정 시 기본 임계값 |
| `MAX_CLAUDE_CALLS_PER_DAY` | `100` | 신호 분석 일별 상한 |
| `MAX_NEWS_CLAUDE_CALLS` | `48` | 뉴스 분석 일별 상한 |
| `NEWS_ENABLED` | `true` | 뉴스 스케줄러 활성화 여부 |
| `NEWS_INTERVAL_MIN` | `30` | 뉴스 분석 주기 (분) |

---

## Claude 클라이언트 구현 방식

- **신호 분석**: `anthropic.AsyncAnthropic` 싱글턴 (`_claude_client`) 으로 관리하여 매 신호마다 클라이언트를 재생성하지 않는다.
- **뉴스 분석**: 호출마다 새 클라이언트 인스턴스를 생성한다 (호출 빈도가 낮아 비용 무관).
- **SDK**: `anthropic` Python SDK (`requirements.txt` 명시)
- **비동기**: 모든 호출이 `asyncio.wait_for`로 타임아웃 보장
