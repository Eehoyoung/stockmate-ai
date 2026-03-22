# ka10020 – 호가잔량상위요청

> **용도**: 매수잔량 압도적 상위 종목 조회 → S1/S7 호가비율 사전 필터링, 장전 세력 감지

**URL**: `POST https://api.kiwoom.com/api/dostk/rkinfo`  
**모의**: `POST https://mockapi.kiwoom.com/api/dostk/rkinfo`  
**Header**: `api-id: ka10020`

---

## Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | **`001`코스피 `101`코스닥** (000 전체 미지원) |
| `sort_tp` | String(1) | Y | **`1`순매수잔량순 `2`순매도잔량순 `3`매수비율순 `4`매도비율순** |
| `trde_qty_tp` | String(4) | Y | `0000`장시작전(0주이상) `0010`만주이상 `0050`5만주이상 `00100`10만주이상 |
| `stk_cnd` | String(1) | Y | `0`전체 `1`관리종목제외 `5`증100제외 `6`증100만 `7`증40만 `8`증30만 `9`증20만 |
| `crd_cnd` | String(1) | Y | `0`전체 `9`신용융자전체 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

---

## Response Body – `bid_req_upper` (LIST)

| 필드 | 설명 | 활용 |
|------|------|------|
| `stk_cd` | 종목코드 | |
| `stk_nm` | 종목명 | |
| `cur_prc` | 현재가 | |
| `flu_rt` | 등락률 | |
| `trde_qty` | 거래량 | |
| **`tot_sel_req`** | **총 매도잔량** | |
| **`tot_buy_req`** | **총 매수잔량** | |
| **`netprps_req`** | **순매수잔량** (= 매수 - 매도) | **핵심: 양수일수록 매수 압력 강함** |
| **`buy_rt`** | **매수비율** (%) | **100 이상이면 매수잔량 > 매도잔량** |

---

## 호출 예시

```json
// 코스피 순매수잔량 상위 (장전 포함, 관리종목 제외)
{
  "mrkt_tp": "001",
  "sort_tp": "1",
  "trde_qty_tp": "0000",
  "stk_cnd": "1",
  "crd_cnd": "0",
  "stex_tp": "1"
}

// Response
{
  "bid_req_upper": [
    {
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "cur_prc": "+65000",
      "trde_qty": "214670",
      "tot_sel_req": "1",
      "tot_buy_req": "22287",
      "netprps_req": "22286",
      "buy_rt": "2228700.00"
    }
  ],
  "return_code": 0
}
```

---

## S7 전술 활용 패턴

```java
// S7 동시호가 보조: 호가잔량 상위 → 0H 예상체결 교집합
// 1. ka10020 sort_tp=3(매수비율순) 상위 조회
// 2. 0H 예상체결가 갭 2~10% 조건 필터
// 3. bidRatio = buy_rt / 100 으로 환산

List<String> bidUpperCodes = resp.getItems().stream()
    .filter(i -> Double.parseDouble(i.getBuyRt()) >= 200.0) // 매수비율 200% 이상
    .map(BidItem::getStkCd)
    .collect(Collectors.toList());
```

---

## 주의

- `mrkt_tp`는 `001` 또는 `101`만 지원 (000 전체 미지원)
- `buy_rt`는 `%` 단위 → `200.00` = 매수잔량이 매도잔량의 2배
- `trde_qty_tp` = `"0000"` 설정 시 장 시작 전(거래량 0) 종목 포함
- 코스피/코스닥 각각 별도 호출 필요
