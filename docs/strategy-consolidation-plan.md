# 전략 통폐합 계획 (15 → 9개)

## 배경 및 목적

현재 15개 독립 전략 파일이 운영 중이며 일부 전략 간 API 중복 호출·로직 유사성·Redis 키 과다 증식 문제가 있다.
통폐합으로 유지보수 부담을 줄이고 코드 응집도를 높이는 것을 목표로 한다.

---

## 현행 전략 분류

| 그룹 | 파일 | 핵심 진입 조건 | API | 타임프레임 |
|------|------|--------------|-----|---------|
| **시초가** | strategy_1_gap_opening.py | 갭 3~15%, 체결강도 ≥ 120% | ka10029 | 시초가 |
| **시초가** | strategy_7_auction.py | 갭 2~10%, 호가비율 ≥ 2.0 | ka10029 | 동시호가 |
| **이벤트** | strategy_2_vi_pullback.py | VI 해제, hoga 비율 | WS 이벤트 | 실시간 |
| **추격** | strategy_4_big_candle.py | 5분봉 양봉 3%, vol 5× | ka10080 | 5분봉 |
| **수급** | strategy_3_inst_foreign.py | 기관+외인 동시 순매수 | ka10063 | 일봉 |
| **수급** | strategy_5_program_buy.py | 프로그램+외인 교집합 | ka90003 | 일봉 |
| **수급** | strategy_11_frgn_cont.py | 외인 3일 연속 순매수 | ka10035 | 일봉 |
| **테마** | strategy_6_theme.py | 테마 후발주 등락률 0.5~7% | ka90001/ka90002 | 일봉 |
| **MA 스윙** | strategy_8_golden_cross.py | MA5 골든크로스, RSI ≤ 75 | ka10081 | 일봉 |
| **MA 스윙** | strategy_9_pullback.py | MA5>20>60 정배열 눌림목 | ka10081 | 일봉 |
| **MA 스윙** | strategy_15_momentum_align.py | MACD+RSI+Boll 3/4 조건 | ka10081 | 일봉 |
| **돌파** | strategy_10_new_high.py | 52주 신고가, vol ≥ 100% | ka10016 | 일봉 |
| **돌파** | strategy_13_box_breakout.py | 박스권 ≤ 8% 돌파, vol ≥ 2× | ka10081 | 일봉 |
| **반등** | strategy_14_oversold_bounce.py | RSI 20~38, 오실레이터 수렴 | ka10081 | 일봉 |
| **종가** | strategy_12_closing.py | 종가 flu ≥ 4%, 강도 ≥ 110% | ka10027 | 14:30~14:50 |

---

## 병합 대상 (3개 그룹)

### 1단계: S1 + S7 → `strategy_1_gap_opening.py`

**병합 근거**
- 두 전략 모두 **ka10029 동일 API** 사용
- 시간 윈도우 겹침: S7(08:30~09:00) ⊂ S1(08:30~09:10)
- 동일한 임포트: `kiwoom_client`, `get_atr_minute`, `fetch_stk_nm`, `calc_tp_sl`
- S1은 `exp_flu_rt + cntr_strength` 기반, S7은 `gap_rt + bid_ratio` 기반 — 동일 시초가 국면에서 보완 관계

**구체적 변경**

| 항목 | 현행 | 병합 후 |
|------|------|--------|
| 파일 | strategy_1_gap_opening.py + strategy_7_auction.py | strategy_1_gap_opening.py (통합) |
| 신호명 | S1_GAP_OPEN / S7_AUCTION | 유지 (하위 호환) |
| 추가 함수 | — | `_clean_num()`, `fetch_gap_rank()`, `fetch_credit_filter()`, `scan_auction_signal()` |
| 삭제 파일 | — | strategy_7_auction.py |

**strategy_runner.py 변경**
```python
# 변경 전
from strategy_7_auction import scan_auction_signal

# 변경 후
from strategy_1_gap_opening import scan_auction_signal
```

**scorer.py, candidates_builder.py, overnight_scorer.py** → 신호명이 유지되므로 변경 불필요

---

### 2단계: S8 + S9 + S15 → `strategy_8_golden_cross.py`

**병합 근거**
- 셋 다 **ka10081 일봉 차트** API 사용 (`fetch_daily_candles`)
- MA5/20/60, RSI, MACD 등 동일 지표 세트 계산
- 의미적 연속성: 추세 시작(S8 골든크로스) → 추세 지속(S9 눌림목) → 모멘텀 확인(S15 다중지표)
- candidates 풀: `candidates:s8:{market}`을 S15가 이미 재활용 중 (`_build_s15`에서 s8 그대로 사용)

**구체적 변경**

| 항목 | 현행 | 병합 후 |
|------|------|--------|
| 파일 | s8_golden_cross.py + s9_pullback.py + s15_momentum_align.py | strategy_8_golden_cross.py (통합) |
| 신호명 | S8_GOLDEN_CROSS / S9_PULLBACK_SWING / S15_MOMENTUM_ALIGN | 유지 (하위 호환) |
| 공유 유틸 | MA/RSI/MACD 각 파일에 중복 계산 로직 | 파일 내 공통 헬퍼로 통합 |
| 삭제 파일 | — | strategy_9_pullback.py, strategy_15_momentum_align.py |

**통합 파일 구조 예시**
```
strategy_8_golden_cross.py
├── _calc_ma_rsi_macd()      # 공통: MA/RSI/MACD 일괄 계산
├── _calc_bollinger()         # 공통: 볼린저 밴드
├── scan_golden_cross()       # S8: MA5 골든크로스 신호
├── scan_pullback_swing()     # S9: 정배열 눌림목 신호
└── scan_momentum_align()     # S15: 다중지표 모멘텀 신호
```

**strategy_runner.py 변경**
```python
# 변경 전
from strategy_9_pullback import scan_pullback_swing
from strategy_15_momentum_align import scan_momentum_align

# 변경 후
from strategy_8_golden_cross import scan_pullback_swing
from strategy_8_golden_cross import scan_momentum_align
```

**candidates_builder.py 변경**
- `_build_s15()` 함수 제거 (S8 풀 직접 사용으로 통합)
- `_build_s9()` 풀 삭제 검토 (S8과 flu_rt 범위 유사)

---

### 3단계: S3 + S5 + S11 → `strategy_3_inst_foreign.py`

**병합 근거**
- 세 전략 모두 **외인/기관/프로그램 수급** 추적이라는 동일 테마
- 비슷한 시간대(09:30~14:30) 활성화
- 동일 스윙 보유기간(3~7거래일)
- scorer.py에서 모두 `demand_score` 중심으로 동일하게 평가

**구체적 변경**

| 항목 | 현행 | 병합 후 |
|------|------|--------|
| 파일 | s3_inst_foreign.py + s5_program_buy.py + s11_frgn_cont.py | strategy_3_inst_foreign.py (통합) |
| 신호명 | S3_INST_FRGN / S5_PROG_FRGN / S11_FRGN_CONT | 유지 (하위 호환) |
| 삭제 파일 | — | strategy_5_program_buy.py, strategy_11_frgn_cont.py |

**주의**: S5는 ka90003 (프로그램 순매수) API로 다른 API를 사용하므로 API 호출 로직은 분리 유지

---

## 단독 유지 전략 (6개)

| 파일 | 유지 이유 |
|------|---------|
| strategy_2_vi_pullback.py | Java → `vi_watch_queue` Redis 이벤트 기반 완전 별개 경로 |
| strategy_4_big_candle.py | 5분봉 실시간, 다른 전략과 타임프레임 이질적 |
| strategy_6_theme.py | ka90001/ka90002 테마 그룹 API, 로직 완전 독자적 |
| strategy_10_new_high.py | ka10016 52주 신고가 이벤트, 맥락 다름 |
| strategy_12_closing.py | 14:30~14:50 특수 타이밍, 독립적 의미 |
| strategy_13_box_breakout.py | 박스권 감지 로직(15일 범위 계산) 독자적 |
| strategy_14_oversold_bounce.py | RSI 20~38 역발상 반등, S8/S9와 정반대 시장 국면 |

---

## 통폐합 결과 요약

```
15개 → 9개 (40% 감소)

[병합]
  strategy_1_gap_opening.py  ←  strategy_7_auction.py       (1단계)
  strategy_8_golden_cross.py ←  strategy_9_pullback.py      (2단계)
                             ←  strategy_15_momentum_align.py
  strategy_3_inst_foreign.py ←  strategy_5_program_buy.py   (3단계)
                             ←  strategy_11_frgn_cont.py

[유지]
  strategy_2_vi_pullback.py
  strategy_4_big_candle.py
  strategy_6_theme.py
  strategy_10_new_high.py
  strategy_12_closing.py
  strategy_13_box_breakout.py
  strategy_14_oversold_bounce.py
```

---

## 수정 대상 파일 요약

### 1단계 (S1+S7)
| 파일 | 변경 내용 |
|------|---------|
| `ai-engine/strategy_1_gap_opening.py` | S7 함수 4개 추가 (`_clean_num`, `fetch_gap_rank`, `fetch_credit_filter`, `scan_auction_signal`) |
| `ai-engine/strategy_7_auction.py` | **삭제** |
| `ai-engine/strategy_runner.py` | S7 임포트 경로 변경 (1줄) |

### 2단계 (S8+S9+S15)
| 파일 | 변경 내용 |
|------|---------|
| `ai-engine/strategy_8_golden_cross.py` | S9/S15 함수 흡수, 공통 MA/RSI 헬퍼 추출 |
| `ai-engine/strategy_9_pullback.py` | **삭제** |
| `ai-engine/strategy_15_momentum_align.py` | **삭제** |
| `ai-engine/strategy_runner.py` | S9/S15 임포트 경로 변경 (2줄) |
| `ai-engine/candidates_builder.py` | `_build_s9()`, `_build_s15()` 통합 검토 |

### 3단계 (S3+S5+S11)
| 파일 | 변경 내용 |
|------|---------|
| `ai-engine/strategy_3_inst_foreign.py` | S5/S11 함수 흡수 |
| `ai-engine/strategy_5_program_buy.py` | **삭제** |
| `ai-engine/strategy_11_frgn_cont.py` | **삭제** |
| `ai-engine/strategy_runner.py` | S5/S11 임포트 경로 변경 (2줄) |

> **변경 없음**: scorer.py, overnight_scorer.py, candidates_builder.py (대부분), analyzer.py
> 이유: 신호명(S1_GAP_OPEN, S7_AUCTION 등)이 유지되므로 해당 파일은 무변경

---

## 기대 효과

| 항목 | 현행 | 통폐합 후 |
|------|------|--------|
| 전략 파일 수 | 15개 | 9개 |
| ka10081 API 호출 중복 | S8/S9/S15 × 2시장 = 6회 | 1파일 내 공유 = 절감 가능 |
| Redis candidates 풀 키 | 15종 | 개선 가능 |
| 신호 추적 이력 | 변경 없음 | 변경 없음 (신호명 유지) |

---

## 단계별 실행 권장 순서

1. **1단계 (S1+S7)**: 가장 안전, 2시간 이내 작업 가능
2. **2단계 (S8+S9+S15)**: 공통 헬퍼 추출이 핵심, 반나절 작업
3. **3단계 (S3+S5+S11)**: API 소스가 달라 검토 필요, 하루 작업

각 단계 완료 후 **동일 날짜 기준 신호 재현 테스트** 수행 권장.
