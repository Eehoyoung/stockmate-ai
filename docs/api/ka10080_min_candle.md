# ka10080 – 주식분봉차트조회요청

> **전술 사용**: S4(장대양봉 + 거래량 급증 판별)

**URL**: `POST https://api.kiwoom.com/api/dostk/chart`  
**Header**: `api-id: ka10080`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `stk_cd` | String(20) | Y | 종목코드 |
| `tic_scope` | String(2) | Y | `1`1분 `3`3분 `5`5분 `10`10분 `15`15분 `30`30분 `45`45분 `60`60분 |
| `upd_stkpc_tp` | String(1) | Y | `0` or `1` (수정주가여부) |
| `base_dt` | String(8) | N | YYYYMMDD (기준일자, 미입력 시 당일) |

### Response Body
| 필드 | 설명 |
|------|------|
| `stk_cd` | 종목코드 |
| `stk_min_pole_chart_qry` | **분봉 데이터 리스트** |
| `- cur_prc` | 현재가 (=종가) |
| `- open_pric` | 시가 |
| `- high_pric` | 고가 |
| `- low_pric` | 저가 |
| `- trde_qty` | 거래량 |
| `- cntr_tm` | 체결시간 (YYYYMMDDHHmmss) |
| `- pred_pre` | 전일대비 |

### S4 전술 장대양봉 조건
```
5분봉 기준 (tic_scope: "5"):
  1. 현재봉 종가(cur_prc) > 시가(open_pric) → 양봉
  2. 몸통비율 = (종가 - 시가) / (고가 - 저가) >= 0.7
  3. 상승폭 = (종가 - 시가) / 시가 * 100 >= 3.0%
  4. 거래량비율 = 현재봉 거래량 / 직전5봉 평균거래량 >= 5배
  5. 체결강도(Redis ws:strength) >= 140
  6. 신고가 여부: 현재 고가 >= 직전 96봉(8시간) 고가 최대값
```

### 표준 호출 (5분봉 당일)
```json
{"stk_cd":"005930","tic_scope":"5","upd_stkpc_tp":"1"}
```

### 주의
- 인덱스 0 = 가장 최근 봉
- 숫자 앞에 `+`, `-` 기호 포함 → `NumberParseUtil.toDouble()` 사용
- 연속조회(cont-yn=Y)로 더 많은 봉 데이터 조회 가능
