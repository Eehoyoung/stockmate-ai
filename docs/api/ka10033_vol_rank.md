# ka10033 – 신용비율상위요청 (거래량순위 용도로 사용)

> **전술 사용**: S7(동시호가 후보), CandidateService 후보 종목 조회

**URL**: `POST https://api.kiwoom.com/api/dostk/rkinfo`  
**Header**: `api-id: ka10033`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | `000`전체 `001`코스피 `101`코스닥 |
| `trde_qty_tp` | String(3) | Y | `0`전체 `10`만주이상 `50`5만주이상 `100`10만주이상 `200`20만주 `300`30만주 `500`50만주 `1000`백만주 |
| `stk_cnd` | String(1) | Y | `0`전체 `1`관리종목제외 `5`증100제외 `6`증100만 `7`증40만 `8`증30만 `9`증20만 |
| `updown_incls` | String(1) | Y | `0`상하한미포함 `1`상하한포함 |
| `crd_cnd` | String(1) | Y | `0`전체 `1~4`신용융자A~D군 `7`E군 `9`전체 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

### Response Body – `crd_rt_upper` (LIST)
| 필드 | 설명 |
|------|------|
| `stk_cd` | 종목코드 |
| `stk_nm` | 종목명 |
| `cur_prc` | 현재가 |
| `flu_rt` | 등락률 |
| `crd_rt` | 신용비율 |
| `sel_req` | 매도잔량 |
| `buy_req` | 매수잔량 |
| `now_trde_qty` | 현재거래량 |

### CandidateService 표준 호출
```json
{"mrkt_tp":"001","trde_qty_tp":"10","stk_cnd":"1","updown_incls":"0","crd_cnd":"0","stex_tp":"1"}
```

### 주의
- 응답 배열 키: `crd_rt_upper` (신용비율 상위)
- 거래량 필터(`trde_qty_tp`) 활용하여 유동성 있는 종목만 조회
