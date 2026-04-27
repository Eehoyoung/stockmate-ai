# ka10131 – 기관외국인연속매매현황요청

> **전술 사용**: S3(연속 N일 순매수 확인)

**URL**: `POST https://api.kiwoom.com/api/dostk/frgnistt`  
**Header**: `api-id: ka10131`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `dt` | String(3) | Y | `1`최근1일 `3`3일 `5`5일 `10`10일 `20`20일 `120`120일 `0`시작일자/종료일자로조회 |
| `strt_dt` | String(8) | N | YYYYMMDD (dt=0 일 때 필수) |
| `end_dt` | String(8) | N | YYYYMMDD |
| `mrkt_tp` | String(3) | Y | `001`코스피 `101`코스닥 |
| `netslmt_tp` | String(1) | Y | `2`순매수 (고정값) |
| `stk_inds_tp` | String(1) | Y | `0`종목(주식) `1`업종 |
| `amt_qty_tp` | String(1) | Y | `0`금액 `1`수량 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

### Response Body – `orgn_frgnr_cont_trde_prst` (LIST)
| 필드 | 설명 |
|------|------|
| `rank` | 순위 |
| `stk_cd` | 종목코드 |
| `stk_nm` | 종목명 |
| `orgn_cont_netprps_dys` | **기관 연속순매수 일수** ← 핵심 |
| `orgn_nettrde_amt` | 기관순매매금액 |
| `frgnr_cont_netprps_dys` | **외국인 연속순매수 일수** ← 핵심 |
| `frgnr_nettrde_amt` | 외국인순매매금액 |
| `tot_cont_netprps_dys` | 합계 연속순매수 일수 |

### S3 전술 표준 호출 (3일 연속)
```json
{"dt":"3","strt_dt":"","end_dt":"","mrkt_tp":"001","netslmt_tp":"2","stk_inds_tp":"0","amt_qty_tp":"0","stex_tp":"1"}
```

### 주의
- `mrkt_tp`는 `001` 또는 `101`만 가능 (000 전체 미지원)
- 코스피/코스닥 각각 호출 후 Set으로 교집합 → S3 후보 필터
