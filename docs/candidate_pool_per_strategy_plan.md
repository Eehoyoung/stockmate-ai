# 전략별 개별 Candidates 풀 Redis 구성 계획

**작성일**: 2026-03-30
**목표 버전**: 2.4.0
**근거 문서**: `docs/candidate_pool_plan.md` (v2.3.0 이후 개선)

---

## 1. 변경 배경

### 1.1 현재 구조 (As-Is)

현재 여러 전략이 동일한 Redis 키를 공유하는 구조로, 전략별 특성이 후보 풀에 반영되지 않음.

| 현재 Redis 키 | 공유 전략 | 문제 |
|------------|---------|-----|
| `candidates:{001/101}` | S1, S7 | 갭률 기준이 S1(3~15%)과 S7(2~10%)으로 상이함 |
| `candidates:swing:{001/101}` | S8, S9, S13, S15 | 전략마다 필터 조건(MA 상태, 변동성)이 다름 |
| `candidates:oversold:{001/101}` | S14 | 단독 사용이나 S14 전용 명칭 아님 |
| `candidates:newhigh:{001/101}` | S10, S13 일부 | 공유 풀 |

### 1.2 목표 구조 (To-Be)

각 전략별 전용 Redis 키를 사용하여 전략 고유의 필터 조건을 풀 수집 단계에서부터 적용.

```
candidates:s{N}:{market}
  예) candidates:s1:001, candidates:s1:101
      candidates:s8:001, candidates:s8:101
```

---

## 2. 전략별 후보 풀 정의

### 2.1 전략별 Redis 키 및 소스 API 매핑

| 전략 | Redis 키 | 소스 API | API 명칭 | TTL | 비고 |
|------|---------|---------|---------|-----|-----|
| **S1** 갭상승 시초가 | `candidates:s1:{001/101}` | **ka10029** | 예상체결등락률상위 | 3분 | 갭률 3~15%, 장전 |
| **S2** VI 눌림목 | `candidates:s2:{001/101}` | *(이벤트 기반)* | vi_watch_queue (WebSocket 1h) | 1시간 | VI 발동 종목 목록 |
| **S3** 외인+기관 | `candidates:s3:{001/101}` | **ka10065** | 장중투자자별매매상위 | 15분 | 외인+기관 동시 순매수 상위 |
| **S4** 장대양봉 | `candidates:s4:{001/101}` | **ka10023** | 거래량급증요청 | 5분 | 거래량급증률 200%+ |
| **S5** 프로그램순매수 | `candidates:s5:{001/101}` | **ka90003** | 프로그램순매수상위50 | 5분 | 프로그램 순매수 상위 |
| **S6** 테마후발주 | `candidates:s6:{001/101}` | **ka90001** | 테마그룹별요청 | 10분 | 테마 상위 그룹 구성종목 |
| **S7** 동시호가 | `candidates:s7:{001/101}` | **ka10029** | 예상체결등락률상위 | 3분 | 갭률 2~10%, 장전 |
| **S8** 골든크로스 | `candidates:s8:{001/101}` | **ka10027** | 전일대비등락률상위 | 5분 | sort_tp=1, 상승률 0.5~8%, 거래대금 10억↑ |
| **S9** 눌림목 | `candidates:s9:{001/101}` | **ka10027** | 전일대비등락률상위 | 5분 | sort_tp=1, 상승률 0.3~5%, 거래대금 10억↑ |
| **S10** 신고가돌파 | `candidates:s10:{001/101}` | **ka10016** | 신고저가요청 | 5분 | ntl_tp=1, 52주 신고가 |
| **S11** 외인연속 | `candidates:s11:{001/101}` | **ka10035** | 외인연속순매매상위 | 30분 | trdeTp=2 연속순매수 |
| **S12** 종가강도 | `candidates:s12:{001/101}` | **ka10032** | 거래대금상위 | 10분 | 장중 거래대금 상위 50 |
| **S13** 박스권돌파 | `candidates:s13:{001/101}` | **ka10027 + ka10016** | 등락률상위 + 신고가 | 5분 | swing ∪ newhigh 합산 |
| **S14** 과매도반등 | `candidates:s14:{001/101}` | **ka10027** | 전일대비등락률상위 | 5분 | sort_tp=3, 하락률 3~10%, 거래대금 10억↑ |
| **S15** 모멘텀동조 | `candidates:s15:{001/101}` | **ka10027 + ka10031** | 등락률상위 ∩ 전일거래량상위 | 5분 | swing ∩ volsurge 교집합 |

---

## 3. 전략별 상세 풀 구성

### S1 – 갭상승 시초가 (ka10029)

- **Redis 키**: `candidates:s1:001`, `candidates:s1:101`
- **소스 API**: ka10029 예상체결등락률상위
- **수집 시각**: 8:30 ~ 9:05 (장전 예상체결 구간)
- **필터 조건**:
  - 예상체결등락률 3% ~ 15%
  - 거래대금 조건: 전체 (stexTp=1)
- **TTL**: 3분 (갭 정보는 장 시작 후 빠르게 변화)
- **ka10029 주요 파라미터**: `mrktTp`, `stexTp`, `fluCtpTp(2: 상승)`, `srtTp(1: 등락률)`

---

### S2 – VI 눌림목 (이벤트 기반)

- **Redis 키**: `candidates:s2:001`, `candidates:s2:101`
- **소스**: WebSocket 1h 이벤트 → `vi_watch_queue`
- **수집 방식**: VI 발동 시점(websocket-listener)에 실시간 push
- **필터 조건**:
  - VI 상태: 발동(vi_stat=1)
  - VI 유형: 정적VI(vi_tp=2), 동적VI(vi_tp=1) 모두
- **TTL**: 1시간 (VI 해제 후에도 일정 시간 유효)
- **비고**: api-orchestrator의 `ViWatchService`가 vi_watch_queue를 소비하여 Redis Set에 적재

---

### S3 – 외인+기관 동시 순매수 (ka10065)

- **Redis 키**: `candidates:s3:001`, `candidates:s3:101`
- **소스 API**: ka10065 장중투자자별매매상위
- **수집 시각**: 9:30 ~ 14:30 (매 15분 갱신)
- **필터 조건**:
  - 외인 순매수량 > 0 AND 기관 순매수량 > 0 (동시 순매수)
  - 순매수금액 상위 30개 이내
- **TTL**: 15분
- **ka10065 주요 파라미터**: `mrktTp`, `invstTp(1:외국인 또는 2:기관)`, `stexTp`
- **보조 API**: ka10131 기관외국인연속매매현황 (3일 연속 여부 확인용)

---

### S4 – 장대양봉 거래량급증 (ka10023)

- **Redis 키**: `candidates:s4:001`, `candidates:s4:101`
- **소스 API**: ka10023 거래량급증요청
- **수집 시각**: 10:00 ~ 14:30 (매 5분 갱신)
- **필터 조건**:
  - 거래량급증률 200% 이상 (전일 대비)
  - 현재가 1,000원 이상
  - 거래대금 10억원 이상 (`trdePricaCnd=2`)
- **TTL**: 5분
- **ka10023 주요 파라미터**: `mrktTp`, `volInqTp(1:거래량증가율)`, `trdePricaCnd`, `stexTp`

---

### S5 – 프로그램 순매수 (ka90003)

- **Redis 키**: `candidates:s5:001`, `candidates:s5:101`
- **소스 API**: ka90003 프로그램순매수상위50요청
- **수집 시각**: 10:00 ~ 14:00 (매 5분 갱신)
- **필터 조건**:
  - 프로그램 순매수 상위 50
  - 현재가 5-일 이동평균 이상 (수집 후 개별 필터)
- **TTL**: 5분
- **ka90003 주요 파라미터**: `mrktTp`, `stexTp`
- **보조 API**: ka90009 외국인기관매매상위 (외인 동반 여부 확인)

---

### S6 – 테마 후발주 (ka90001 + ka90002)

- **Redis 키**: `candidates:s6:001`, `candidates:s6:101`
- **소스 API**: ka90001 테마그룹별요청 → ka90002 테마구성종목요청
- **수집 방식**: 2단계 수집 (테마 상위 → 구성종목)
  1. ka90001 로 등락률 상위 테마 그룹 TOP 5 조회
  2. 각 테마 코드로 ka90002 구성종목 조회
  3. 구성종목 중 등락률 < 테마 평균 × 0.5 (후발주 조건) 필터
- **수집 시각**: 9:30 ~ 13:00 (매 10분 갱신)
- **TTL**: 10분
- **ka90001 파라미터**: 없음 (전체 조회)
- **ka90002 파라미터**: `themaGrpCd` (테마 코드)

---

### S7 – 동시호가 (ka10029)

- **Redis 키**: `candidates:s7:001`, `candidates:s7:101`
- **소스 API**: ka10029 예상체결등락률상위
- **수집 시각**: 8:30 ~ 9:00 (동시호가 구간)
- **필터 조건**:
  - 예상체결등락률 2% ~ 10% (S1보다 완화된 갭 기준)
  - 예상체결 호가잔량 매수/매도 비율 ≥ 1.5
- **TTL**: 3분
- **비고**: S1과 동일 API지만 갭률 조건 상이, 호가잔량 추가 필터

---

### S8 – 골든크로스 스윙 (ka10027)

- **Redis 키**: `candidates:s8:001`, `candidates:s8:101`
- **소스 API**: ka10027 전일대비등락률상위
- **수집 시각**: 9:30 ~ 14:30 (매 5분 갱신)
- **필터 조건**:
  - sort_tp=1 (상승률 기준)
  - 등락률 0.5% ~ 8%
  - 거래대금 10억원 이상 (`trdePricaCnd=2`)
  - 현재가 1,000원 이상
- **TTL**: 5분
- **ka10027 파라미터**: `mrktTp`, `sortTp(1)`, `trdePricaCnd(2)`, `stexTp`
- **비고**: 수집 후 개별 종목에서 ka10081 일봉 조회 → MA5/MA20 골든크로스 필터

---

### S9 – 정배열 눌림목 스윙 (ka10027)

- **Redis 키**: `candidates:s9:001`, `candidates:s9:101`
- **소스 API**: ka10027 전일대비등락률상위
- **수집 시각**: 9:30 ~ 13:00 (매 5분 갱신)
- **필터 조건**:
  - sort_tp=1 (상승률 기준)
  - 등락률 0.3% ~ 5% (S8보다 낮은 상승률 → 눌림목 조건)
  - 거래대금 10억원 이상
- **TTL**: 5분
- **비고**: S8과 소스 API 동일, 등락률 범위 상이. 공유 API 호출로 최적화 가능

---

### S10 – 52주 신고가 돌파 (ka10016)

- **Redis 키**: `candidates:s10:001`, `candidates:s10:101`
- **소스 API**: ka10016 신고저가요청
- **수집 시각**: 9:30 ~ 14:30 (매 5분 갱신)
- **필터 조건**:
  - ntl_tp=1 (신고가)
  - 기준 기간 250일 (52주)
  - 거래량 10,000주 이상 (`trdeQtyTp=00010`)
- **TTL**: 5분
- **ka10016 파라미터**: `mrktTp`, `ntlTp(1)`, `trdeQtyTp(00010)`, `stexTp`

---

### S11 – 외국인 연속 순매수 (ka10035)

- **Redis 키**: `candidates:s11:001`, `candidates:s11:101`
- **소스 API**: ka10035 외인연속순매매상위
- **수집 시각**: 9:30 ~ 14:30 (매 30분 갱신 – 외인 포지션은 일 단위 변동)
- **필터 조건**:
  - trdeTp=2 (연속 순매수)
  - 연속 순매수 3일 이상 (dm1, dm2, dm3 모두 양수)
  - 총 순매수 합계 양수
- **TTL**: 30분
- **ka10035 파라미터**: `mrktTp`, `trdeTp(2)`, `baseDtTp(1)`, `stexTp`

---

### S12 – 종가 강도 확인 (ka10032)

- **Redis 키**: `candidates:s12:001`, `candidates:s12:101`
- **소스 API**: ka10032 거래대금상위
- **수집 시각**: 14:30 ~ 14:50 (종가 집중 구간, 매 10분 갱신)
- **필터 조건**:
  - 거래대금 순 정렬 상위 50
  - 등락률 > 0 (양전 종목만)
- **TTL**: 10분
- **ka10032 파라미터**: `mrktTp`, `sortTp(1)`, `stexTp`
- **비고**: 기존 `candidates:{market}` (갭 풀) 사용에서 거래대금 상위로 교체

---

### S13 – 박스권 돌파 (ka10027 ∪ ka10016)

- **Redis 키**: `candidates:s13:001`, `candidates:s13:101`
- **소스 API**: ka10027 (swing 풀) + ka10016 (newhigh 풀) **합산**
- **수집 방식**:
  ```
  s13 = unique(s8_candidates ∪ s10_candidates)
  ```
  - `candidates:s8:{market}`에서 상위 100개
  - `candidates:s10:{market}`에서 상위 50개
  - 중복 제거 후 합산
- **수집 시각**: 9:30 ~ 14:00 (s8/s10 풀 갱신 시 자동 갱신)
- **TTL**: 5분
- **비고**: 별도 API 호출 없이 s8/s10 풀을 합산하여 구성
  → `CandidateService.getS13Candidates()` = `getS8() ∪ getS10()`

---

### S14 – 과매도 반등 (ka10027 하락률)

- **Redis 키**: `candidates:s14:001`, `candidates:s14:101`
- **소스 API**: ka10027 전일대비등락률상위 (하락률 기준)
- **수집 시각**: 9:30 ~ 14:00 (매 5분 갱신)
- **필터 조건**:
  - sort_tp=3 (하락률 기준)
  - 등락률 -3% ~ -10%
  - 거래대금 10억원 이상 (`trdePricaCnd=2`)
  - 현재가 1,000원 이상
- **TTL**: 5분
- **ka10027 파라미터**: `mrktTp`, `sortTp(3)`, `trdePricaCnd(2)`, `stexTp`

---

### S15 – 모멘텀 동조 (ka10027 ∩ ka10031)

- **Redis 키**: `candidates:s15:001`, `candidates:s15:101`
- **소스 API**: ka10027 (swing) ∩ ka10031 (전일거래량상위) **교집합**
- **수집 방식**:
  ```
  s15 = s8_candidates ∩ volsurge_candidates
  fallback: s8_candidates (교집합 없을 때)
  ```
  - `candidates:s8:{market}` 에서 swing 풀
  - ka10031 전일거래량상위 (전일대비 120%+) 임시 조회
  - 교집합 우선, 미달 시 swing 단독 사용
- **수집 시각**: 10:00 ~ 14:30 (매 5분 갱신)
- **TTL**: 5분
- **ka10031 파라미터**: `mrktTp`, `sortTp(1)`, `stexTp`

---

## 4. API 사용 요약

| API ID | API 명칭 | 사용 전략 | 문서 참조 |
|--------|---------|---------|---------|
| ka10016 | 신고저가요청 | S10, S13(간접) | `docs/rank_info/ka10016.md` |
| ka10023 | 거래량급증요청 | S4 | `docs/api/ka10023_vol_surge.md` |
| ka10027 | 전일대비등락률상위 | S8, S9, S13(간접), S14, S15(간접) | `docs/rank_info/ka10027.md` |
| ka10029 | 예상체결등락률상위 | S1, S7 | `docs/rank_info/ka10029_expected_upper.md` |
| ka10031 | 전일거래량상위 | S15(교집합) | `docs/api/ka10031.md` |
| ka10032 | 거래대금상위 | S12 | `docs/api/ka10032.md` |
| ka10035 | 외인연속순매매상위 | S11 | `docs/rank_info/ka10035.md` |
| ka10065 | 장중투자자별매매상위 | S3 | *(문서 미작성)* |
| ka90001 | 테마그룹별요청 | S6 | *(문서 미작성)* |
| ka90002 | 테마구성종목요청 | S6 | *(문서 미작성)* |
| ka90003 | 프로그램순매수상위50 | S5 | *(문서 미작성)* |
| **WebSocket 1h** | VI발동/해제 | S2 | *(websocket-listener)* |

---

## 5. Redis 키 전체 구조 (최종)

```
candidates:s1:{001|101}       TTL 3분   ka10029  갭상승 시초가
candidates:s2:{001|101}       TTL 1시간 WS-1h    VI 눌림목 (이벤트)
candidates:s3:{001|101}       TTL 15분  ka10065  외인+기관 동시순매수
candidates:s4:{001|101}       TTL 5분   ka10023  장대양봉 거래량급증
candidates:s5:{001|101}       TTL 5분   ka90003  프로그램 순매수
candidates:s6:{001|101}       TTL 10분  ka90001+ka90002  테마 후발주
candidates:s7:{001|101}       TTL 3분   ka10029  동시호가
candidates:s8:{001|101}       TTL 5분   ka10027(상승)  골든크로스
candidates:s9:{001|101}       TTL 5분   ka10027(상승)  눌림목
candidates:s10:{001|101}      TTL 5분   ka10016  신고가 돌파
candidates:s11:{001|101}      TTL 30분  ka10035  외인 연속순매수
candidates:s12:{001|101}      TTL 10분  ka10032  종가 강도
candidates:s13:{001|101}      TTL 5분   s8∪s10   박스권 돌파
candidates:s14:{001|101}      TTL 5분   ka10027(하락)  과매도 반등
candidates:s15:{001|101}      TTL 5분   s8∩ka10031  모멘텀 동조

candidates:meta:s{N}:{001|101}  TTL 1시간  풀 메타 정보 (size, updated_ms, source)
```

---

## 6. 구현 파일별 변경 범위

### 6.1 Java (api-orchestrator)

#### `CandidateService.java` – 전면 재구성

현재의 `getSwingCandidates()`, `getOversoldCandidates()` 등 타입별 메서드를
전략별 메서드로 교체.

```java
// 신규 메서드 목록
getS1Candidates(String market)   // ka10029 갭 3~15%
getS2Candidates(String market)   // VI Set 조회 (vi_watch_set:{market})
getS3Candidates(String market)   // ka10065 외인+기관
getS4Candidates(String market)   // ka10023 거래량급증
getS5Candidates(String market)   // ka90003 프로그램순매수
getS6Candidates(String market)   // ka90001+ka90002 테마후발주
getS7Candidates(String market)   // ka10029 갭 2~10%
getS8Candidates(String market)   // ka10027 상승 0.5~8%
getS9Candidates(String market)   // ka10027 상승 0.3~5%
getS10Candidates(String market)  // ka10016 52주 신고가
getS11Candidates(String market)  // ka10035 외인연속
getS12Candidates(String market)  // ka10032 거래대금상위
getS13Candidates(String market)  // s8 ∪ s10
getS14Candidates(String market)  // ka10027 하락 3~10%
getS15Candidates(String market)  // s8 ∩ ka10031
```

**기존 메서드 deprecated 처리** (하위 호환 후 제거):
- `getAllCandidates()` → `getS1Candidates()` + `getS7Candidates()`
- `getSwingCandidates()` → `getS8Candidates()` / `getS9Candidates()`
- `getOversoldCandidates()` → `getS14Candidates()`
- `getNewHighCandidates()` → `getS10Candidates()`

#### `TradingScheduler.java` – 각 scan 메서드에서 전략 전용 메서드 호출

```java
// 예시
scanGapOpening() → candidateService.getS1Candidates(market)
scanAuction()    → candidateService.getS7Candidates(market)
scanGoldenCross() → candidateService.getS8Candidates(market)
scanPullback()   → candidateService.getS9Candidates(market)
// ...
```

#### `StrategyService.java` – 전략별 메서드에서 전용 풀 사용

---

### 6.2 Python (ai-engine)

#### `strategy_runner.py` – 전략별 키 읽기 수정

```python
STRATEGY_CANDIDATE_KEYS = {
    "s1":  "candidates:s1",
    "s2":  "candidates:s2",
    "s3":  "candidates:s3",
    "s4":  "candidates:s4",
    "s5":  "candidates:s5",
    "s6":  "candidates:s6",
    "s7":  "candidates:s7",
    "s8":  "candidates:s8",
    "s9":  "candidates:s9",
    "s10": "candidates:s10",
    "s11": "candidates:s11",
    "s12": "candidates:s12",
    "s13": "candidates:s13",
    "s14": "candidates:s14",
    "s15": "candidates:s15",
}

async def load_candidates(rdb, strategy_id: str, market: str) -> list[str]:
    base_key = STRATEGY_CANDIDATE_KEYS[strategy_id]
    codes = await rdb.lrange(f"{base_key}:{market}", 0, 99)
    if not codes:
        # 폴백: candidates:{market}
        codes = await rdb.lrange(f"candidates:{market}", 0, 99)
    return codes
```

#### 각 strategy_N.py – 하드코딩된 Redis 키 제거

현재 각 전략 파일이 `candidates:swing:001` 등을 직접 읽는 코드를
`strategy_runner.py`의 `load_candidates()` 호출로 위임.

예시 (`strategy_8_golden_cross.py`):
```python
# 수정 전
kospi  = await rdb.lrange("candidates:swing:001", 0, 99)
kosdaq = await rdb.lrange("candidates:swing:101", 0, 99)

# 수정 후 (strategy_runner가 주입)
# 전략 함수 시그니처: async def run(rdb, candidates: list[str], market: str, ...)
```

---

## 7. 수집 스케줄 (Cron 계획)

| Cron | 시각 | 갱신 풀 | 비고 |
|------|-----|--------|-----|
| `0 30-58/5 8 * * MON-FRI` | 08:30 ~ 08:55 (5분) | s1, s7 | 장전 갭 풀 |
| `0 55 8 * * MON-FRI` | 08:55 | s1, s7, s8, s9, s10, s11, s14 | Warmup |
| `0 30/15 9-14 * * MON-FRI` | 09:30 ~ 14:30 (15분) | s3 | 외인+기관 |
| `0 0/5 10-14 * * MON-FRI` | 10:00 ~ 14:30 (5분) | s4, s5 | 급등/프로그램 |
| `0 30/10 9-13 * * MON-FRI` | 09:30 ~ 13:00 (10분) | s6 | 테마 |
| `0 28/5 9-14 * * MON-FRI` | 09:28 ~ 14:30 (5분) | s8, s9, s10, s13, s14, s15 | 스윙 |
| `0 30/30 9-14 * * MON-FRI` | 09:30 ~ 14:30 (30분) | s11 | 외인연속 |
| `0 30/10 14-14 * * MON-FRI` | 14:30 ~ 14:50 (10분) | s12 | 종가강도 |

---

## 8. 구현 우선순위

### P0 – 기반 구조 (즉시)

| # | 파일 | 작업 |
|---|------|-----|
| 1 | `CandidateService.java` | `getS1()` ~ `getS15()` 메서드 추가, 기존 메서드 deprecated |
| 2 | `strategy_runner.py` | `STRATEGY_CANDIDATE_KEYS` 매핑 추가, `load_candidates()` 함수 |
| 3 | `TradingScheduler.java` | 각 scan 메서드를 전략별 메서드로 교체 |

### P1 – 개별 전략 연결

| # | 파일 | 작업 |
|---|------|-----|
| 4 | `strategy_8_golden_cross.py` | 하드코딩 키 → load_candidates 위임 |
| 5 | `strategy_9_pullback.py` | 동일 |
| 6 | `strategy_13_box_breakout.py` | swing ∪ newhigh → s13 단일 키 |
| 7 | `strategy_14_oversold_bounce.py` | oversold → s14 |
| 8 | `strategy_15_momentum_align.py` | s8 ∩ volsurge → s15 |

### P2 – 신규 풀 구현

| # | 파일 | 작업 |
|---|------|-----|
| 9 | `CandidateService.java` | S3 (ka10065), S4 (ka10023), S5 (ka90003), S6 (ka90001+90002) |
| 10 | `TradingScheduler.java` | S3/S4/S5/S6 수집 Cron 추가 |
| 11 | Strategy files S3~S6 | 전용 풀 사용으로 전환 |

---

## 9. 기대 효과

| 항목 | 현재 | 개선 후 |
|------|------|--------|
| 전략 간 후보 오염 | S8/S9/S13/S15가 동일 swing 풀 공유 | 전략별 독립 풀, 개별 필터 적용 |
| S1 vs S7 구분 | 동일 갭 풀 사용 (조건 중복) | S1: 갭 3~15% / S7: 갭 2~10% 분리 |
| S3/S4/S5/S6 후보 풀 | 없음 (각 전략이 매번 직접 API 호출) | 전용 풀 → API 호출 최소화 |
| S12 후보 적합도 | 장전 갭 기준 종목 | 장중 거래대금 상위 |
| 디버깅/모니터링 | 공유 키 → 어느 전략이 소비했는지 불명확 | `candidates:meta:s{N}:{market}` 개별 추적 |
| 키 네이밍 일관성 | 혼재 (candidates, swing, oversold 등) | 전략 번호 기반 일관된 규칙 |
