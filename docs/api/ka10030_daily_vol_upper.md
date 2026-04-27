# ka10030 – 당일거래량상위요청

> **용도**: 당일 누적 거래량 상위 종목 조회 → CandidateService 보조, 유동성 높은 후보 종목 선별  
> ka10033(신용비율상위)과 달리 **거래량 절대값 기준** 으로 정렬

**URL**: `POST https://api.kiwoom.com/api/dostk/rkinfo`  
**모의**: `POST https://mockapi.kiwoom.com/api/dostk/rkinfo`  
**Header**: `api-id: ka10030`

---

## Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | `000`전체 `001`코스피 `101`코스닥 |
| `sort_tp` | String(1) | Y | **`1`거래량 `2`거래회전율 `3`거래대금** |
| `mang_stk_incls` | String(1) | Y | `0`관리종목포함 `1`관리종목미포함 `3`우선주제외 `11`정리매매제외 `4`관리+우선주제외 `5`증100제외 `14`ETF제외 `15`스팩제외 `16`ETF+ETN제외 |
| `crd_tp` | String(1) | Y | `0`전체 `9`신용융자전체 `1~4`신용융자A~D군 `8`신용대주 |
| `trde_qty_tp` | String(1) | Y | `0`전체 `5`5천주이상 `10`1만주이상 `50`5만주이상 `100`10만주이상 `200`20만주 `300`30만주 `500`500만주이상 `1000`백만주이상 |
| `pric_tp` | String(1) | Y | `0`전체 `2`1천원이상 `3`1천~2천원 `4`2천~5천원 `5`5천원이상 `6`5천~1만원 `7`1만원이상 `8`5만원이상 `9`10만원이상 `10`1만원미만 |
| `trde_prica_tp` | String(1) | Y | `0`전체 `1`1천만원이상 `3`3천만원이상 `4`5천만원이상 `10`1억이상 `30`3억이상 `50`5억이상 `100`10억이상 `300`30억이상 `500`50억이상 `1000`100억이상 |
| `mrkt_open_tp` | String(1) | Y | `0`전체 `1`장중 `2`장전시간외 `3`장후시간외 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

---

## Response Body – `tdy_trde_qty_upper` (LIST)

| 필드 | 설명 | 활용 |
|------|------|------|
| `stk_cd` | 종목코드 | |
| `stk_nm` | 종목명 | |
| `cur_prc` | 현재가 | |
| `flu_rt` | 등락률 | |
| **`trde_qty`** | **당일 누적 거래량** | **핵심: 유동성 지표** |
| **`pred_rt`** | **전일비(%)** | **전일 거래량 대비 오늘 거래량 비율** |
| `trde_tern_rt` | 거래회전율 | |
| `trde_amt` | 거래금액(백만원) | |
| `opmr_trde_qty` | 장중거래량 | |
| `af_mkrt_trde_qty` | 장후거래량 | |
| `bf_mkrt_trde_qty` | 장전거래량 | |

---

## 호출 예시

```json
// 거래량 상위, 관리종목 미포함, ETF 제외, 1천원 이상, 장중
{
  "mrkt_tp": "000",
  "sort_tp": "1",
  "mang_stk_incls": "1",
  "crd_tp": "0",
  "trde_qty_tp": "0",
  "pric_tp": "2",
  "trde_prica_tp": "0",
  "mrkt_open_tp": "1",
  "stex_tp": "1"
}

// Response
{
  "tdy_trde_qty_upper": [
    {
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "cur_prc": "-152000",
      "flu_rt": "-0.07",
      "trde_qty": "34954641",
      "pred_rt": "+155.13",
      "trde_tern_rt": "+48.21",
      "trde_amt": "5308092"
    }
  ],
  "returnCode": 0
}
```

---

## ka10033 vs ka10030 비교

| 구분 | ka10033 (신용비율상위) | ka10030 (당일거래량상위) |
|------|----------------------|------------------------|
| 정렬 기준 | 신용비율, 거래량조건 필터 | 거래량 / 회전율 / 거래대금 직접 정렬 |
| 주요 용도 | CandidateService 후보 200종목 | 고유동성 종목 탐색 |
| 세부 필터 | 신용 등급별 필터 가능 | 거래대금/가격/장구분 필터 풍부 |
| 전술 연계 | S7 동시호가 후보 | S4 추격매수 고유동성 종목 |

---

## S4 전술 활용 패턴

```java
// 장중 거래대금 10억 이상 + 전일비 150% 이상 종목 → S4 장대양봉 후보
List<String> highVolCodes = resp.getItems().stream()
    .filter(i -> {
        double predRt = parseDouble(i.getPredRt());
        long trdeAmt  = parseLong(i.getTrdeAmt());
        return predRt >= 150.0 && trdeAmt >= 1000; // 1000백만원 = 10억
    })
    .map(TdyTrdeItem::getStkCd)
    .limit(50)
    .collect(Collectors.toList());
```

---

## 주의

- `returnCode` (카멜케이스) 사용 주의 — 다른 API는 `return_code` (스네이크케이스)
- `pred_rt` = 전일 대비 오늘 거래량 비율 (%), `+155` = 전일보다 2.55배
- `trde_amt` 단위: 백만원 → `1000` = 10억원
- `mrkt_open_tp=1`(장중)으로 설정 시 장전/장후 거래량 제외한 순수 장중 거래량만 집계
