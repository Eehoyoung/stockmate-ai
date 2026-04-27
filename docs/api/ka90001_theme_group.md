# ka90001 – 테마그룹별요청

> **전술 사용**: S6(테마 후발주 – 상위 테마 조회)

**URL**: `POST https://api.kiwoom.com/api/dostk/thme`  
**Header**: `api-id: ka90001`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `qry_tp` | String(1) | Y | `0`전체검색 `1`테마검색 `2`종목검색 |
| `stk_cd` | String(6) | N | 검색 종목코드 |
| `date_tp` | String(2) | Y | n일전 (1~99) |
| `thema_nm` | String(50) | N | 검색 테마명 |
| `flu_pl_amt_tp` | String(1) | Y | `1`상위기간수익률 `2`하위기간수익률 `3`상위등락률 `4`하위등락률 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

### Response Body – `thema_grp` (LIST)
| 필드 | 설명 |
|------|------|
| `thema_grp_cd` | **테마그룹코드** (ka90002 호출에 사용) |
| `thema_nm` | 테마명 |
| `stk_num` | 종목수 |
| `flu_rt` | **등락율** ← 당일 테마 강도 판단 기준 |
| `dt_prft_rt` | 기간수익률 |
| `rising_stk_num` | 상승종목수 |
| `main_stk` | 주요종목 |

### S6 전술 표준 호출 (상위 테마 조회)
```json
{"qry_tp":"0","stk_cd":"","date_tp":"1","thema_nm":"","flu_pl_amt_tp":"1","stex_tp":"1"}
```

### S6 조건
- `flu_rt >= 2.0%` 인 상위 5개 테마만 처리

---

# ka90002 – 테마구성종목요청

> **전술 사용**: S6(테마 구성 종목 조회 → 후발주 필터)

**URL**: `POST https://api.kiwoom.com/api/dostk/thme`  
**Header**: `api-id: ka90002`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `date_tp` | String(1) | N | 1~99일 |
| `thema_grp_cd` | String(6) | Y | **ka90001의 `thema_grp_cd`** |
| `stex_tp` | String(1) | Y | `1`KRX |

### Response Body
| 필드 | 설명 |
|------|------|
| `flu_rt` | 테마 전체 등락률 |
| `thema_comp_stk` | **테마 구성 종목 리스트** |
| `- stk_cd` | 종목코드 |
| `- stk_nm` | 종목명 |
| `- cur_prc` | 현재가 |
| `- flu_rt` | **개별 종목 등락율** ← 후발주 판별 기준 |
| `- acc_trde_qty` | 누적거래량 |
| `- sel_bid` | 매도호가 |
| `- buy_bid` | 매수호가 |

### S6 후발주 필터 로직
```python
# 전체 종목 등락율 리스트 정렬
rates = sorted([float(s.flu_rt) for s in stocks])
p70 = rates[int(len(rates) * 0.7)]  # 70% 분위값

# 후발주 조건: 0.5% <= 등락율 < 70th 분위 AND 등락율 < 5%
laggards = [s for s in stocks if 0.5 <= float(s.flu_rt) < p70 and float(s.flu_rt) < 5.0]
```

### 호출 예시
```json
{"date_tp":"1","thema_grp_cd":"319","stex_tp":"1"}
```
