# ka10046 – 체결강도추이시간별요청

> **전술 사용**: S1(갭상승 체결강도 확인), S2(VI 눌림목 강도 확인), S3, S4, S6

**URL**: `POST https://api.kiwoom.com/api/dostk/mrkcond`  
**Header**: `api-id: ka10046`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `stk_cd` | String(6) | Y | 종목코드 (KRX:039490, NXT:039490_NX, SOR:039490_AL) |

### Response Body – `cntr_str_tm` (LIST)
| 필드 | 설명 |
|------|------|
| `cntr_tm` | 체결시간 (HHmmss) |
| `cur_prc` | 현재가 |
| `flu_rt` | 등락율 |
| `trde_qty` | 거래량 |
| `acc_trde_qty` | 누적거래량 |
| `acc_trde_prica` | 누적거래대금 |
| `cntr_str` | **체결강도** ← 핵심 필드 |
| `cntr_str_5min` | 체결강도 5분 |
| `cntr_str_20min` | 체결강도 20분 |
| `cntr_str_60min` | 체결강도 60분 |

### 체결강도 해석
- 100 기준: 100초과 = 매수우세, 100미만 = 매도우세
- S1 진입 조건: 최근 5개 평균 **130 이상**
- S2 진입 조건: 최근 3개 평균 **110 이상**
- S4 진입 조건: 최근 3개 평균 **140 이상**

### 호출 예시
```json
// Request
{"stk_cd": "005930"}

// Response
{"cntr_str_tm": [{"cntr_tm":"163713","cur_prc":"+156600","flu_rt":"+28.68","cntr_str":"172.01",...}], "return_code":0}
```

### Redis 저장 (ws:strength:{stkCd})
- WebSocket 0B 수신 시 `values.228` (체결강도) 를 List에 lpush
- 최근 10개 유지, TTL 5분
- `RedisMarketDataService.getAvgCntrStrength(stkCd, N)` 으로 조회
