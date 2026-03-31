# PostgreSQL 저장 현황 분석 및 수정 계획 (2026-03-31)

## 1. 현재 테이블 현황

| 테이블 | 엔티티 | 상태 |
|--------|--------|------|
| `trading_signals` | `TradingSignal.java` | ✅ 정상 저장 중 (단, 필드 누락 있음 → P1-A) |
| `kiwoom_tokens` | `KiwoomToken.java` | ✅ 정상 저장 중 |
| `vi_events` | `ViEvent.java` | ✅ 정상 저장 중 |
| `ws_tick_data` | `WsTickData.java` | ⚠️ Java WS 비활성화로 실제 데이터 없음 |
| `economic_events` | `EconomicEvent.java` | ℹ️ 수동 입력 또는 미래 기능 (미사용 가능) |
| `news_analysis` | `NewsAnalysis.java` | ℹ️ Python news_scheduler 연동 시 사용 (현재 미연동) |

---

## 2. 발견된 문제점

### [Critical] P1-A: `trading_signals` 에 tp1_price / tp2_price / sl_price 컬럼 없음

**문제**: `StrategyService.java` 에서 전략별 기술적 분석 기반 절대가(tp1Price, tp2Price, slPrice)를 계산하여 `TradingSignalDto`에 설정하고 있다.  
이 값들은 `toQueuePayload()`를 통해 telegram_queue에는 전송되지만 **PostgreSQL에는 저장되지 않는다**.

`SignalService.buildSignalEntity()` (line 164~187)에서 매핑 누락:
```java
// 현재 buildSignalEntity() — tp1/tp2/slPrice 매핑 없음
.targetPrice(t1 > 0 ? t1 : null)   // ← calcTarget1Price() (% 기반)만 저장
.stopPrice(sp > 0 ? sp : null)      // ← calcStopPrice() (% 기반)만 저장
// tp1Price (기술적 절대가) → 저장 안 됨
// tp2Price (기술적 절대가) → 저장 안 됨
// slPrice  (기술적 절대가) → 저장 안 됨
```

`TradingSignal.java` 엔티티에도 해당 컬럼 정의 없음.  
→ OvernightRiskScheduler가 `signal.getStopPrice()`를 쓰는데 이건 % 기반값(정상), 기술적 slPrice가 더 정확하지만 저장 경로 없음.

**수정 방향**:
1. `TradingSignal.java`에 `tp1Price`, `tp2Price`, `slPrice` 필드 추가
2. `SignalService.buildSignalEntity()`에서 dto의 tp1Price/tp2Price/slPrice 매핑 추가

---

### [Critical] P1-B: `FrgnContNettrdRequest.baseDtTp` 값 불일치

**문제**: `StrategyRequests.java` line 256:
```java
@JsonProperty("base_dt_tp") private String baseDtTp = "0";   // 0:당일기준
```

반면 전략 스펙(`strategy_11_frgn_cont.py` 주석 및 ka10035 API 문서)에서는 `base_dt_tp=1(전일기준)`을 사용해야 한다:
```python
"base_dt_tp": "1",    # 1: 전일기준
```

`"0"`(당일기준)으로 호출 시 D-1/D-2/D-3의 기준이 달라져 **외국인 연속 매수 판별이 부정확**해진다.

**수정 방향**: `FrgnContNettrdRequest.baseDtTp` 기본값을 `"1"`로 변경

---

### [Critical] P1-C: `hibernate.ddl-auto: create` 데이터 유실 위험

**문제**: `application.yml`:
```yaml
hibernate:
  ddl-auto: create    # ← 재기동 시 전체 테이블 DROP + 재생성
```

서버 재기동마다 `trading_signals`, `vi_events`, `kiwoom_tokens` 등 **모든 데이터 초기화**.  
이미 `OvernightRiskScheduler`는 "최근 2일" 신호를 DB에서 조회하는데 재기동 시 데이터 소실.

**수정 방향**: `ddl-auto: update` 로 변경 (컬럼 추가 자동 반영, 기존 데이터 보존)

---

### [Important] P2-A: 전략 메타데이터 `extra_info` 미활용

**문제**: `TradingSignal.java`에 `extra_info TEXT` 컬럼이 있지만 `buildSignalEntity()`에서 항상 null.  
DTO에는 있지만 DB에 저장 안 되는 필드들:
- `rsi` (S8/S9/S13/S14/S15)
- `atrPct` (S14/S15)
- `condCount` (S14/S15)
- `holdingDays` (S8/S9/S13/S14/S15)
- `isNewHigh` (S10)
- `continuousDays` (S11)
- `netBuyAmt` (S3/S5)
- `bodyRatio` (S4)
- `volSurgeRt` (S10)
- `themeRank`, `volRank` (S6/S12)

이 데이터들은 telegram_queue로는 전송되지만 DB에서 성과 분석 시 조회 불가.

**수정 방향**: `buildSignalEntity()`에서 전략별 핵심 메타를 JSON으로 직렬화하여 `extra_info`에 저장

---

### [Important] P2-B: 일별 성과 데이터 영속화 없음

**문제**: `/성과` 텔레그램 명령은 `TradingSignalRepository.getStrategyPerformanceStats()`를 호출하여  
당일 신호의 WIN/LOSS/SENT 상태를 집계한다.  
그러나 `closeSignal()` 메서드가 entity에는 있지만 **호출하는 코드가 없음** → `realized_pnl`, `closed_at`, `executed_at`이 항상 null.  
P1-C 문제 해결 전까지는 ddl=create로 재기동 시 데이터 자체가 소실.

또한 Redis `daily_summary:{today}` 해시는 재기동/Redis 재시작 시 소실.  
전략별 누적 승률, 평균 수익률 등 **다일을 넘기는 성과 추적 불가**.

**수정 방향 (신규 테이블)**:
```sql
CREATE TABLE signal_performance_daily (
    id              BIGSERIAL PRIMARY KEY,
    trade_date      DATE        NOT NULL,
    strategy        VARCHAR(30) NOT NULL,
    signal_count    INT         DEFAULT 0,
    win_count       INT         DEFAULT 0,
    loss_count      INT         DEFAULT 0,
    avg_pnl_pct     DOUBLE PRECISION,
    total_pnl_pct   DOUBLE PRECISION,
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    UNIQUE (trade_date, strategy)
);
```

→ `DataCleanupScheduler` 또는 장 마감 후 배치(15:40)에서 당일 집계 후 upsert

---

### [Minor] P3-A: `ws_tick_data` 테이블 미사용

**문제**: Java WebSocket이 비활성화(`JAVA_WS_ENABLED=false`)된 상태에서 Python websocket-listener가 단독으로 Redis에만 tick 데이터를 쓴다.  
`ws_tick_data` 테이블은 JPA로 정의되어 있지만 **실제 데이터가 전혀 없음**.

또한 tick 데이터를 매 체결마다 DB에 저장하면 하루 수백만 건이 쌓여 성능 문제 발생 가능.

**수정 방향 (선택)**: Java WS 비활성화 상태에서는 WsTickData 엔티티 저장 로직 제거 또는 샘플링 방식으로 전환. 또는 TimescaleDB 확장 고려.

---

## 3. 수정 우선순위 요약

| 우선순위 | 항목 | 파일 | 작업 |
|----------|------|------|------|
| **P1-A** | tp1/tp2/slPrice 엔티티 컬럼 추가 | `TradingSignal.java`, `SignalService.java` | 필드 3개 추가 + 매핑 |
| **P1-B** | FrgnContNettrdRequest baseDtTp 수정 | `StrategyRequests.java` | `"0"` → `"1"` |
| **P1-C** | ddl-auto 변경 | `application.yml` | `create` → `update` |
| **P2-A** | extra_info JSON 저장 | `SignalService.java` | buildSignalEntity() 보완 |
| **P2-B** | 일별 성과 테이블 추가 | 신규 엔티티 + 배치 | SignalPerformanceDaily |
| **P3-A** | ws_tick_data 정리 | 판단 후 진행 | Java WS 활성화 시 재검토 |

---

## 4. 체크리스트

- [x] P1-A: TradingSignal.java에 tp1Price/tp2Price/slPrice 컬럼 추가
- [x] P1-A: SignalService.buildSignalEntity()에서 DTO → 엔티티 매핑 추가
- [x] P1-B: StrategyRequests.FrgnContNettrdRequest baseDtTp = "1"
- [x] P1-C: application.yml ddl-auto: update (이미 ${DDL_AUTO:update}로 설정됨 — 수정 불필요)
- [ ] P2-A: buildSignalEntity()에서 extra_info JSON 직렬화
- [ ] P2-B: SignalPerformanceDailyEntity + Repository + 배치 집계 로직
