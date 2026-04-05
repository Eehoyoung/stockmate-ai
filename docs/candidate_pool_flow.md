# Candidate Pool Flow — S1~S15 종목 후보 흐름 전체 정리

> 기준일: 2026-04-05 (갱신)
> 관련 파일: `candidates_builder.py`, `strategy_runner.py`, `strategy_N_*.py`, `vi_watch_worker.py`

---

## 전체 구조 요약

```
[Python ai-engine] candidates_builder.py
  ├── 장전 (07:25~09:10, 3분 주기): S1, S7, S2
  └── 장중 (09:05~14:55, 10분 주기): S2~S6, S8~S15 전체
       └── Kiwoom REST API 호출 → 필터링
            └── Redis LPUSH → candidates:s{N}:{market}  (TTL 3~30분)
                              │
                              ▼
[Python ai-engine] strategy_runner.py
  ├── Redis LRANGE → candidates:s{N}:{market}
  └── strategy_{N}.py 함수 호출 → 정밀 필터 → 신호 생성
                              │
                              ▼
              telegram_queue (Redis LPUSH)
```

> ⚠️ **Java CandidateService는 더 이상 풀 적재를 담당하지 않음.**
> 모든 candidates:s{N}:{market} 키는 Python candidates_builder.py 가 단독 관리.

---

## 전략별 후보 풀 현황 요약표

| 전략 | Redis 키 | Python 빌드 API | 장전/장중 | TTL | Python 소비 방식 |
|------|---------|----------------|---------|-----|----------------|
| S1 | `candidates:s1:{mkt}` | ka10029 (갭 3~15%) | 장전+장중 | 3분 | ✅ 풀 필수 |
| S2 | `candidates:s2:{mkt}` | ka10054 (VI 발동) | 장전+장중 | 5분 | ✅ vi_watch_worker 보완 |
| S3 | `candidates:s3:{mkt}` | ka10065 (외인∩기관계) | 장중 | 10분 | ✅ 풀 우선, fallback |
| S4 | `candidates:s4:{mkt}` | ka10027 (2~20%) | 장중 | 5분 | ✅ 풀 필수 |
| S5 | `candidates:s5:{mkt}` | ka90003 (프로그램순매수) | 장중 | 10분 | ✅ 풀 우선, fallback |
| S6 | `candidates:s6:{mkt}` | ka90001→ka90002 (테마) | 장중 | 5분 | ✅ 풀 필터로 활용 |
| S7 | `candidates:s7:{mkt}` | ka10029 (갭 2~10%) | 장전+장중 | 3분 | ✅ 풀 우선, fallback |
| S8 | `candidates:s8:{mkt}` | ka10027 (0.5~8%) | 장중 | 20분 | ✅ 풀 필수 (경고) |
| S9 | `candidates:s9:{mkt}` | ka10027 (0.3~5%) | 장중 | 20분 | ✅ 풀 필수 (경고) |
| S10 | `candidates:s10:{mkt}` | ka10016 (52주 신고가) | 장중 | 20분 | ✅ 풀 우선, fallback |
| S11 | `candidates:s11:{mkt}` | ka10035 (외인 3일 연속) | 장중 | 30분 | ✅ 풀 우선, fallback |
| S12 | `candidates:s12:{mkt}` | ka10032 (거래대금상위) | 장중 | 10분 | ⚠️ 풀 적재는 하나 전략 미사용 |
| S13 | `candidates:s13:{mkt}` | S8풀 ∪ S10풀 | 장중 | 20분 | ✅ 풀 필수 |
| S14 | `candidates:s14:{mkt}` | ka10027 (하락 3~10%) | 장중 | 20분 | ✅ 풀 필수 |
| S15 | `candidates:s15:{mkt}` | S8풀 재활용 | 장중 | 20분 | ✅ 풀 필수 |
| (구형) | `candidates:{mkt}` | — | — | — | ❌ 미사용, 점진적 제거 중 |

> `{mkt}`: `001` = 코스피, `101` = 코스닥  
> 총 30개 키 (15전략 × 2시장) 모두 Python candidates_builder.py 단독 생성

---

## 1. candidates:001 / candidates:101 (구형 공용 풀)

- **상태**: 미사용 (점진적 제거 중, CLAUDE.md P1)
- Java CandidateService.getCandidates() 가 브리핑용으로 적재하던 키
- strategy_runner.py 어떤 전략도 이 키를 읽지 않음

---

## 2. S1 — 갭상승 시초가 (`candidates:s1:{market}`)

### 빌드 흐름
```
candidates_builder._build_pre_market()  [07:25~09:10, 3분 주기]
  └─ _build_s1(token, market, rdb)
       └─ ka10029 예상체결등락률상위
            필터: 3.0% ≤ flu_rt ≤ 15.0%, 만주 이상, 관리종목 제외, 1천원 이상
            최대: 100개 / TTL: 180s
            → Redis RPUSH candidates:s1:001, candidates:s1:101
```

### Python 소비 흐름
```
strategy_runner.py [08:30~09:10 활성]
  └─ LRANGE candidates:s1:001 + candidates:s1:101  (최대 100개)
       └─ strategy_1_gap_opening.scan_gap_opening(token, candidates)
            ├─ Redis ws:expected:{stk_cd} 예상체결가/등락률 조회
            ├─ 필터: 예상 등락률 ≥ 2.5%, 예상체결가 > 0
            ├─ fetch_cntr_strength() → 체결강도 ≥ 120%
            └─ score = gap_pct * 0.5 + (strength - 100) * 0.5
                 상위 5개 → telegram_queue
```

---

## 3. S2 — VI 눌림목 재진입 (`candidates:s2:{market}`)

### 빌드 흐름
```
candidates_builder._build_s2()  [장전+장중 갱신]
  └─ ka10054 변동성완화장치발동종목
       필터: 상승방향(motn_drc=1), open_pric_pre_flu_rt > 0
       최대: 50개 / TTL: 300s
       → Redis RPUSH candidates:s2:001, candidates:s2:101
```

### Python 소비 흐름
```
websocket-listener (ws_client.py, 1h VI 이벤트)
  └─ redis_writer.write_vi_event()
       └─ vi_watch_queue LPUSH {stk_cd, vi_price, watch_until, is_dynamic}

vi_watch_worker.run_vi_watch_worker()  [장중 상시]
  ├─ vi_watch_queue RPOP → check_vi_pullback() 실행 (Primary)
  └─ vi_watch_queue 공백 시 30초마다:
       └─ _supplement_from_pool(rdb)  (Supplemental)
            ├─ candidates:s2:001/101 LRANGE → 미처리 종목 확인
            ├─ vi:{stk_cd} 해시 존재 여부 확인 (WS 이벤트 선수신 필요)
            └─ vi_watch_queue LPUSH → check_vi_pullback() 재사용
```

---

## 4. S3 — 외인+기관 동시 순매수 (`candidates:s3:{market}`)

### 빌드 흐름
```
candidates_builder._build_s3()  [장중 10분 주기]
  └─ asyncio.gather(
       _fetch_ka10065_set(token, market, "9000"),  # 외인
       _fetch_ka10065_set(token, market, "9999"),  # 기관계
     ) → 교집합 추출
     최대: 100개 / TTL: 600s
     → Redis RPUSH candidates:s3:001, candidates:s3:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~14:30 활성]
  └─ strategy_3_inst_foreign.scan_inst_foreign(token, market, rdb)
       ├─ LRANGE candidates:s3:{market} → pool_set 구성 [풀 우선]
       ├─ ka10063 장중투자자별매매 smtm_netprps_tp=1 전수 조회
       ├─ pool_set ∩ ka10063결과 교집합
       ├─ ka10131 기관외국인연속매매 3일 연속 순매수 맵 교차
       ├─ 최대 10개에 대해 ka10055 당일/전일 거래량 비교 → vol_ratio ≥ 1.5
       └─ 통과 시 → telegram_queue (상위 5개)
       ※ 풀 없으면 ka10063 결과 전체 사용 (fallback)
```

---

## 5. S4 — 장대양봉 추격 (`candidates:s4:{market}`)

### 빌드 흐름
```
candidates_builder._build_s4()  [장중 10분 주기]
  └─ ka10027 전일대비등락률상위 (sort_tp=1)
       필터: 2.0% ≤ flu_rt ≤ 20.0%
       정렬: ws:strength:{stk_cd} ≥ 120 종목 우선 (LPUSH LIST → lindex 0)
       최대: 100개 / TTL: 300s
       → Redis RPUSH candidates:s4:001, candidates:s4:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~14:30 활성]
  └─ LRANGE candidates:s4:001 + candidates:s4:101  (최대 30개)
       └─ strategy_4_big_candle.check_big_candle(token, stk_cd) 순차 실행
            ├─ ka10080 5분봉차트 조회
            ├─ 필터: 양봉 몸통 ≥ 2.5%, 몸통비율 ≥ 65%, 거래량 직전5봉 대비 ≥ 3배
            ├─ 전고점(96봉) 돌파 확인
            ├─ Redis ws:strength:{stk_cd} 체결강도 3분 평균 ≥ 120%
            └─ 조건 통과 시 → telegram_queue (최대 5개)
```

---

## 6. S5 — 프로그램+외인 순매수 (`candidates:s5:{market}`)

### 빌드 흐름
```
candidates_builder._build_s5()  [장중 10분 주기]
  └─ ka90003 프로그램순매수상위50
       mrkt_tp: 001→P00101, 101→P10102
       필터: prm_netprps_amt > 0
       최대: 100개 / TTL: 600s
       → Redis RPUSH candidates:s5:001, candidates:s5:101
```

### Python 소비 흐름
```
strategy_runner.py [10:00~14:00 활성]
  └─ strategy_5_program_buy.scan_program_buy(token, market, rdb)
       ├─ LRANGE candidates:s5:{market} → pool_set 구성 [풀 우선]
       ├─ ka90003 프로그램순매수상위50 전수 조회 → overlap_raw
       ├─ pool_set ∩ overlap_raw 교집합 (순매수금액 상위 15개)
       └─ 각 종목:
            ├─ ka10044 전일 기관 순매수 리스트 확인
            ├─ ka10080 5분봉 5이평선 위 확인
            └─ 통과 시 → telegram_queue (상위 5개)
       ※ 풀 없으면 overlap_raw 전체 사용 (fallback)
```

---

## 7. S6 — 테마 후발주 (`candidates:s6:{market}`)

### 빌드 흐름
```
candidates_builder._build_s6()  [장중 10분 주기, 루프 외부 1회]
  └─ ka90001 테마그룹별 상위등락률 → 상위 5테마 코드 추출
       └─ 각 테마: ka90002 테마구성종목 조회
            필터: flu_rt < 5.0 (선도주 제외)
            최대: 150개 / TTL: 300s
            → Redis RPUSH candidates:s6:001, candidates:s6:101
            ※ 테마는 시장 구분 없음 → 001/101 동일 풀 적재
```

### Python 소비 흐름
```
strategy_runner.py [09:30~13:00 활성]
  └─ strategy_6_theme.scan_theme_laggard(token, rdb)
       ├─ LRANGE candidates:s6:001 → pool_set 구성
       ├─ ka90001 테마그룹별 상위등락률 (상위 10개 테마, 테마 자체 ≥ 2%)
       └─ 각 테마:
            ├─ ka90002 테마구성종목 조회
            ├─ pool_set 필터: pool_set에 없는 종목 skip
            ├─ 등락률 분포 P70 임계값 계산
            ├─ 후발주 필터: 0.5% ≤ flu_rt < P70, flu_rt < 7%
            ├─ fetch_cntr_strength() → 체결강도 ≥ 115%
            └─ 통과 시 → telegram_queue (체결강도 상위 5개)
```

---

## 8. S7 — 동시호가 (`candidates:s7:{market}`)

### 빌드 흐름
```
candidates_builder._build_pre_market()  [07:25~09:10, 3분 주기]
  └─ _build_s7(token, market, rdb)
       └─ ka10029 예상체결등락률상위
            필터: 2.0% ≤ flu_rt ≤ 10.0%, 만주 이상, 관리종목 제외, 1천원 이상
            최대: 100개 / TTL: 180s
            → Redis RPUSH candidates:s7:001, candidates:s7:101
```

### Python 소비 흐름
```
strategy_runner.py [08:30~09:00 활성]
  └─ strategy_7_auction.scan_auction_signal(token, market, rdb)
       ├─ LRANGE candidates:s7:{market} → gap_candidates 구성 [풀 우선]
       ├─ ka10033 신용비율상위 → 고신용 종목 제외
       └─ 교집합 종목:
            ├─ Redis ws:hoga:{stk_cd} 호가잔량 조회 (0D WebSocket)
            ├─ 필터: 갭 2~10%, 매수/매도 잔량비 ≥ 2.0
            └─ 통과 시 → telegram_queue (잔량비 상위 5개)
       ※ 풀 없으면 ka10029 직접 호출 (fallback)
```

---

## 9. S8 — 5일선 골든크로스 스윙 (`candidates:s8:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [09:05~14:55, 10분 주기]
  └─ _build_s8(token, market, rdb)
       └─ ka10027 전일대비등락률상위
            필터: 0.5% ≤ flu_rt ≤ 8.0%, 만주 이상, 관리종목 제외
            최대: 150개 / TTL: 1200s
            → Redis RPUSH candidates:s8:001, candidates:s8:101
```

### Python 소비 흐름
```
strategy_runner.py [10:00~14:30 활성]
  └─ LRANGE candidates:s8:001 + candidates:s8:101  (최대 30개)
       └─ strategy_8_golden_cross.scan_golden_cross(token, rdb)
            └─ 각 종목:
                 ├─ ma_utils.fetch_daily_candles() → ka10081 일봉 60봉 이상
                 ├─ detect_golden_cross() → MA5 > MA20 크로스 또는 3일 이내 근접 (이격 ≤ 5%)
                 ├─ 필터: MA60 × 0.95 이상, 거래량 ≥ MA20 × 1.3, 등락률 0~15%
                 ├─ RSI(14) ≤ 75 하드게이트
                 ├─ calc_macd() → histogram 가속 보너스
                 └─ 통과 시 → telegram_queue (점수 상위 5개)
       ※ 풀 없으면 경고 로그 후 [] 반환 (fallback 없음)
```

---

## 10. S9 — 정배열 눌림목 스윙 (`candidates:s9:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [09:05~14:55, 10분 주기]
  └─ _build_s9(token, market, rdb)
       └─ ka10027 전일대비등락률상위
            필터: 0.3% ≤ flu_rt ≤ 5.0%, 만주 이상, 관리종목 제외
            최대: 150개 / TTL: 1200s
            → Redis RPUSH candidates:s9:001, candidates:s9:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~13:00 활성]
  └─ LRANGE candidates:s9:001 + candidates:s9:101  (최대 30개)
       └─ strategy_9_pullback.scan_pullback_swing(token, rdb)
            └─ 각 종목:
                 ├─ ka10081 일봉 62봉 이상
                 ├─ detect_pullback_setup() → MA5 > MA20 > MA60 정배열 + MA5 ±3% 이내
                 ├─ MA20 이격 ≤ 15%, 당일 양봉, 거래량 ≥ 전일 × 1.1
                 ├─ RSI(14) ≤ 68 하드게이트
                 ├─ calc_stochastic() → %K > %D 골든크로스 보너스
                 └─ 통과 시 → telegram_queue (점수 상위 5개)
       ※ 풀 없으면 경고 로그 후 [] 반환 (fallback 없음)
```

---

## 11. S10 — 52주 신고가 돌파 스윙 (`candidates:s10:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [09:05~14:55, 10분 주기]
  └─ _build_s10(token, market, rdb)
       └─ ka10016 신고저가요청 (ntl_tp=1, dt=250, 52주 신고가)
            필터: stk_cd 유효값만, 관리종목 제외
            최대: 100개 / TTL: 1200s
            → Redis RPUSH candidates:s10:001, candidates:s10:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~14:30 활성, market="000" 전체]
  └─ strategy_10_new_high.scan_new_high_swing(token, "000", rdb)
       ├─ LRANGE candidates:s10:001 + candidates:s10:101 → pool_codes [풀 우선]
       ├─ ws:tick:{stk_cd} 로 flu_rt/cur_prc 보완
       ├─ ka10023 거래량급증 병렬 조회
       ├─ 필터: 등락률 2~15%, 거래량급증률 ≥ 100%
       ├─ fetch_cntr_strength() + fetch_hoga() 수급 보완
       ├─ ma_utils.get_ma_context() → MA20 이격 25% 초과 제외
       └─ 통과 시 → telegram_queue (점수 상위 5개)
       ※ 풀 없으면 ka10016+ka10023 전수 조회 (fallback)
```

---

## 12. S11 — 외국인 연속 순매수 스윙 (`candidates:s11:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [09:05~14:55, 10분 주기]
  └─ _build_s11(token, market, rdb)
       └─ ka10035 외인연속순매매상위 (trde_tp=2, base_dt_tp=1)
            필터: dm1>0, dm2>0, dm3>0, tot>0 (3일 연속 순매수)
            최대: 80개 / TTL: 1800s
            → Redis RPUSH candidates:s11:001, candidates:s11:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~14:30 활성]
  └─ strategy_11_frgn_cont.scan_frgn_cont_swing(token, market, rdb)
       ├─ LRANGE candidates:s11:{market} → pool_set 구성 [풀 우선]
       ├─ ka10035 직접 조회 → 풀 교집합 필터
       ├─ Redis ws:tick:{stk_cd} → flu_rt 0~10%, cntr_str ≥ 100%
       └─ 통과 시 → telegram_queue (점수 상위 5개)
       ※ 풀 없으면 ka10035 전체 결과 사용 (fallback)
```

---

## 13. S12 — 종가 강도 확인 매수 (`candidates:s12:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [09:05~14:55, 10분 주기]
  └─ _build_s12(token, market, rdb)
       └─ ka10032 거래대금상위 (mang_stk_incls=0)
            필터: flu_rt > 0 (양전 종목만)
            최대: 50개 / TTL: 600s
            → Redis RPUSH candidates:s12:001, candidates:s12:101
```

### Python 소비 흐름
```
strategy_runner.py [14:30~14:50 활성]
  └─ strategy_12_closing.scan_closing_buy(token, market, rdb)
       ├─ ka10027 등락률상위 직접 호출 (candidates:s12:* 풀 미사용)
       ├─ ka10063 기관 당일 순매수 집합 병렬 수집
       ├─ 교집합 종목 필터: 4% ≤ flu_rt ≤ 15%, cntr_str ≥ 110%
       └─ 통과 시 → telegram_queue (점수 상위 5개)

⚠️ 풀 적재는 하나 strategy_12_closing.py 가 이를 사용하지 않음.
   Java 풀(ka10032 거래대금 기준)과 Python 스캔(ka10027+ka10063) 기준이 달라
   사실상 독립적으로 동작. (by design)
```

---

## 14. S13 — 박스권 돌파 스윙 (`candidates:s13:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [S8·S10 빌드 완료 후 즉시]
  └─ _build_s13(market, rdb)
       └─ candidates:s8:{market} ∪ candidates:s10:{market} 합산
            중복 제거 / 최대: 150개 / TTL: 1200s
            → Redis RPUSH candidates:s13:001, candidates:s13:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~14:00 활성]
  └─ LRANGE candidates:s13:001 + candidates:s13:101  (최대 30개)
       └─ strategy_13_box_breakout.scan_box_breakout(token, rdb)
            └─ 각 종목:
                 ├─ ka10081 일봉 130봉
                 ├─ detect_box_breakout() → 15일 박스권(고저 ≤ 8%) 상단 돌파
                 ├─ 필터: 양봉, 거래량 ≥ 15일평균 × 2, 현재가 ≥ MA20
                 ├─ MA120 저항선 페널티 적용
                 ├─ calc_bollinger() → 밴드폭 < 6% 스퀴즈 보너스
                 ├─ calc_mfi() > 55 자금유입 보너스
                 ├─ Redis ws:tick 체결강도 ≥ 120%, flu_rt 0~20%
                 └─ 통과 시 → telegram_queue (점수 상위 5개)
```

---

## 15. S14 — 과매도 반등 스윙 (`candidates:s14:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [09:05~14:55, 10분 주기]
  └─ _build_s14(token, market, rdb)
       └─ ka10027 전일대비등락률 하락상위 (sort_tp=3)
            필터: 3.0% ≤ abs(flu_rt) ≤ 10.0%, 만주 이상, 관리종목 제외
            최대: 100개 / TTL: 1200s
            → Redis RPUSH candidates:s14:001, candidates:s14:101
```

### Python 소비 흐름
```
strategy_runner.py [09:30~14:00 활성]
  └─ LRANGE candidates:s14:001 + candidates:s14:101  (최대 40개)
       └─ strategy_14_oversold_bounce.scan_oversold_bounce(token, rdb)
            └─ 각 종목:
                 ├─ ka10081 일봉 65봉
                 ├─ 필수: RSI(14) 20~38, 현재가 ≥ MA60 × 0.88
                 ├─ 필수: ATR%(14) ≤ 4.0%, flu_rt ≥ -5% (급락 당일 제외)
                 ├─ 선택 3개 중 2개 이상 충족:
                 │    A. calc_stochastic() %K > %D 하단(20미만) 골든크로스
                 │    B. calc_williams_r() -80 상향 돌파
                 │    C. calc_mfi() < 30 + 반등 신호
                 └─ 통과 시 → telegram_queue (점수 상위 5개)
```

---

## 16. S15 — 다중지표 모멘텀 동조 스윙 (`candidates:s15:{market}`)

### 빌드 흐름
```
candidates_builder._build_intraday()  [S8 빌드 완료 후 즉시]
  └─ _build_s15(market, rdb)
       └─ candidates:s8:{market} 재활용
            최대: 100개 / TTL: 1200s
            → Redis RPUSH candidates:s15:001, candidates:s15:101
```

### Python 소비 흐름
```
strategy_runner.py [10:00~14:30 활성]
  └─ LRANGE candidates:s15:001 + candidates:s15:101  (최대 30개)
       └─ strategy_15_momentum_align.scan_momentum_align(token, rdb)
            └─ 각 종목:
                 ├─ ka10081 일봉 (MACD 26+9 = 최소 35봉)
                 ├─ 필수: 현재가 ≥ MA20, 등락률 0~12%, RSI < 72
                 ├─ 선택 4개 중 3개 이상 충족:
                 │    A. calc_macd() → 골든크로스 당일 또는 히스토그램 2봉 가속
                 │    B. RSI 48~68 (추세 초·중반)
                 │    C. calc_bollinger() %B 0.45~0.82
                 │    D. 거래량 ≥ MA20 × 1.3
                 ├─ 보너스: VWAP 위, ATR 1~3%, Stochastic %K>50
                 └─ 통과 시 → telegram_queue (점수 상위 5개)
```

---

## 미완료 항목 (Pending Work)

| 우선순위 | 항목 | 현재 상태 |
|---------|------|---------|
| P1 | S12 strategy_12_closing.py 가 candidates:s12:* 풀 사용하도록 전환 | 현재 ka10027+ka10063 직접 호출 |
| P2 | scorer.py S14/S15 케이스·RSI/ATR·시간대 가중치 추가 | 미구현 |
| P2 | TP/SL 6파일 구현 | 미구현 |
| P3 | OvernightRiskScheduler.java 통합 | 미통합 |
| P3 | /candidate 명령 풀 현황 표시 | 미구현 |
