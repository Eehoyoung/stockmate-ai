# 작업완료보고서 — candidates 풀 완전정상화

> 작업일: 2026-04-05  
> 작업자: Claude (Sonnet 4.6)  
> 대상: `ai-engine/candidates_builder.py` 및 전략 파일 S1~S15

---

## 작업 목표

`candidates:s{N}:001` / `candidates:s{N}:101` Redis 키를 S1~S15 전략 전체에 대해 빠짐없이 생성하고, 각 전략이 해당 풀을 우선적으로 소비하도록 보장한다. WebSocket은 Python(websocket-listener) 단독 운영.

---

## 작업 결과 요약

| 구분 | 내용 |
|------|------|
| 추가된 풀 빌더 | S2, S3, S5, S6 (신규 4종) |
| API 응답키 버그 수정 | 3건 (ka10029, ka10016, ka10035) |
| Redis 타입 버그 수정 | 1건 (ws:strength LIST → lindex) |
| 전략 파일 풀 우선 읽기 추가 | 6종 (S3, S5, S6, S7, S10, S11) |
| vi_watch_worker 보완 | S2 풀 연동 (_supplement_from_pool) |
| 디버그 로그 개선 | 2건 (_lpush_with_ttl 빈결과, S8/S9 경고) |
| 설정 변경 | LOG_LEVEL=DEBUG (docker-compose.yml ai-engine) |
| 문서 갱신 | candidate_pool_flow.md 전면 재작성 |

---

## 1. 신규 풀 빌더 추가 (candidates_builder.py)

### 1-1. S2: `_build_s2()` — ka10054 변동성완화장치발동종목

```
호출 API : POST /api/dostk/stkinfo (api-id: ka10054)
필터     : motn_drc=1 (상승), open_pric_pre_flu_rt > 0
최대     : 50개 / TTL: 300s
호출 시점: 장전(_build_pre_market) + 장중(_build_intraday)
생성 키  : candidates:s2:001, candidates:s2:101
```

### 1-2. S3: `_build_s3()` — ka10065 외인∩기관계 교집합

```
호출 API : POST /api/dostk/rkinfo (api-id: ka10065)
방식     : asyncio.gather() 로 외인(orgn_tp=9000) + 기관계(orgn_tp=9999) 병렬 조회 → 교집합
최대     : 100개 / TTL: 600s
호출 시점: 장중
생성 키  : candidates:s3:001, candidates:s3:101
```

### 1-3. S5: `_build_s5()` — ka90003 프로그램순매수상위

```
호출 API : POST /api/dostk/stkinfo (api-id: ka90003)
필터     : prm_netprps_amt > 0, mrkt_tp: 001→P00101, 101→P10102
최대     : 100개 / TTL: 600s
호출 시점: 장중
생성 키  : candidates:s5:001, candidates:s5:101
```

### 1-4. S6: `_build_s6()` — ka90001→ka90002 테마 2단계

```
호출 API : ka90001(테마그룹 상위 5개) → ka90002(테마구성종목)
필터     : flu_rt < 5.0 (선도주 제외)
최대     : 150개 / TTL: 300s
호출 시점: 장중 루프 외부 1회 (테마는 시장 구분 없음)
생성 키  : candidates:s6:001, candidates:s6:101 (동일 내용)
```

---

## 2. API 응답 키 버그 수정

| 파일 | 수정 전 (잘못된 키) | 수정 후 (정확한 키) | 영향 전략 |
|------|-----------------|-----------------|---------|
| `candidates_builder.py` `_fetch_ka10029()` | `"expd_cntr_flu_upper"` | `"exp_cntr_flu_rt_upper"` | S1, S7 풀 항상 공백 → 수정 |
| `candidates_builder.py` `_build_s10()` | `"new_high_low_prps"` | `"ntl_pric"` | S10 풀 항상 공백 → 수정 |
| `candidates_builder.py` `_build_s11()` | `"frgnr_cont_netsl_upper"` | `"for_cont_nettrde_upper"` | S11 풀 항상 공백 → 수정 |

---

## 3. Redis 타입 불일치 수정

**`ws:strength:{stk_cd}` 키 타입 문제**

```
문제: websocket-listener/redis_writer.py 가 LPUSH 로 저장 → LIST 타입
     candidates_builder._build_s4() 가 rdb.get() 으로 접근 → WRONGTYPE 오류
수정: rdb.get(f"ws:strength:{stk_cd}") → rdb.lindex(f"ws:strength:{stk_cd}", 0)
```

---

## 4. 전략 파일 풀 우선 읽기 추가

| 파일 | 변경 내용 |
|------|---------|
| `strategy_3_inst_foreign.py` | `candidates:s3:{market}` 풀 → pool_set, ka10063 결과와 교집합, fallback |
| `strategy_5_program_buy.py` | `candidates:s5:{market}` 풀 → pool_set, overlap_raw와 교집합, fallback |
| `strategy_6_theme.py` | `candidates:s6:001` 풀 → pool_set, 테마 구성종목 필터로 활용 |
| `strategy_7_auction.py` | `candidates:s7:{market}` 풀 → gap_candidates, fallback: ka10029 직접 |
| `strategy_10_new_high.py` | `candidates:s10:001+101` 풀 → pool_codes, ws:tick 보완, fallback: ka10016+ka10023 |
| `strategy_11_frgn_cont.py` | `candidates:s11:{market}` 풀 → pool_set, ka10035 결과와 교집합, fallback |

---

## 5. vi_watch_worker.py — S2 풀 연동

**문제**: `candidates:s2:*` 풀이 적재되어도 vi_watch_worker가 이를 읽지 않아 사실상 미사용.

**해결**: `_supplement_from_pool(rdb)` 함수 추가

흐름:
```
[vi_watch_queue 공백]
  └─ (30초 주기, _SUPPLEMENT_INTERVAL=30.0) _supplement_from_pool()
       ├─ candidates:s2:001/101 LRANGE
       ├─ scanner:dedup:S2_VI_PULLBACK:{stk_cd} 체크 (이미 처리된 종목 skip)
       ├─ vi:{stk_cd} 해시 확인 (WS 이벤트로 설정된 VI 데이터 필요)
       └─ vi_watch_queue LPUSH → check_vi_pullback() 으로 처리
```

---

## 6. 디버그 로그 개선

### `_lpush_with_ttl()` 빈 결과 로그 추가
```python
if not codes:
    logger.debug("[builder] %s 빈 결과 – 기존 키 유지 (TTL 만료 대기)", key)
    return
```

### S8/S9 풀 미존재 경고 추가
```python
logger.warning("[S8] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요")
```

---

## 7. LOG_LEVEL=DEBUG 활성화

`docker-compose.yml` ai-engine 서비스 environment에 `LOG_LEVEL: DEBUG` 추가.  
LOG_LEVEL=DEBUG 로 실행 시 각 전략별 빌드 결과(종목 수, 빈 결과 여부)를 로그로 추적 가능.

---

## 8. 최종 candidates 풀 현황 (30개 키 전량 완비)

| 전략 | :s{N}:001 | :s{N}:101 | 빌드 API | 전략 소비 |
|------|:---:|:---:|---------|:---:|
| S1 | ✅ | ✅ | ka10029 (갭 3~15%) | ✅ 필수 |
| S2 | ✅ | ✅ | ka10054 (VI 발동) | ✅ 보완 경로 |
| S3 | ✅ | ✅ | ka10065 외인∩기관계 | ✅ 풀 우선 |
| S4 | ✅ | ✅ | ka10027 (2~20%) | ✅ 필수 |
| S5 | ✅ | ✅ | ka90003 프로그램순매수 | ✅ 풀 우선 |
| S6 | ✅ | ✅ | ka90001→ka90002 테마 | ✅ 풀 필터 |
| S7 | ✅ | ✅ | ka10029 (갭 2~10%) | ✅ 풀 우선 |
| S8 | ✅ | ✅ | ka10027 (0.5~8%) | ✅ 필수 |
| S9 | ✅ | ✅ | ka10027 (0.3~5%) | ✅ 필수 |
| S10 | ✅ | ✅ | ka10016 (52주 신고가) | ✅ 풀 우선 |
| S11 | ✅ | ✅ | ka10035 (외인 3일 연속) | ✅ 풀 우선 |
| S12 | ✅ | ✅ | ka10032 (거래대금상위) | ⚠️ 전략 미사용 (by design) |
| S13 | ✅ | ✅ | S8풀 ∪ S10풀 합산 | ✅ 필수 |
| S14 | ✅ | ✅ | ka10027 (하락 3~10%) | ✅ 필수 |
| S15 | ✅ | ✅ | S8풀 재활용 | ✅ 필수 |

**총 30개 키 전량 Python candidates_builder.py 단독 생성·관리 완료.**

---

## 잔여 미완료 항목

| 우선 | 항목 |
|------|------|
| P1 | `strategy_12_closing.py` candidates:s12:* 풀 우선 읽기 전환 |
| P2 | `scorer.py` S14/S15 케이스·RSI/ATR·시간대 가중치 추가 |
| P2 | TP/SL 6파일 구현 |
| P3 | `OvernightRiskScheduler.java` 통합 |
| P3 | `/candidate` 명령 풀 현황 표시 |
