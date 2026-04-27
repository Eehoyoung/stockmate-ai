# Kiwoom REST API Reference — StockMate AI

각 전략에서 사용하는 키움 REST API의 요청/응답 명세입니다.
API 업데이트 시 이 문서를 기준으로 코드를 수정하세요.

---

## 수정 방법 (공통)

1. **요청 헤더 변경** → 각 전략 파일의 `headers` dict에서 `api-id` 값을 새 ID로 교체
2. **요청 바디 필드 변경** → `json={...}` payload의 키 이름/값 수정
3. **응답 바디 필드 변경** → `data.get("배열키", [])` 및 `item.get("필드명")` 부분 수정
4. **엔드포인트 URL 변경** → `KIWOOM_BASE_URL` 환경변수 또는 `client.post(f".../{경로}")` 수정
5. **연속조회 헤더** → 요청 헤더 `cont-yn: Y`, `next-key: <값>` / 응답 헤더 `cont-yn`, `next-key` 패턴은 모든 API 공통

---

## 공통 헤더 패턴

```python
headers = {
    "api-id": "kaXXXXX",                            # API ID (변경 시 이 값만 교체)
    "authorization": f"Bearer {token}",
    "Content-Type": "application/json;charset=UTF-8"
}
# 연속조회 시 추가
headers["cont-yn"] = "Y"
headers["next-key"] = next_key   # 이전 응답의 next-key 헤더값
```

**Base URL**: `https://api.kiwoom.com` (환경변수 `KIWOOM_BASE_URL`)

---

## API 목록

| API ID | 엔드포인트 | 설명 | 사용 파일 |
|--------|-----------|------|----------|
| ka10001 | /api/dostk/stkinfo | 주식기본정보 (종목명) | http_utils.py |
| ka10016 | /api/dostk/stkinfo | 신고저가 요청 | strategy_10 |
| ka10023 | /api/dostk/rkinfo | 거래량 급증 요청 | strategy_10 |
| ka10027 | /api/dostk/rkinfo | 전일대비 등락률 상위 | strategy_12 |
| ka10029 | /api/dostk/rkinfo | 예상체결 등락률 상위 | strategy_1, strategy_7 |
| ka10033 | /api/dostk/rkinfo | 신용비율 상위 | strategy_7 |
| ka10035 | /api/dostk/rkinfo | 외인 연속 순매매 상위 | strategy_11 |
| ka10044 | /api/dostk/mrkcond | 전일 기관 순매매 | strategy_5 |
| ka10046 | /api/dostk/mrkcond | 체결강도 추이 시간별 | http_utils.py |
| ka10055 | /api/dostk/stkinfo | 당일전일 체결량 비교 | strategy_3 |
| ka10063 | /api/dostk/mrkcond | 장중 투자자별 매매 | strategy_3, strategy_12 |
| ka10080 | /api/dostk/chart | 주식 분봉 차트 | strategy_4, strategy_5, strategy_15 |
| ka10081 | /api/dostk/chart | 주식 일봉 차트 | strategy_8,9,10,13,14,15, ma_utils |
| ka10131 | /api/dostk/frgnistt | 기관외국인 연속매매 | strategy_3 |
| ka90001 | /api/dostk/thme | 테마 그룹별 상위 수익률 | strategy_6 |
| ka90002 | /api/dostk/thme | 테마 구성 종목 | strategy_6 |
| ka90003 | /api/dostk/stkinfo | 프로그램 순매수 상위50 | strategy_5 |
| ka90009 | /api/dostk/rkinfo | 외국인기관 매매 상위 | strategy_5 |

---

## 상세 명세

---

### ka10001 — 주식기본정보 (종목명 조회)

**파일**: `http_utils.py` → `fetch_stk_nm()`  
**엔드포인트**: `POST /api/dostk/stkinfo`

**요청 바디**
```json
{
  "stk_cd": "005930"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| stk_cd | string | 종목코드 (6자리) |

**응답 바디 (사용 필드)**
```json
{
  "stk_info": [
    { "stk_nm": "삼성전자" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| stk_info[].stk_nm | string | 종목명 |

**수정 위치**: `http_utils.py:fetch_stk_nm()` — `data.get("stk_info", [])`, `item.get("stk_nm")`

---

### ka10016 — 신고저가 요청

**파일**: `strategy_10_new_high.py`  
**엔드포인트**: `POST /api/dostk/stkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "000",
  "ntl_tp": "1",
  "high_low_close_tp": "1",
  "stk_cnd": "1",
  "trde_qty_tp": "00010",
  "crd_cnd": "0",
  "updown_incls": "0",
  "dt": "250",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | "000"=전체, "001"=코스피, "101"=코스닥 |
| ntl_tp | string | "1"=신고가, "2"=신저가 |
| high_low_close_tp | string | "1"=고가기준 |
| stk_cnd | string | "1"=관리종목 제외 |
| trde_qty_tp | string | "00010"=1천만주 이상 |
| crd_cnd | string | "0"=전체 |
| updown_incls | string | "0"=상하한 포함 |
| dt | string | "250"=250 거래일 기준 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "ntl_pric": [
    { "stk_cd": "005930", "cur_prc": "75000", "flu_rt": "3.5", "stk_nm": "삼성전자" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| ntl_pric[].stk_cd | string | 종목코드 |
| ntl_pric[].cur_prc | string | 현재가 |
| ntl_pric[].flu_rt | string | 등락률(%) |
| ntl_pric[].stk_nm | string | 종목명 |

**연속조회**: 지원 (`cont-yn`, `next-key` 헤더)  
**수정 위치**: `strategy_10_new_high.py` → `data.get("ntl_pric", [])`

---

### ka10023 — 거래량 급증 요청

**파일**: `strategy_10_new_high.py`  
**엔드포인트**: `POST /api/dostk/rkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "000",
  "sort_tp": "2",
  "tm_tp": "2",
  "trde_qty_tp": "10",
  "stk_cnd": "20",
  "pric_tp": "8",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | 시장구분 |
| sort_tp | string | "2"=급증률순 |
| tm_tp | string | "2"=전일대비 |
| trde_qty_tp | string | "10"=1천만주 이상 |
| stk_cnd | string | "20"=ETF/ETN/SPAC 제외 |
| pric_tp | string | "8"=1000원 이상 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "trde_qty_sdnin": [
    { "stk_cd": "005930", "sdnin_rt": "350.5" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| trde_qty_sdnin[].stk_cd | string | 종목코드 |
| trde_qty_sdnin[].sdnin_rt | string | 급증률(%) |

**연속조회**: 지원  
**수정 위치**: `strategy_10_new_high.py` → `data.get("trde_qty_sdnin", [])`

---

### ka10027 — 전일대비 등락률 상위

**파일**: `strategy_12_closing.py`  
**엔드포인트**: `POST /api/dostk/rkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "001",
  "sort_tp": "1",
  "trde_qty_cnd": "0010",
  "stk_cnd": "1",
  "crd_cnd": "0",
  "updown_incls": "0",
  "pric_cnd": "8",
  "trde_prica_cnd": "10",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | 시장구분 |
| sort_tp | string | "1"=등락률 오름차순 |
| trde_qty_cnd | string | "0010"=100만주 이상 |
| stk_cnd | string | "1"=관리종목 제외 |
| pric_cnd | string | "8"=1000원 이상 |
| trde_prica_cnd | string | "10"=10억 이상 |

**응답 바디 (사용 필드)**
```json
{
  "pred_pre_flu_rt_upper": [
    {
      "stk_cd": "005930",
      "cur_prc": "75000",
      "flu_rt": "3.5",
      "cntr_str": "120.5",
      "now_trde_qty": "1500000",
      "sel_req": "50000",
      "buy_req": "80000"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| pred_pre_flu_rt_upper[].stk_cd | string | 종목코드 |
| pred_pre_flu_rt_upper[].cur_prc | string | 현재가 |
| pred_pre_flu_rt_upper[].flu_rt | string | 등락률(%) |
| pred_pre_flu_rt_upper[].cntr_str | string | 체결강도 |
| pred_pre_flu_rt_upper[].now_trde_qty | string | 현재 거래량 |
| pred_pre_flu_rt_upper[].sel_req | string | 매도 잔량 |
| pred_pre_flu_rt_upper[].buy_req | string | 매수 잔량 |

**연속조회**: 지원 (max_pages=2)  
**수정 위치**: `strategy_12_closing.py` → `data.get("pred_pre_flu_rt_upper", [])`

---

### ka10029 — 예상체결 등락률 상위

**파일**: `strategy_1_gap_opening.py`, `strategy_7_auction.py`  
**엔드포인트**: `POST /api/dostk/rkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "001",
  "sort_tp": "1",
  "trde_qty_cnd": "10",
  "stk_cnd": "1",
  "crd_cnd": "0",
  "pric_cnd": "8",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | 시장구분 |
| sort_tp | string | "1"=등락률 오름차순 |
| trde_qty_cnd | string | "10"=1천만주 이상 |
| stk_cnd | string | "1"=관리종목 제외 |
| crd_cnd | string | "0"=전체 |
| pric_cnd | string | "8"=1000원 이상 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "exp_cntr_flu_rt_upper": [
    { "stk_cd": "005930", "flu_rt": "5.2" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| exp_cntr_flu_rt_upper[].stk_cd | string | 종목코드 |
| exp_cntr_flu_rt_upper[].flu_rt | string | 예상 등락률(%) |

**연속조회**: 지원  
**수정 위치**: `strategy_1_gap_opening.py`, `strategy_7_auction.py` → `data.get("exp_cntr_flu_rt_upper", [])`

---

### ka10033 — 신용비율 상위

**파일**: `strategy_7_auction.py`  
**엔드포인트**: `POST /api/dostk/rkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "001",
  "trde_qty_tp": "0",
  "stk_cnd": "1",
  "updown_incls": "1",
  "crd_cnd": "0",
  "stex_tp": "1"
}
```

**응답 바디 (사용 필드)**
```json
{
  "crd_rt_upper": [
    { "stk_cd": "005930", "crd_rt": "5.3" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| crd_rt_upper[].stk_cd | string | 종목코드 |
| crd_rt_upper[].crd_rt | string | 신용비율(%) |

**수정 위치**: `strategy_7_auction.py` → `data.get("crd_rt_upper", [])`

---

### ka10035 — 외인 연속 순매매 상위

**파일**: `strategy_11_frgn_cont.py`  
**엔드포인트**: `POST /api/dostk/rkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "001",
  "trde_tp": "2",
  "base_dt_tp": "1",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | 시장구분 |
| trde_tp | string | "2"=연속 순매수 |
| base_dt_tp | string | "1"=전일 기준 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "for_cont_nettrde_upper": [
    {
      "stk_cd": "005930",
      "cur_prc": "75000",
      "dm1": "500000",
      "dm2": "300000",
      "dm3": "200000",
      "tot": "1000000",
      "limit_exh_rt": "35.2"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| for_cont_nettrde_upper[].stk_cd | string | 종목코드 |
| for_cont_nettrde_upper[].cur_prc | string | 현재가 |
| for_cont_nettrde_upper[].dm1 | string | D-1 순매수량 |
| for_cont_nettrde_upper[].dm2 | string | D-2 순매수량 |
| for_cont_nettrde_upper[].dm3 | string | D-3 순매수량 |
| for_cont_nettrde_upper[].tot | string | 누적 순매수량 |
| for_cont_nettrde_upper[].limit_exh_rt | string | 한도 소진율(%) |

**연속조회**: 지원 (max_pages=2)  
**수정 위치**: `strategy_11_frgn_cont.py` → `data.get("for_cont_nettrde_upper", [])`

---

### ka10044 — 전일 기관 순매매

**파일**: `strategy_5_program_buy.py` → `check_extra_conditions()`  
**엔드포인트**: `POST /api/dostk/mrkcond`

**요청 바디**
```json
{
  "strt_dt": "20260402",
  "end_dt": "20260402",
  "trde_tp": "2",
  "mrkt_tp": "001",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| strt_dt | string | 시작일 (YYYYMMDD) |
| end_dt | string | 종료일 (YYYYMMDD) |
| trde_tp | string | "2"=순매수 |
| mrkt_tp | string | 시장구분 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "daly_orgn_trde_stk": [
    { "stk_cd": "005930" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| daly_orgn_trde_stk[].stk_cd | string | 기관 순매수 종목코드 |

**수정 위치**: `strategy_5_program_buy.py:check_extra_conditions()` → `inst_data.get("daly_orgn_trde_stk", [])`

---

### ka10046 — 체결강도 추이 시간별

**파일**: `http_utils.py` → `fetch_cntr_strength()`  
**엔드포인트**: `POST /api/dostk/mrkcond`

**요청 바디**
```json
{
  "stk_cd": "005930",
  "stex_tp": "1"
}
```

**응답 바디 (사용 필드)**
```json
{
  "cntr_str_tm": [
    { "cntr_str": "125.3" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| cntr_str_tm[].cntr_str | string | 체결강도 (최근 5개 평균) |

**수정 위치**: `http_utils.py:fetch_cntr_strength()` → `data.get("cntr_str_tm", [])`

---

### ka10055 — 당일전일 체결량 비교

**파일**: `strategy_3_inst_foreign.py` → `fetch_volume_compare()`  
**엔드포인트**: `POST /api/dostk/stkinfo`

**요청 바디**
```json
{
  "stk_cd": "005930",
  "tdy_pred": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| stk_cd | string | 종목코드 |
| tdy_pred | string | "1"=당일, "2"=전일 |

**응답 바디 (사용 필드)**
```json
{
  "tdy_pred_cntr_qty": [
    { "cntr_tm": "091530", "cntr_qty": "+150000" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| tdy_pred_cntr_qty[].cntr_tm | string | 체결시각 (HHMMSS) |
| tdy_pred_cntr_qty[].cntr_qty | string | 체결량 (부호 포함, 절대값 사용) |

> **주의**: `cntr_qty` 는 매도(-)/매수(+) 부호 포함. `abs(int(...replace("+",...).replace("-","")))` 로 처리.

**연속조회**: 지원  
**수정 위치**: `strategy_3_inst_foreign.py:fetch_volume_compare()` → `data.get("tdy_pred_cntr_qty", [])`

---

### ka10063 — 장중 투자자별 매매

**파일**: `strategy_3_inst_foreign.py`, `strategy_12_closing.py`  
**엔드포인트**: `POST /api/dostk/mrkcond`

**요청 바디**
```json
{
  "mrkt_tp": "001",
  "amt_qty_tp": "1",
  "invsr": "6",
  "frgn_all": "1",
  "smtm_netprps_tp": "1",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | 시장구분 |
| amt_qty_tp | string | "1"=금액&수량 |
| invsr | string | "6"=외국인 |
| frgn_all | string | "1"=외국계 전체 |
| smtm_netprps_tp | string | "1"=외인+기관 동시 순매수 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "opmr_invsr_trde": [
    { "stk_cd": "005930", "net_buy_amt": "5000000000", "stk_nm": "삼성전자" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| opmr_invsr_trde[].stk_cd | string | 종목코드 |
| opmr_invsr_trde[].net_buy_amt | string | 순매수 금액(원) |
| opmr_invsr_trde[].stk_nm | string | 종목명 |

**연속조회**: 지원  
**수정 위치**: `strategy_3_inst_foreign.py:fetch_intraday_investor()` → `data.get("opmr_invsr_trde", [])`

---

### ka10080 — 주식 분봉 차트

**파일**: `strategy_4_big_candle.py`, `strategy_5_program_buy.py`, `strategy_15_momentum_align.py`  
**엔드포인트**: `POST /api/dostk/chart`

**요청 바디**
```json
{
  "stk_cd": "005930",
  "tic_scope": "5",
  "upd_stkpc_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| stk_cd | string | 종목코드 |
| tic_scope | string | "1"=1분, "5"=5분, "10"=10분, "30"=30분, "60"=60분 |
| upd_stkpc_tp | string | "1"=수정주가 반영 |

**응답 바디 (사용 필드)**
```json
{
  "stk_min_pole_chart_qry": [
    {
      "open_pric": "74500",
      "high_pric": "75500",
      "low_pric": "74000",
      "cur_prc": "75000",
      "trde_qty": "250000"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| stk_min_pole_chart_qry[].open_pric | string | 시가 |
| stk_min_pole_chart_qry[].high_pric | string | 고가 |
| stk_min_pole_chart_qry[].low_pric | string | 저가 |
| stk_min_pole_chart_qry[].cur_prc | string | 종가(현재가) |
| stk_min_pole_chart_qry[].trde_qty | string | 거래량 |

> **배열 순서**: index 0 = 가장 최근 봉 (역순)

**수정 위치**: `strategy_4_big_candle.py` → `data.get("stk_min_pole_chart_qry", [])`

---

### ka10081 — 주식 일봉 차트

**파일**: `strategy_8,9,10,13,14,15`, `ma_utils.py`, `indicator_*.py`  
**엔드포인트**: `POST /api/dostk/chart`

**요청 바디**
```json
{
  "stk_cd": "005930",
  "base_dt": "20260403",
  "upd_stkpc_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| stk_cd | string | 종목코드 |
| base_dt | string | 기준일 (YYYYMMDD), 빈값=오늘 |
| upd_stkpc_tp | string | "1"=수정주가 반영 |

**응답 바디 (사용 필드)**
```json
{
  "stk_dt_pole_chart_qry": [
    {
      "dt": "20260403",
      "open_pric": "74500",
      "high_pric": "75500",
      "low_pric": "74000",
      "cur_prc": "75000",
      "trde_qty": "8500000"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| stk_dt_pole_chart_qry[].dt | string | 날짜 (YYYYMMDD) |
| stk_dt_pole_chart_qry[].open_pric | string | 시가 |
| stk_dt_pole_chart_qry[].high_pric | string | 고가 |
| stk_dt_pole_chart_qry[].low_pric | string | 저가 |
| stk_dt_pole_chart_qry[].cur_prc | string | 종가(현재가) |
| stk_dt_pole_chart_qry[].trde_qty | string | 거래량 |

> **배열 순서**: index 0 = 가장 최근 봉 (역순)  
> **연속조회**: 120봉 이상 필요 시 `cont-yn`/`next-key` 헤더로 페이징

**수정 위치**: `ma_utils.py:fetch_daily_candles()` → `data.get("stk_dt_pole_chart_qry", [])`

---

### ka10131 — 기관외국인 연속매매

**파일**: `strategy_3_inst_foreign.py` → `fetch_continuous_netbuy()`  
**엔드포인트**: `POST /api/dostk/frgnistt`

**요청 바디**
```json
{
  "dt": "3",
  "mrkt_tp": "001",
  "netslmt_tp": "2",
  "stk_inds_tp": "0",
  "amt_qty_tp": "0",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| dt | string | 연속 일수 (예: "3") |
| mrkt_tp | string | 시장구분 |
| netslmt_tp | string | "2"=순매수 |
| stk_inds_tp | string | "0"=전체 업종 |
| amt_qty_tp | string | "0"=수량 기준 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "orgn_frgnr_cont_trde_prst": [
    { "stk_cd": "005930", "tot_cont_netprps_dys": "+5" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| orgn_frgnr_cont_trde_prst[].stk_cd | string | 종목코드 |
| orgn_frgnr_cont_trde_prst[].tot_cont_netprps_dys | string | 연속 순매수 일수 (부호 포함) |

> **주의**: `tot_cont_netprps_dys`에 `+` 부호 포함 → `int(raw.replace("+","").replace(",",""))` 처리

**연속조회**: 지원  
**수정 위치**: `strategy_3_inst_foreign.py:fetch_continuous_netbuy()` → `data.get("orgn_frgnr_cont_trde_prst", [])`

---

### ka90001 — 테마 그룹별 상위 수익률

**파일**: `strategy_6_theme.py`  
**엔드포인트**: `POST /api/dostk/thme`

**요청 바디**
```json
{
  "qry_tp": "1",
  "date_tp": "1",
  "flu_pl_amt_tp": "3",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| qry_tp | string | "1"=테마 조회 |
| date_tp | string | "1"=당일 |
| flu_pl_amt_tp | string | "3"=등락률 상위 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "thema_grp": [
    { "thema_grp_cd": "001", "thema_nm": "2차전지", "flu_rt": "4.2" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| thema_grp[].thema_grp_cd | string | 테마 그룹 코드 |
| thema_grp[].thema_nm | string | 테마명 |
| thema_grp[].flu_rt | string | 테마 등락률(%) |

**연속조회**: 지원  
**수정 위치**: `strategy_6_theme.py` → `data.get("thema_grp", [])`

---

### ka90002 — 테마 구성 종목

**파일**: `strategy_6_theme.py`  
**엔드포인트**: `POST /api/dostk/thme`

**요청 바디**
```json
{
  "date_tp": "1",
  "thema_grp_cd": "001",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| date_tp | string | "1"=당일 |
| thema_grp_cd | string | 테마 그룹 코드 (ka90001 응답값) |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "thema_comp_stk": [
    { "stk_cd": "005930", "flu_rt": "5.2", "stk_nm": "삼성전자" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| thema_comp_stk[].stk_cd | string | 종목코드 |
| thema_comp_stk[].flu_rt | string | 종목 등락률(%) |
| thema_comp_stk[].stk_nm | string | 종목명 |

**수정 위치**: `strategy_6_theme.py` → `data.get("thema_comp_stk", [])`

---

### ka90003 — 프로그램 순매수 상위 50

**파일**: `strategy_5_program_buy.py` → `fetch_program_netbuy()`  
**엔드포인트**: `POST /api/dostk/stkinfo`

**요청 바디**
```json
{
  "trde_upper_tp": "2",
  "amt_qty_tp": "1",
  "mrkt_tp": "P00101",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| trde_upper_tp | string | "2"=순매수 상위 |
| amt_qty_tp | string | "1"=금액 기준 |
| mrkt_tp | string | "P00101"=코스피, "P10102"=코스닥 |
| stex_tp | string | "1"=KRX |

> **주의**: `mrkt_tp` 형식이 다른 API와 다름 (`P00101`/`P10102`). 코드 내 `market_map` dict 참고.

**응답 바디 (사용 필드)**
```json
{
  "prm_netprps_upper_50": [
    { "stk_cd": "005930", "prm_netprps_amt": "12500000000" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| prm_netprps_upper_50[].stk_cd | string | 종목코드 |
| prm_netprps_upper_50[].prm_netprps_amt | string | 프로그램 순매수 금액(원) |

**연속조회**: 지원  
**수정 위치**: `strategy_5_program_buy.py:fetch_program_netbuy()` → `data.get("prm_netprps_upper_50", [])`

---

### ka90009 — 외국인기관 매매 상위

**파일**: `strategy_5_program_buy.py` → `fetch_frgn_inst_upper()`  
**엔드포인트**: `POST /api/dostk/rkinfo`

**요청 바디**
```json
{
  "mrkt_tp": "001",
  "amt_qty_tp": "1",
  "qry_dt_tp": "0",
  "stex_tp": "1"
}
```

| 필드 | 타입 | 값/설명 |
|------|------|---------|
| mrkt_tp | string | "001"=코스피, "101"=코스닥 |
| amt_qty_tp | string | "1"=금액 기준 |
| qry_dt_tp | string | "0"=당일 |
| stex_tp | string | "1"=KRX |

**응답 바디 (사용 필드)**
```json
{
  "frgnr_orgn_trde_upper": [
    { "for_netprps_stk_cd": "005930" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| frgnr_orgn_trde_upper[].for_netprps_stk_cd | string | 외인 순매수 종목코드 |

**연속조회**: 지원  
**수정 위치**: `strategy_5_program_buy.py:fetch_frgn_inst_upper()` → `x.get("for_netprps_stk_cd")`

---

## Rate Limiting 참고

| 항목 | 값 |
|------|----|
| Kiwoom API 한도 | 초당 약 5회 |
| `KIWOOM_API_INTERVAL` | 0.25초 (기본값) |
| `MAX_CONCURRENT_STRATEGIES` | 3개 동시 실행 |
| S3 per-stock 호출 | ka10055 × 2 (당일+전일) — 최대 10종목 = 20회 |
| S5 per-stock 호출 | ka10044 + ka10080 — 최대 15종목 = 30회 |

> 429 응답 발생 시 `KIWOOM_API_INTERVAL`을 `0.5` 이상으로 늘리거나  
> 각 전략의 종목 상한값(`:10`, `:15`)을 줄이세요.

---

## 엔드포인트별 사용 API 요약

| 엔드포인트 | 사용 API ID |
|-----------|------------|
| /api/dostk/stkinfo | ka10001, ka10016, ka10055, ka90003 |
| /api/dostk/rkinfo | ka10023, ka10027, ka10029, ka10033, ka10035, ka90009 |
| /api/dostk/mrkcond | ka10044, ka10046, ka10063 |
| /api/dostk/chart | ka10080, ka10081 |
| /api/dostk/frgnistt | ka10131 |
| /api/dostk/thme | ka90001, ka90002 |
