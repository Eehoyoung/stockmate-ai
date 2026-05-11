# 보조지표·데이터 신선도·멀티타임프레임 개선 계획

작성일: 2026-05-11  
대상: `ai-engine`, `websocket-listener`, `api-orchestrator`

## 1. 검토 목적

기존 15개 전략의 보조지표 사용 현황을 기준으로, 추가하면 좋은 지표와 보완해야 할 지표를 재검토한다. 이번 계획은 기존 지표 추가 논의에 더해 다음 범위를 포함한다.

- 실시간 데이터 신선도 검증
- 데이터 누락 방지 및 fallback 정책
- 1분/5분/30분/60분봉 확인 체계
- 일봉/주봉 확인 체계
- 신호 시점 피처 저장과 사후 검증 가능성

## 2. 현재 확인된 구현 상태

### 2.1 이미 사용하는 주요 지표

현재 시스템은 기본 기술지표를 상당수 보유한다.

- 가격/추세: MA5, MA20, MA60, MA120, 일목균형표, 52주 신고가, 박스권 상단/하단
- 모멘텀: RSI, MACD, Stochastic, Williams %R
- 변동성/밴드: ATR, Bollinger Band, Bollinger %B, bandwidth
- 거래량/수급: volume ratio, MFI, VWAP, 체결강도, 호가 매수/매도 비율
- 리스크: R:R, ATR 기반 TP/SL, 시장국면 보너스/패널티, 시총/거래대금/섹터 과열 일부 패널티

관련 위치:

- [scorer.py](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/scorer.py)
- [ma_utils.py](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/ma_utils.py)
- [indicator_volume.py](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/indicator_volume.py)
- [V6__create_daily_indicators.sql](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/api-orchestrator/src/main/resources/db/migration/V6__create_daily_indicators.sql)
- [V3__create_signal_score_components.sql](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/api-orchestrator/src/main/resources/db/migration/V3__create_signal_score_components.sql)

### 2.2 데이터 신선도 구현 상태

`redis_reader.py`에는 실시간 Redis 데이터의 freshness 판정이 있다.

현재 cutoff:

- `hoga`: caution 1초, cancel 2초
- `tick`: caution 3초, cancel 5초
- `strength`: caution 5초, cancel 10초
- `vi_active`: caution 3초, cancel 5초
- `vi_released`: caution 10초, cancel 20초

`queue_worker.py`는 freshness cancel 조건을 일부 사용한다. 다만 결측과 stale의 정책이 아직 전략별로 충분히 분리되어 있지 않고, 봉 데이터 freshness는 실시간 Redis freshness만큼 엄격하게 관리되지 않는다.

관련 위치:

- [redis_reader.py](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/redis_reader.py)
- [queue_worker.py](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/queue_worker.py)
- [position_sizing.py](/C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/position_sizing.py)

### 2.3 분봉/일봉/주봉 확인 상태

현재 코드 기준:

- 1분/5분/30분/60분봉: `ka10080` 기반 `fetch_minute_candles(token, stk_cd, tic_scope)` 구조상 지원 가능하다. `indicator_rsi`, `indicator_macd`, `indicator_bollinger`, `indicator_stochastic`, `indicator_atr` 주석도 `"1","3","5","10","15","30","45","60"` 범위를 명시한다.
- 실제 전략 사용: 대부분 5분봉 중심이다. 일부 분석/지표 함수는 `tic_scope` 파라미터를 받지만, 전략별로 1/30/60분봉을 체계적으로 동시에 확인하는 구조는 약하다.
- 일봉: `ka10081` 기반 `fetch_daily_candles`와 `daily_indicators` 테이블로 확인된다.
- 주봉: 코드에서 직접 주봉 API 또는 주봉 집계 사용은 명확히 확인되지 않는다. 현 단계에서는 미구현으로 보고, 일봉을 주 단위로 집계하거나 키움 주봉 API가 있다면 별도 fetcher를 추가해야 한다.

## 3. 6개 페르소나 토론 요약

### 3.1 스캘퍼

기존 RSI/MACD/볼린저를 더 늘리는 것은 급등주 false positive를 줄이는 데 한계가 있다. 급등/VI/장대양봉/박스 돌파에서는 거래량의 크기보다 방향과 지속성이 중요하다.

주장:

- `CVD`, `체결 방향 델타`, `aggressive_buy_ratio`가 필요하다.
- `anchored VWAP`은 VI 발동/해제, 장대양봉 시작, 박스 돌파 시점을 기준으로 잡아야 한다.
- 5분봉 캐시 TTL 300초는 초단타 기준으로 길다.
- 현재봉 `index 0`을 확정봉처럼 쓰면 봉 중간 고점 추격 신호가 생긴다.

반박받은 지점:

- 필터를 hard gate로 바로 넣으면 좋은 급등 초입을 놓칠 수 있다.
- 처음에는 shadow feature로 저장하고 검증 후 승격해야 한다.

### 3.2 추세추종/스윙

호가와 체결은 진입 타이밍에는 유효하지만 3~10거래일 지속성은 일봉 추세와 상대강도가 결정한다.

주장:

- `ADX/DMI`, `MA20/MA60 slope`, `relative strength vs index/sector`가 필요하다.
- S8/S10/S13/S15는 돌파 발생보다 돌파선 유지가 중요하다.
- S13의 `pre_breakout_volume_contraction`은 이미 계산되므로 핵심 점수로 승격해야 한다.
- 30분/60분봉은 스윙 진입 전 상위 프레임 확인용으로 써야 한다.

반박받은 지점:

- MA와 ADX는 후행성이 있다.
- 실시간 진입 직전에는 1분/5분 orderflow가 없으면 추격 매수가 될 수 있다.

### 3.3 평균회귀

과매도는 싸다는 뜻이 아니라 아직 팔리는 중일 수 있다.

주장:

- S14/S9/S12에는 `VWAP reclaim`, `저점 재확인 실패`, `RSI/MFI divergence`, `%B re-entry`가 필요하다.
- 1분봉은 반전 트리거, 5분봉은 반전 확인, 30분/60분봉은 하락 추세 회피에 사용해야 한다.
- 일봉 RSI만으로 반등을 판단하면 떨어지는 칼날을 잡는다.

반박받은 지점:

- 확인을 너무 기다리면 평균회귀 초입 수익을 놓친다.
- 강한 추세주에서는 RSI 60~75가 과열이 아니라 정상 추세 구간일 수 있다.

### 3.4 수급/마켓마이크로스트럭처

총매수잔량/총매도잔량 비율은 허수잔량에 취약하다.

주장:

- `1~5호가 imbalance`, `imbalance persistence`, `cancel_rate`, `ask wall absorption`이 필요하다.
- `거래대금 가속도`와 `가격 전진 효율`이 없으면 거래량 폭발과 매물 소화를 구분하지 못한다.
- 분봉보다 초 단위 snapshot과 rolling window가 더 중요하다.

반박받은 지점:

- 호가/체결 데이터는 노이즈가 많다.
- 단일 snapshot이 아니라 3~20초 persistence로만 사용해야 한다.

### 3.5 리스크/포트폴리오

지표보다 중요한 것은 신호 점수와 계좌 손실 단위의 연결이다.

주장:

- `risk_per_trade = entry - stop` 기준 sizing이 필요하다.
- 일중 손실 kill switch, 섹터/테마 집중도 제한, 변동성 기반 size 축소가 우선이다.
- stale data는 score 감점이 아니라 전략별로 `CANCEL`, `SHADOW`, `SIZE_DOWN` 중 하나로 명확히 처리해야 한다.

반박받은 지점:

- 너무 보수적으로 막으면 신호 수가 급감한다.
- 따라서 전략별 기대값 검증 후 gate 강도를 조절해야 한다.

### 3.6 퀀트/검증

모든 페르소나 주장은 저장 피처와 결과 라벨이 있어야 검증 가능하다.

주장:

- 신호 시점의 전체 `feature_snapshot_json`이 필요하다.
- `source_latency_ms`, `missing_feature_flags`, `freshness_status`, `candle_scope_status`를 저장해야 한다.
- `MFE`, `MAE`, `TP/SL first touch`, `slippage_bps`, `net_pnl_after_cost`가 없으면 지표의 실효성을 판단할 수 없다.
- 주봉/60분봉 같은 상위 프레임을 추가하더라도 versioning과 ablation이 없으면 과최적화가 된다.

반박받은 지점:

- 검증 체계를 완성하기 전까지 개선 속도가 느려질 수 있다.
- 타협안은 새 지표를 바로 hard gate로 쓰지 말고 shadow 저장부터 시작하는 것이다.

## 4. 최종 합의안

### 4.1 데이터 신선도 정책

데이터 신선도는 모든 신호의 공통 선행 조건으로 둔다.

#### 실시간 Redis 데이터

현재 cutoff는 유지하되, 신호 payload에 다음을 반드시 저장한다.

- `freshness.tick.state`
- `freshness.tick.age_ms`
- `freshness.hoga.state`
- `freshness.hoga.age_ms`
- `freshness.strength.state`
- `freshness.strength.age_ms`
- `freshness.vi.state`
- `freshness.vi.age_ms`
- `freshness_decision`: `PASS`, `CAUTION`, `SIZE_DOWN`, `SHADOW`, `CANCEL`

전략별 기본 정책:

- S1/S2/S4/S10/S12/S13: tick 또는 hoga cancel이면 `CANCEL`
- S8/S9/S14/S15: tick stale은 `SHADOW` 또는 `SIZE_DOWN`, hoga missing은 감점 가능
- S3/S5/S11: 실시간 수급 REST 기반 신호는 tick stale만으로 즉시 cancel하지 않고 `SHADOW` 가능

#### 봉 데이터

봉 데이터에도 freshness를 추가한다.

- `candle_scope`: `1m`, `5m`, `30m`, `60m`, `1d`, `1w`
- `candle_latest_ts`
- `candle_age_ms`
- `candle_count`
- `expected_min_count`
- `is_current_bar_closed`
- `source`: `REST`, `CACHE`, `AGGREGATED`, `FALLBACK`
- `cache_hit`
- `cache_ttl_remaining_ms`
- `missing_reason`

분봉 캐시 TTL 권고:

- 1분봉: 10~20초
- 5분봉: 30~60초
- 30분봉: 3~5분
- 60분봉: 5~10분
- 일봉: 장중에는 10~30분, 장마감 후 확정 캐시는 당일 고정
- 주봉: 장중 집계는 30~60분, 주말/장마감 확정 후 고정

현재 `RSI_MIN_CACHE_TTL_SEC=300` 계열은 1분/5분 초단타 검증에는 길다. scope별 TTL 분리가 필요하다.

### 4.2 데이터 누락 방지 정책

결측을 무조건 기본값 `0` 또는 `100`으로 대체하지 않는다. 결측은 신호 품질의 일부로 저장하고, 전략별 처리 정책을 분리한다.

필수 저장 필드:

- `missing_feature_flags`: 누락된 피처 목록
- `fallback_used`: true/false
- `fallback_source`: `WS`, `REST`, `DAILY_CANDLE`, `PREVIOUS_CACHE`, `NONE`
- `fallback_confidence`: `HIGH`, `MEDIUM`, `LOW`
- `data_quality_score`: 0~100
- `data_quality_decision`: `PASS`, `SHADOW`, `SIZE_DOWN`, `CANCEL`

하드 결측:

- 현재가 없음
- 진입가 없음
- 전략 필수 봉 개수 부족
- TP/SL 계산 불가
- 실시간 전략에서 tick/hoga가 cancel 상태

소프트 결측:

- hoga missing but tick fresh
- strength missing but tick fresh
- 일부 보조지표 warm-up 부족
- sector/theme 정보 없음
- market cap 없음

소프트 결측은 `SHADOW` 또는 `SIZE_DOWN`으로 시작하고, 성과 검증 후 hard gate 여부를 정한다.

## 5. 멀티타임프레임 확인 체계

### 5.1 1분봉

용도:

- 진입 직전 orderflow 확인
- 고점 유지율/follow-through 확인
- VWAP 재탈환 확인
- VI 해제 후 재유입 확인

추천 지표:

- 1분 VWAP
- 1분 거래대금 가속도
- 1분 CVD slope
- 최근 1~3개 1분봉 고점/저점 유지
- 1분 ATR 또는 range 확장

적용 전략:

- S1, S2, S4, S10, S12, S13 우선

### 5.2 5분봉

용도:

- 현재 주력 단기 확인 프레임
- 장대양봉/눌림/돌파 후 유지 확인
- 분봉 RSI/MACD/ATR/VWAP 확인

추천 보완:

- 현재봉과 확정봉 분리
- `index 0`은 진행봉, `index 1`은 확정봉으로 명시
- 신호 발생 시 `current_bar_progress_pct` 저장
- 5분봉 캐시 TTL을 30~60초로 축소

적용 전략:

- S2, S4, S7, S10, S13, S15

### 5.3 30분봉

용도:

- 장중 상위 추세 확인
- 5분봉 속임수 제거
- 평균회귀에서 하락 추세 회피

추천 지표:

- 30분 MA20 slope
- 30분 RSI range
- 30분 VWAP/MA20 상하 위치
- 30분 고점/저점 구조

적용 전략:

- S8, S9, S10, S13, S14, S15

### 5.4 60분봉

용도:

- 스윙 진입 전 큰 방향성 확인
- 일봉 신호가 너무 느릴 때 중간 프레임으로 사용

추천 지표:

- 60분 MA20/MA60 slope
- 60분 ADX/DMI
- 60분 전고점/전저점
- 60분 Bollinger bandwidth

적용 전략:

- S7, S8, S9, S10, S13, S15

### 5.5 일봉

용도:

- 후보군 선별
- 추세 구조, 박스, 신고가, ATR, 거래량 기준선 계산

현재 상태:

- `ka10081`과 `daily_indicators` 테이블로 지원된다.

보완:

- 일봉 indicator snapshot에 `source_date`, `computed_at`, `is_final_daily_bar` 추가
- 장중 일봉과 장마감 확정 일봉을 구분
- 일봉 기반 신호라도 진입 전 1분/5분 freshness를 확인

### 5.6 주봉

현재 상태:

- 코드상 직접 주봉 fetcher 또는 주봉 indicator 저장은 확인되지 않는다.

추가 방식:

- 1안: 키움 주봉 API가 있으면 `fetch_weekly_candles` 추가
- 2안: 일봉을 ISO week 또는 한국 거래주 기준으로 집계해 주봉 생성

추천 주봉 지표:

- 주봉 MA10/MA20
- 주봉 RSI
- 주봉 MACD histogram
- 주봉 52주 고점/저점
- 주봉 거래량 평균 대비 현재 주 거래량

사용 목적:

- 장기 하락 추세 종목의 단기 반등 추격 방지
- 신고가/박스 돌파의 상위 프레임 저항 확인
- S7/S8/S10/S13/S15의 스윙 품질 필터

## 6. 추가 지표 우선순위

### P0: 저장/검증 인프라

1. `feature_snapshot_json`
2. `feature_schema_version`
3. `scorer_version`
4. `threshold_version`
5. `freshness_status`
6. `missing_feature_flags`
7. `candle_scope_status`
8. `MFE/MAE`
9. `TP/SL first touch`
10. `net_pnl_after_cost`

### P1: 실시간 품질 지표

1. CVD / 체결 방향 델타
2. aggressive buy ratio
3. 1~5호가 imbalance
4. imbalance persistence
5. cancel rate
6. ask wall absorption
7. trade value acceleration
8. price impact efficiency
9. anchored VWAP
10. RVOL by time-of-day

### P2: 추세/스윙 지표

1. ADX/DMI
2. relative strength vs index/sector
3. MA slope / linear regression slope
4. breakout retest hold
5. ATR-normalized breakout extension
6. volume dry-up and expansion
7. OBV or CMF
8. RSI range shift

### P3: 평균회귀 안전장치

1. VWAP reclaim
2. low retest failure
3. RSI/MFI divergence
4. Bollinger %B re-entry
5. downtrend ADX filter
6. volatility peak then contraction

## 7. 구현 계획 및 진행 현황

### Phase 1: 관측 가능성 보강 — ✅ 완료 (2026-05-11, commit 09896a1)

**완료 항목:**

- `queue_worker.py`에 `_compute_freshness_decision` / `_collect_missing_feature_flags` / `_compute_data_quality` 추가
- 신호 payload에 `freshness_decision`, `missing_feature_flags`, `data_quality_score`, `data_quality_decision`, `fallback_used` 저장
- 전략별 freshness 정책 분리 (strict: S1/S2/S4/S10/S12/S13 / REST기반: S3/S5/S11 / default)
- `entry_for_shadow` 필드 `cur_prc` fallback 추가 (W-2 버그 수정)
- `.env.example`에 scope별 TTL 환경변수 4개 추가

**미구현 (Phase 2 이후로 이관):**

- `ws_tick_feature_snapshot` 직접 연동 (WS listener 아키텍처 변경 필요, 별도 검토)

---

### Phase 2: scope별 candle provider 정리 — ✅ 완료 (2026-05-11, commit 76594c2)

**완료 항목:**

- `ma_utils.py` 신규 함수 추가
  - `_MIN_CACHE_TTL_BY_SCOPE`: 1m/5m/30m/60m scope별 TTL dict (환경변수 분리)
  - `_min_cache_ttl(scope)`: scope별 TTL 조회
  - `_is_bar_closed(scope)`: 봉 경계 30초 경과 여부
  - `_is_intraday_kst()`: 장중(09:00~15:30) 판별
  - `get_confirmed_candles(candles)`: 장중 진행봉 제외, 확정봉만 반환
  - `get_current_bar(candles)`: 장중이면 index 0, 장외면 None
  - `fetch_minute_candles_with_status(token, stk_cd, tic_scope)`: scope TTL 기반 캐시 + status dict 반환
  - `fetch_daily_candles_with_status(token, stk_cd)`: 장중/확정 일봉 구분 + cache hit 판별
  - `fetch_multi_scope_candles(token, stk_cd, scopes)`: 1분/5분/30분/60분 동시 조회, 오류 scope는 ERROR fallback
  - `build_weekly_candles(daily_candles)`: 일봉 ISO week 집계로 주봉 생성
- `tests/test_ma_utils.py` 24개 테스트 전부 통과

---

### Phase 3: shadow feature 운영 — ✅ 완료 (2026-05-12, commit 03116e3, 3bf26b5)

**완료 항목:**

- `shadow_features.py` 신규 모듈
  - `compute_orderbook_imbalance(hoga)`: 총잔량·1호가 imbalance ∈ [-1, 1]
  - `compute_relative_strength(signal, ctx)`: 종목 등락률 vs 지수 등락률 (rs_pct, rs_trend)
  - `compute_tick_buy_pressure(tick, ctx)`: 체결강도 + spread_pct + label (strong/moderate/weak)
  - `compute_cvd_from_candles(candles)`: OHLCV 기반 CVD 근사 (total, last5, slope, aggressive_buy_ratio)
  - `compute_anchored_vwap(candles, cur_prc)`: Day-anchored VWAP + price_vs_vwap_pct
  - `compute_adx(highs, lows, closes, period=14)`: Wilder's ADX/DMI (+DI, -DI, trend_strength, trend_direction)
  - `compute_all_shadow_features(signal, ctx, minute_candles, daily_candles)`: 통합 진입점, 개별 오류는 None 처리
- `queue_worker.py` 연동: `compute_all_shadow_features` import, `enriched` dict에 `shadow_features` 키 추가
  - 오류 발생 시 `{}` 폴백, DEBUG 로깅 — 신호 발송 절대 차단 안 함
- DB 저장 인프라
  - V44 마이그레이션: `trading_signals.shadow_features JSONB` 컬럼 추가
  - `db_writer.py` `insert_python_signal`: `$56::jsonb` 파라미터로 저장
  - `TradingSignal.java` JPA 엔티티에 `shadowFeatures String` 필드 추가
- `tests/test_shadow_features.py` 39개 테스트 전부 통과
- **전체 테스트: 649 passed** (2026-05-12 기준)

**설계 원칙 준수:**

- 0 추가 API 호출: 이미 로드된 ctx/signal/candle 데이터만 사용
- ENTER/CANCEL gate 판단에 미사용 — 순수 관측·저장만
- 개별 feature 오류가 전체 실패로 전파되지 않음

**수집 기간:** 2026-05-12 ~ 2026-05-26 (약 2주, 실거래일 기준 약 10일)

---

### Phase 4: 전략별 gate 승격 — 🔴 미착수 (개시일: 2026-05-26)

**개시 조건:**

- Phase 3 데이터 수집 최소 2주 완료
- `trading_signals.shadow_features` 에 전략별 신호 건수 충분히 확보
  - 검증 기준: ENTER 신호 기준 전략당 최소 20건 이상 (가급적 30건+)
  - S1/S4/S12 처럼 발화 빈도 낮은 전략은 기간 연장 가능

**작업 주의사항:**

1. **데이터 충분성 선확인 필수**  
   승격 전 반드시 아래 쿼리로 전략별 shadow 수집 현황 확인:
   ```sql
   SELECT strategy,
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE action = 'ENTER') AS enter_cnt,
          COUNT(*) FILTER (WHERE shadow_features IS NOT NULL) AS has_shadow
   FROM trading_signals
   WHERE created_at >= '2026-05-12'
   GROUP BY strategy ORDER BY enter_cnt DESC;
   ```
   enter_cnt < 20인 전략은 해당 회차 Phase 4에서 제외하고 계속 수집.

2. **상관관계 먼저, 임계값 나중**  
   shadow feature 분포와 ENTER 결과(MFE/MAE/수익률)의 상관관계를 먼저 계산한다.  
   임계값을 먼저 정하고 데이터를 끼워 맞추지 않는다.

3. **한 번에 하나씩 승격**  
   한 사이클에 feature 하나만 gate에 추가한다. 여러 feature를 동시에 승격하면 어떤 feature가 성과에 기여했는지 분리 불가.

4. **shadow → score bonus/penalty 우선, hard CANCEL은 마지막**  
   `score bonus/penalty` → `SIZE_DOWN` → `SHADOW` → `CANCEL` 순서로 강도를 높인다.  
   처음부터 hard CANCEL로 승격하면 좋은 신호를 잃을 수 있다.

5. **rollback 계획 필수**  
   각 승격 변경은 feature flag 또는 env var로 on/off 가능하게 만든다.  
   성과 악화 감지 시 즉시 rollback 가능해야 한다.

6. **MFE/MAE 계산 인프라 확인**  
   Phase 4 시작 전에 `trade_outcomes` 또는 `position_state_events` 테이블에  
   MFE/MAE가 실제로 기록되고 있는지 확인한다.  
   없으면 phase 4 시작 전 보완 필요.

**작업 내용:**

| 우선순위 | Feature | 대상 전략 | 승격 방식 |
|---|---|---|---|
| P0 | `orderbook.imbalance_total` | S1/S4/S10/S12/S13 | score bonus/penalty |
| P0 | `relative_strength.rs_trend` | S10/S13/S15 | score bonus/penalty |
| P1 | `tick_pressure.buy_pressure_label` | S1/S2/S4/S6/S12 | score bonus |
| P1 | `adx.trend_strength` | S7/S8/S9/S15 | CANCEL(weak+bear) |
| P2 | `cvd.cvd_slope` | S4/S10/S13 | SIZE_DOWN(음수) |
| P2 | `anchored_vwap.above_vwap` | S9/S12/S14 | score bonus |

**EV 검증 방법:**

1. feature 값을 분위수(Q1/Q2/Q3)로 나눠 그룹별 평균 MFE, MAE, 승률을 계산
2. 통계적 유의성: 그룹 간 차이가 표준오차 1.5배 이상일 때만 승격 고려
3. 비교 기준선: 해당 전략의 전체 평균 수익률 vs feature 상위/하위 그룹 수익률

---

### Phase 5: 리스크 연결 — 🔴 미착수 (Phase 4 이후)

- stale 또는 결측 신호는 position sizing에서 자동 size down한다.
- `risk_per_trade = entry - stop` 기반 계좌 sizing으로 전환한다.
- daily loss kill switch와 섹터/테마 집중도 제한을 신규 진입 gate에 연결한다.

## 8. 전략별 적용 매트릭스

| 전략 | 1분 | 5분 | 30분 | 60분 | 일봉 | 주봉 | 핵심 보완 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1_GAP_OPEN | 필수 | 보조 | 불필요 | 불필요 | 보조 | 불필요 | 예상체결 freshness, 1분 VWAP, CVD |
| S2_VI_PULLBACK | 필수 | 필수 | 보조 | 불필요 | 보조 | 불필요 | VI anchored VWAP, 재유입 품질 |
| S3_INST_FRGN | 보조 | 보조 | 보조 | 보조 | 필수 | 보조 | 수급금액/거래대금 정규화 |
| S4_BIG_CANDLE | 필수 | 필수 | 보조 | 불필요 | 보조 | 불필요 | 현재봉/확정봉 분리, 고점 유지율 |
| S5_PROG_FRGN | 보조 | 필수 | 보조 | 보조 | 필수 | 보조 | 프로그램 순매수 정규화 |
| S6_THEME_LAGGARD | 필수 | 필수 | 보조 | 불필요 | 보조 | 불필요 | 테마 확산도, 수급 지속성 |
| S7_ICHIMOKU_BREAKOUT | 보조 | 필수 | 필수 | 필수 | 필수 | 보조 | 구름 돌파 유지, 상위 프레임 저항 |
| S8_GOLDEN_CROSS | 보조 | 보조 | 필수 | 필수 | 필수 | 보조 | ADX/DMI, MA slope |
| S9_PULLBACK_SWING | 보조 | 필수 | 필수 | 필수 | 필수 | 보조 | 눌림 품질, 추세 붕괴 회피 |
| S10_NEW_HIGH | 필수 | 필수 | 필수 | 필수 | 필수 | 필수 | 상대강도, 돌파폭 ATR 정규화 |
| S11_FRGN_CONT | 보조 | 보조 | 보조 | 보조 | 필수 | 보조 | 외인 순매수 지속성 정규화 |
| S12_CLOSING | 필수 | 필수 | 보조 | 불필요 | 보조 | 불필요 | VWAP 회복, 종가 위치 |
| S13_BOX_BREAKOUT | 필수 | 필수 | 필수 | 필수 | 필수 | 필수 | dry-up/expansion, retest hold |
| S14_OVERSOLD_BOUNCE | 필수 | 필수 | 필수 | 보조 | 필수 | 보조 | VWAP reclaim, divergence |
| S15_MOMENTUM_ALIGN | 보조 | 필수 | 필수 | 필수 | 필수 | 보조 | ADX, relative strength, 60분 정렬 |

## 9. 우선 실행 항목

1. `freshness_status`를 실시간 Redis뿐 아니라 분봉/일봉/주봉에도 확장한다.
2. `fetch_minute_candles` 캐시 TTL을 scope별로 분리한다.
3. 1분/5분/30분/60분 candle status를 신호 payload에 저장한다.
4. 주봉 builder를 추가한다. 우선 일봉 집계 방식으로 시작한다.
5. `feature_snapshot_json`, `missing_feature_flags`, `data_quality_score`를 저장한다.
6. CVD, anchored VWAP, orderbook imbalance는 shadow feature로 먼저 운영한다.
7. 2~4주 표본 수집 후 전략별 hard gate 승격 여부를 결정한다.

## 10. 최종 결론

새 보조지표를 추가하는 것보다 먼저 데이터 신선도와 결측 정책을 공통 레이어로 고정해야 한다. 현재 시스템은 5분봉과 일봉 중심으로 충분히 동작하지만, 1분/30분/60분/주봉이 전략별로 일관되게 확인되는 구조는 아직 약하다.

최종 방향은 다음이다.

- 단타/급등 전략: 1분 + 5분 + 실시간 orderflow 중심
- 스윙/추세 전략: 30분 + 60분 + 일봉 + 주봉 중심
- 평균회귀 전략: 1분 반전 + 5분 확인 + 30분/일봉 하락 추세 회피
- 모든 전략 공통: freshness, missing, fallback, feature snapshot, outcome label 저장

운영 적용은 hard gate가 아니라 shadow 저장부터 시작한다. 검증된 지표만 전략별 점수, 감점, `SHADOW`, `CANCEL`, `SIZE_DOWN` 정책으로 승격한다.
