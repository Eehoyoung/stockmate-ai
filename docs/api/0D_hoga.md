# 0D – 주식호가잔량 (실시간)

> **전술 사용**: S1/S2/S7 호가 매수/매도 비율 계산

**WebSocket URL**: `wss://api.kiwoom.com:10000/api/dostk/websocket`

## 구독 요청

```json
{
  "trnm": "REG",
  "grp_no": "2",
  "refresh": "1",
  "data": [{"item": ["005930"], "type": ["0D"]}]
}
```

## 실시간 수신 – `values` 핵심 필드

| 키 | 한글명 | 설명 |
|----|--------|------|
| `21` | 호가시간 | HHmmss |
| `41`~`50` | 매도호가 1~10 | |
| `61`~`70` | 매도호가수량 1~10 | |
| `51`~`60` | 매수호가 1~10 | |
| `71`~`80` | 매수호가수량 1~10 | |
| **`121`** | **매도호가총잔량** | **호가비율 계산 분모** |
| **`125`** | **매수호가총잔량** | **호가비율 계산 분자** |
| `128` | 순매수잔량 | 매수잔량 - 매도잔량 |
| `129` | 매수비율 | % |

## Redis 저장 구조

```
ws:hoga:{stkCd}  (Hash, TTL 10s)
  total_buy_bid_req:  125번 필드 (매수호가총잔량)
  total_sel_bid_req:  121번 필드 (매도호가총잔량)
  buy_bid_pric_1:     51번 필드 (매수 1호가)
  sel_bid_pric_1:     41번 필드 (매도 1호가)
  bid_req_base_tm:    21번 필드 (호가시간)
```

## 호가비율 계산 (bidRatio)

```java
// RedisMarketDataService 에서
double bid = parseDouble(hoga, "total_buy_bid_req");  // 125번
double ask = parseDouble(hoga, "total_sel_bid_req");  // 121번
double bidRatio = ask > 0 ? bid / ask : 0;

// 전술별 기준:
// S1: bidRatio >= 1.3 (매수잔량이 매도잔량의 1.3배 이상)
// S2: bidRatio >= 1.3
// S7: bidRatio >= 2.0
```

## 수신 예시

```json
{
  "trnm": "REAL",
  "data": [{
    "type": "0D",
    "name": "주식호가잔량",
    "item": "005930",
    "values": {
      "21": "165207",
      "41": "-20800",
      "61": "82",
      "51": "-20700",
      "71": "23847",
      "121": "12622527",
      "125": "14453430",
      "128": "+1830903",
      "129": "114.51"
    }
  }]
}
```
