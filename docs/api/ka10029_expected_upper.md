# ka10029 – 예상체결등락률상위요청

> **용도**: 장전 동시호가 구간에서 갭상승 후보 전체 시장 스캔  
> S1(갭상승 시초가) · S7(동시호가) 후보 종목 일괄 탐색

**URL**: `POST https://api.kiwoom.com/api/dostk/rkinfo`  
**모의**: `POST https://mockapi.kiwoom.com/api/dostk/rkinfo`  
**Header**: `api-id: ka10029`  
**활성 시간**: **08:00~09:00** (장전 동시호가 구간에서 의미 있는 데이터)

---

## Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `mrkt_tp` | String(3) | Y | `000`전체 `001`코스피 `101`코스닥 |
| `sort_tp` | String(1) | Y | **`1`상승률 `2`상승폭 `3`보합 `4`하락률 `5`하락폭 `6`체결량 `7`상한 `8`하한** |
| `trde_qty_cnd` | String(5) | Y | `0`전체 `1`천주이상 `3`3천주 `5`5천주 `10`만주이상 `50`5만주이상 `100`10만주이상 |
| `stk_cnd` | String(2) | Y | `0`전체 `1`관리종목제외 `3`우선주제외 `4`관리+우선주제외 `5`증100제외 `11`정리매매제외 `14`ETF제외 `15`스팩제외 `16`ETF+ETN제외 |
| `crd_cnd` | String(1) | Y | `0`전체 `9`신용융자전체 |
| `pric_cnd` | String(2) | Y | `0`전체 `1`1천원미만 `2`1천원~2천원 `3`2천원~5천원 `4`5천원~1만원 `5`1만원이상 `8`1천원이상 `10`1만원미만 |
| `stex_tp` | String(1) | Y | `1`KRX `2`NXT `3`통합 |

---

## Response Body – `exp_cntr_flu_rt_upper` (LIST)

| 필드 | 설명 | 활용 |
|------|------|------|
| `stk_cd` | 종목코드 | |
| `stk_nm` | 종목명 | |
| **`exp_cntr_pric`** | **예상체결가** | **갭 계산 분자** |
| **`base_pric`** | **기준가(전일종가)** | **갭 계산 분모** |
| **`flu_rt`** | **예상 등락률(%)** | **갭% 직접 확인 가능** |
| `pred_pre` | 전일대비 | |
| `exp_cntr_qty` | 예상체결량 | |
| `sel_req` | 매도잔량 | |
| `sel_bid` | 매도호가 | |
| `buy_bid` | 매수호가 | |
| `buy_req` | 매수잔량 | |

---

## 호출 예시

```json
// 상승률 상위, 만주 이상, 관리종목+ETF 제외, 1천원 이상
{
  "mrkt_tp": "000",
  "sort_tp": "1",
  "trde_qty_cnd": "10",
  "stk_cnd": "1",
  "crd_cnd": "0",
  "pric_cnd": "8",
  "stex_tp": "1"
}

// Response
{
  "exp_cntr_flu_rt_upper": [
    {
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "exp_cntr_pric": "+48100",
      "base_pric": "37000",
      "pred_pre_sig": "1",
      "pred_pre": "+11100",
      "flu_rt": "+30.00",
      "exp_cntr_qty": "1",
      "sel_req": "0",
      "buy_bid": "0",
      "buy_req": "0"
    }
  ],
  "return_code": 0
}
```

---

## S1/S7 전술 활용 패턴

```java
// S1: 갭상승 3~15% 종목 일괄 필터 (WebSocket 0H 개별 조회 대신 사용 가능)
List<TradingSignalDto> s1Candidates = resp.getItems().stream()
    .filter(item -> {
        double fluRt = parseDouble(item.getFluRt());
        return fluRt >= 3.0 && fluRt <= 15.0;
    })
    .map(item -> TradingSignalDto.builder()
        .stkCd(item.getStkCd())
        .stkNm(item.getStkNm())
        .gapPct(parseDouble(item.getFluRt()))
        .build())
    .collect(Collectors.toList());

// S7: 갭 2~10% 필터 후 Redis 0D 호가비율 개별 확인
```

---

## 0H WebSocket vs ka10029 비교

| 구분 | 0H WebSocket | ka10029 REST |
|------|-------------|-------------|
| 방식 | 종목별 실시간 push | 전체 시장 순위 일괄 조회 |
| 속도 | 빠름 | 느림 (REST 호출) |
| 활용 | 구독 종목 실시간 모니터링 | 장전 갭 후보 전수 탐색 |
| 추천 | 구독 종목 확정 후 | **구독 전 후보 선별 시** |

---

## 주의

- 장중에는 예상체결 값이 의미 없으므로 **08:00~09:00** 에만 호출
- `flu_rt` 값에 `+` 기호 포함 → `NumberParseUtil.toDouble()` 사용
- `base_pric` = 전일 기준가 (권리락 반영 조정가)
