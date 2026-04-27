# ka90009 – 외국인기관매매상위요청

> **전술 사용**: S5(외국인 순매수 상위 종목 → S3 교집합 필터)

**URL**: `POST https://api.kiwoom.com/api/dostk/rkinfo`  
**Header**: `api-id: ka90009`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | `000`전체 `001`코스피 `101`코스닥 |
| `amt_qty_tp` | String(1) | Y | `1`금액(천만원) `2`수량(천주) |
| `qry_dt_tp` | String(1) | Y | `0`조회일자미포함 `1`조회일자포함 |
| `date` | String(8) | N | YYYYMMDD |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

### Response Body – `frgnr_orgn_trde_upper` (LIST)
> 외인순매도/순매수, 기관순매도/순매수가 **각 행에 같이** 들어있는 구조

| 필드 | 설명 |
|------|------|
| `for_netprps_stk_cd` | **외인 순매수 종목코드** ← 핵심 |
| `for_netprps_stk_nm` | 외인 순매수 종목명 |
| `for_netprps_amt` | 외인 순매수금액 |
| `orgn_netprps_stk_cd` | 기관 순매수 종목코드 |
| `orgn_netprps_amt` | 기관 순매수금액 |
| `for_netslmt_stk_cd` | 외인 순매도 종목코드 |

### S5 표준 호출 및 처리
```java
// 호출
FrgnInstUpperRequest req = FrgnInstUpperRequest.builder()
    .mrktTp("000").amtQtyTp("1").qryDtTp("0").stexTp("1").build();

// 외인 순매수 종목코드 Set 추출
Set<String> frgnBuySet = resp.getItems().stream()
    .map(FrgnInstUpperResponse.FrgnItem::getForNetprpsStkCd)
    .filter(Objects::nonNull)
    .collect(Collectors.toSet());
```

### 주의
- 응답 구조가 특이: 한 행에 순매도/순매수 종목이 함께 있음
- `for_netprps_stk_cd` 와 `for_netslmt_stk_cd` 는 서로 다른 종목
