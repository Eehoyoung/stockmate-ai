# ka90003 – 프로그램순매수상위50요청

> **전술 사용**: S5(프로그램 순매수 상위 종목 조회)

**URL**: `POST https://api.kiwoom.com/api/dostk/stkinfo`  
**Header**: `api-id: ka90003`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `trde_upper_tp` | String(1) | Y | `1`순매도상위 `2`순매수상위 |
| `amt_qty_tp` | String(2) | Y | `1`금액 `2`수량 |
| `mrkt_tp` | String(10) | Y | ⚠️ **`P00101`코스피 `P10102`코스닥** (001/101 아님!) |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

### Response Body – `prm_netprps_upper_50` (LIST)
| 필드 | 설명 |
|------|------|
| `rank` | 순위 |
| `stk_cd` | 종목코드 |
| `stk_nm` | 종목명 |
| `cur_prc` | 현재가 |
| `flu_rt` | 등락율 |
| `acc_trde_qty` | 누적거래량 |
| `prm_sell_amt` | 프로그램 매도금액 |
| `prm_buy_amt` | 프로그램 매수금액 |
| `prm_netprps_amt` | **프로그램 순매수금액** ← 핵심 |

### S5 표준 호출
```json
// 코스피
{"trde_upper_tp":"2","amt_qty_tp":"1","mrkt_tp":"P00101","stex_tp":"1"}

// 코스닥
{"trde_upper_tp":"2","amt_qty_tp":"1","mrkt_tp":"P10102","stex_tp":"1"}
```

### ⚠️ 중요 주의사항
- `mrkt_tp` 값이 다른 API와 다름: **`P00101`(코스피), `P10102`(코스닥)**
- `001`, `101` 형식 사용 시 오류 발생
- 최대 50개 반환 (연속조회 없음)
