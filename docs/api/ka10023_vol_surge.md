# ka10023 – 거래량급증요청

> **용도**: 단기 거래량 급증 종목 탐지 → S4(장대양봉) 사전 필터, 세력 개입 종목 조기 감지

**URL**: `POST https://api.kiwoom.com/api/dostk/rkinfo`  
**모의**: `POST https://mockapi.kiwoom.com/api/dostk/rkinfo`  
**Header**: `api-id: ka10023`

---

## Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | `000`전체 `001`코스피 `101`코스닥 |
| `sort_tp` | String(1) | Y | **`1`급증량 `2`급증률 `3`급감량 `4`급감률** |
| `tm_tp` | String(1) | Y | **`1`분 `2`전일** |
| `trde_qty_tp` | String(1) | Y | `5`5천주이상 `10`만주이상 `50`5만주이상 `100`10만주이상 `200`20만주 `300`30만주 `500`50만주 `1000`백만주 |
| `tm` | String(2) | N | 분 입력 (`tm_tp=1` 일 때 사용, 예: `"5"` = 5분 내) |
| `stk_cnd` | String(1) | Y | `0`전체 `1`관리종목제외 `3`우선주제외 `11`정리매매제외 `14`ETF제외 `15`스팩제외 `18`ETF+ETN제외 `20`ETF+ETN+스팩제외 |
| `pric_tp` | String(1) | Y | `0`전체 `2`5만원이상 `5`1만원이상 `6`5천원이상 `8`1천원이상 `9`10만원이상 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

---

## Response Body – `trde_qty_sdnin` (LIST)

| 필드 | 설명 | 활용 |
|------|------|------|
| `stk_cd` | 종목코드 | |
| `stk_nm` | 종목명 | |
| `cur_prc` | 현재가 | |
| `flu_rt` | 등락률 | |
| **`prev_trde_qty`** | **이전 거래량** | **기준 시점 거래량** |
| **`now_trde_qty`** | **현재 거래량** | **현재 누적 거래량** |
| **`sdnin_qty`** | **급증량** | **now - prev** |
| **`sdnin_rt`** | **급증률** | **핵심: 거래량 증가 비율(%)** |

---

## 호출 예시

```json
// 5분 내 거래량 급증률 상위 (만주 이상, 관리종목/ETF 제외)
{
  "mrkt_tp": "000",
  "sort_tp": "2",
  "tm_tp": "1",
  "trde_qty_tp": "10",
  "tm": "5",
  "stk_cnd": "1",
  "pric_tp": "8",
  "stex_tp": "1"
}

// Response
{
  "trde_qty_sdnin": [
    {
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "cur_prc": "-152000",
      "flu_rt": "-0.07",
      "prev_trde_qty": "22532511",
      "now_trde_qty": "31103523",
      "sdnin_qty": "+8571012",
      "sdnin_rt": "+38.04"
    }
  ],
  "return_code": 0
}
```

---

## S4 전술 보조 활용

```java
// 3분봉 스캔 전 ka10023으로 거래량 급증 종목 우선 추출
// → ka10080 분봉 호출 대상 축소 (API 호출 최소화)

// 전일 대비 거래량 급증 (tm_tp=2)
// sort_tp=2 (급증률순) + sdnin_rt >= 50% → 후보 리스트
// → 해당 종목만 ka10080으로 장대양봉 확인

List<String> surgeTargets = resp.getItems().stream()
    .filter(i -> Double.parseDouble(i.getSdninRt().replace("+","")) >= 50.0)
    .map(VolumeItem::getStkCd)
    .limit(30)
    .collect(Collectors.toList());
```

---

## 주의

- `tm_tp=1`(분) 선택 시 `tm` 필드 필수 입력 (예: `"3"`, `"5"`, `"10"`)
- `tm_tp=2`(전일) 선택 시 `tm` 필드 불필요
- `sdnin_rt` 에 `+` 기호 포함 → `NumberParseUtil.toDouble()` 사용
- 급증률 순(`sort_tp=2`) 정렬이 실전에서 더 유용 (거래량 절대값보다 변화율이 중요)
