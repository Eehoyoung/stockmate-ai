# ka10081 – 주식일봉차트조회요청

> **전술 사용**: S3(연속 상승 확인), 보조 분석

**URL**: `POST https://api.kiwoom.com/api/dostk/chart`  
**Header**: `api-id: ka10081`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `stk_cd` | String(20) | Y | 종목코드 |
| `base_dt` | String(8) | Y | YYYYMMDD 기준일자 |
| `upd_stkpc_tp` | String(1) | Y | `0` or `1` |

### Response Body – `stk_dt_pole_chart_qry` (LIST)
| 필드 | 설명 |
|------|------|
| `dt` | 일자 (YYYYMMDD) |
| `cur_prc` | 현재가(종가) |
| `open_pric` | 시가 |
| `high_pric` | 고가 |
| `low_pric` | 저가 |
| `trde_qty` | 거래량 |
| `trde_prica` | 거래대금 (백만원) |
| `pred_pre` | 전일대비 |
| `trde_tern_rt` | 거래회전율 |

### 호출 예시
```json
{"stk_cd":"005930","base_dt":"20250908","upd_stkpc_tp":"1"}
```
