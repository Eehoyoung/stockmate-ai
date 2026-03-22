# ka10001 – 주식기본정보요청

> **용도**: 전일종가(`base_pric`) 확보, 종목명 조회, 상한가/하한가 확인  
> S1/S7 갭 계산 시 `0H` 예상체결가와 비교할 **전일종가** 조회에 사용

**URL**: `POST https://api.kiwoom.com/api/dostk/stkinfo`  
**모의**: `POST https://mockapi.kiwoom.com/api/dostk/stkinfo`  
**Header**: `api-id: ka10001`

---

## Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `stk_cd` | String(20) | Y | 종목코드 (KRX:`039490`, NXT:`039490_NX`, SOR:`039490_AL`) |

---

## Response Body (단건, LIST 아님)

| 필드 | 설명 | 전술 활용 |
|------|------|-----------|
| `stk_cd` | 종목코드 | |
| `stk_nm` | 종목명 | |
| `cur_prc` | **현재가** | |
| `pred_pre` | 전일대비 | |
| `flu_rt` | 등락율 | |
| `trde_qty` | 거래량 | |
| **`base_pric`** | **기준가(전일종가)** | **S1/S7 갭 계산 기준** |
| `upl_pric` | 상한가 | 상한가 여부 확인 |
| `lst_pric` | 하한가 | 하한가 여부 확인 |
| `exp_cntr_pric` | 예상체결가 | 장전 예상체결 확인 |
| `oyr_hgst` | 연중최고 | 신고가 근접 여부 |
| `oyr_lwst` | 연중최저 | |
| `mac` | 시가총액(억) | |
| `flo_stk` | 상장주식수 | |
| `per` | PER | ⚠️ 주 1회 업데이트 |
| `roe` | ROE | ⚠️ 주 1회 업데이트 |
| `pbr` | PBR | |
| `250hgst` | 52주 최고가 | |
| `250lwst` | 52주 최저가 | |
| `open_pric` | 시가 | |
| `high_pric` | 고가 | |
| `low_pric` | 저가 | |

---

## 호출 예시

```json
// Request
{"stk_cd": "005930"}

// Response
{
  "stk_cd": "005930",
  "stk_nm": "삼성전자",
  "cur_prc": "+52700",
  "base_pric": "51600",
  "upl_pric": "67100",
  "lst_pric": "36100",
  "mac": "24352",
  "oyr_hgst": "+181400",
  "oyr_lwst": "-91200",
  "return_code": 0
}
```

---

## 전일종가 확보 활용 패턴

장전 갭 계산 시 `0H` 예상체결(WebSocket)의 전일 기준가를 보완하는 용도:

```java
// S1/S7 전술에서 장 시작 전 일괄 조회 후 Redis 캐싱 권장
// key: "stock:base:{stkCd}", TTL: 하루 (장중 변하지 않음)

double expPrice  = getExpectedData(stkCd).get("exp_cntr_pric");
double prevClose = getBasePriceFromCache(stkCd); // ka10001로 사전 조회
double gapPct    = (expPrice - prevClose) / prevClose * 100;
```

---

## 주의

- PER, ROE는 외부 벤더 제공 데이터 → **실시간 아님**, 주 1회 업데이트
- `base_pric`(기준가) = 전일 종가 기준 (권리락 등 조정 반영)
- 연속조회 없음 (종목 1개씩 호출)
