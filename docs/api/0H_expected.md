# 0H – 주식예상체결 (실시간)

> **전술 사용**: S1/S7 – 장전 갭 계산의 핵심 데이터

**WebSocket URL**: `wss://api.kiwoom.com:10000/api/dostk/websocket`  
**활성 시간**: 08:00~09:00 (장 시작 전 동시호가)

## 구독 요청

```json
{
  "trnm": "REG",
  "grp_no": "3",
  "refresh": "1",
  "data": [{"item": ["005930"], "type": ["0H"]}]
}
```

## 실시간 수신 – `values` 필드

| 키 | 한글명 | 설명 |
|----|--------|------|
| `20` | 예상체결시간 | HHmmss |
| **`10`** | **예상체결가** | **갭 계산 분자** |
| `11` | 전일대비 | 전일종가 대비 등락금액 (Java: `exp_pred_pre`) |
| **`12`** | **예상등락율** | **예상 갭% 직접 확인 가능** |
| `15` | 예상체결수량 | |
| `13` | 누적거래량 | |

## Redis 저장 구조

```
ws:expected:{stkCd}  (Hash, TTL 60s)
  exp_cntr_pric:  10번 필드 (예상체결가)
  exp_pred_pre:   11번 필드 (전일대비 등락금액)
  exp_flu_rt:     12번 필드 (예상등락율)
  exp_cntr_qty:   15번 필드 (예상체결수량)
  pred_pre_pric:  전일종가 (exp_cntr_pric / (1 + exp_flu_rt/100) 역산)
  exp_cntr_tm:    20번 필드 (예상체결시간)
```

## 갭 계산 방법

```java
// RedisMarketDataService 에서
double expPrice  = parseDouble(exp, "exp_cntr_pric");  // 예상체결가
double prevClose = parseDouble(exp, "pred_pre_pric");  // 전일종가

// 갭% 계산
double gapPct = (expPrice - prevClose) / prevClose * 100;

// 전술별 기준:
// S1: 3.0% <= gapPct <= 15.0%
// S7: 2.0% <= gapPct <= 10.0%
```

## 전일종가 확보 방법

`0H` 응답의 `10`번 값은 예상체결가이고 전일종가가 아님.  
전일종가는 아래 중 하나로 확보:
1. `0D` 호가잔량의 `200`번 필드 (예상체결가전일종가대비)
2. `ka10001` 주식기본정보 REST 호출
3. Redis에 장 시작 전 ka10001로 미리 저장

## 수신 예시

```json
{
  "trnm": "REAL",
  "data": [{
    "type": "0H",
    "name": "주식예상체결",
    "item": "005930",
    "values": {
      "20": "110206",
      "10": "+60500",
      "11": "+200",
      "12": "+0.33",
      "15": "-7805",
      "13": "768293"
    }
  }]
}
```

## 주의

- 장중에는 `0H` 데이터가 의미 없음 → 정규장 시작 후 구독 해제 권장
- `WebSocketSubscriptionManager.setupMarketHoursSubscription()` 에서 `GRP 3` 해제 처리됨
