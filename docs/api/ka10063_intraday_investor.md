# ka10063 – 장중투자자별매매요청

> **전술 사용**: S3(외인+기관 동시 순매수 스캔)

**URL**: `POST https://api.kiwoom.com/api/dostk/mrkcond`  
**Header**: `api-id: ka10063`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | `000`전체 `001`코스피 `101`코스닥 |
| `amt_qty_tp` | String(1) | Y | `1`금액&수량 |
| `invsr` | String(1) | Y | `6`외국인 `7`기관계 `1`투신 `0`보험 `2`은행 `3`연기금 `4`국가 `5`기타법인 |
| `frgn_all` | String(1) | Y | `1`외국계전체체크 `0`미체크 |
| `smtm_netprps_tp` | String(1) | Y | `1`동시순매수체크 `0`미체크 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

### Response Body – `opmr_invsr_trde` (LIST)
| 필드 | 설명 |
|------|------|
| `stk_cd` | 종목코드 |
| `stk_nm` | 종목명 |
| `cur_prc` | 현재가 |
| `flu_rt` | 등락율 |
| `acc_trde_qty` | 누적거래량 |
| `netprps_qty` | **순매수수량** ← 핵심 |
| `netprps_amt` | 순매수금액 (천원) |
| `buy_qty` | 매수수량 |
| `sell_qty` | 매도수량 |

### S3 전술 표준 호출 (외국인 동시순매수)
```json
{"mrkt_tp":"001","amt_qty_tp":"1","invsr":"6","frgn_all":"1","smtm_netprps_tp":"1","stex_tp":"1"}
```

### 주의
- `smtm_netprps_tp: "1"` 설정 시 외인+기관 **동시** 순매수 종목만 반환
- 코스피/코스닥 각각 별도 호출 필요 (`mrkt_tp: "001"`, `"101"`)
- `netprps_qty` 값에 `+`, `-` 기호 포함 → `NumberParseUtil.toLong()` 사용
