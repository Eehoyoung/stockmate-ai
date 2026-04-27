키움 REST API
API 정보
메뉴 위치 국내주식 > 종목정보 > 프로그램순매수상위50요청(ka90003)
API 명 프로그램순매수상위50요청
API ID ka90003
기본정보
Method POST
운영 도메인 https://api.kiwoom.com
모의투자 도메인 https://mockapi.kiwoom.com(KRX만 지원가능)
URL /api/dostk/stkinfo
Format JSON
Content-Type application/json;charset=UTF-8
개요
Request
구분 Element 한글명 Type Require
d
Length Description
Header api-id TR명 String Y 10
Header authorization 접근토큰 String Y 1000 토큰 지정시 토큰타입("Bearer") 붙혀서 호출
예) Bearer Egicyx...
Header cont-yn 연속조회여부 String N 1
응답 Header의 연속조회여부값이 Y일 경우 다음데이터
요청시 응답 Header의 cont-yn값 세팅
Header next-key 연속조회키 String N 50 응답 Header의 연속조회여부값이 Y일 경우 다음데이터
요청시 응답 Header의 next-key값 세팅
Body trde_upper_tp 매매상위구분 String Y 1 1:순매도상위, 2:순매수상위
Body amt_qty_tp 금액수량구분 String Y 2 1:금액, 2:수량
Body mrkt_tp 시장구분 String Y 10 P00101:코스피, P10102:코스닥
Body stex_tp 거래소구분 String Y 1 1:KRX, 2:NXT 3.통합
Response
구분 Element 한글명 Type Require
d
Length Description
Header api-id TR명 String Y 10
Header cont-yn 연속조회여부 String N 1 다음 데이터가 있을시 Y값 전달
Header next-key 연속조회키 String N 50 다음 데이터가 있을시 다음 키값 전달
Body prm_netprps_upper_
50
프로그램순매수상위
50 LIST N
Body - rank 순위 String N 20
Body - stk_cd 종목코드 String N 20
Body - stk_nm 종목명 String N 40
Body - cur_prc 현재가 String N 20
Body - flu_sig 등락기호 String N 20
Body - pred_pre 전일대비 String N 20
Body - flu_rt 등락율 String N 20
351 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body - acc_trde_qty 누적거래량 String N 20
Body - prm_sell_amt 프로그램매도금액 String N 20
Body - prm_buy_amt 프로그램매수금액 String N 20
Body - prm_netprps_amt 프로그램순매수금액 String N 20
Request Example
{
"trde_upper_tp": "1",
"amt_qty_tp": "1",
"mrkt_tp": "P00101",
"stex_tp": "1"
}
Response Example
{
"prm_trde_trnsn": [
{
"cntr_tm": "170500",
"dfrt_trde_sel": "0",
"dfrt_trde_buy": "0",
"dfrt_trde_netprps": "0",
"ndiffpro_trde_sel": "1",
"ndiffpro_trde_buy": "17",
"ndiffpro_trde_netprps": "+17",
"dfrt_trde_sell_qty": "0",
"dfrt_trde_buy_qty": "0",
"dfrt_trde_netprps_qty": "0",
"ndiffpro_trde_sell_qty": "0",
"ndiffpro_trde_buy_qty": "0",
"ndiffpro_trde_netprps_qty": "+0",
"all_sel": "1",
"all_buy": "17",
"all_netprps": "+17",
"kospi200": "+47839",
"basis": "-146.59"
},
{
"cntr_tm": "170400",
"dfrt_trde_sel": "0",
"dfrt_trde_buy": "0",
"dfrt_trde_netprps": "0",
"ndiffpro_trde_sel": "1",
"ndiffpro_trde_buy": "17",
"ndiffpro_trde_netprps": "+17",
"dfrt_trde_sell_qty": "0",
"dfrt_trde_buy_qty": "0",
"dfrt_trde_netprps_qty": "0",
"ndiffpro_trde_sell_qty": "0",
"ndiffpro_trde_buy_qty": "0",
"ndiffpro_trde_netprps_qty": "+0",
"all_sel": "1",
"all_buy": "17",
"all_netprps": "+17",
"kospi200": "+47839",
"basis": "-146.59"
}
],
"return_code": 0,
"return_msg": "정상적으로 처리되었습니다"
}
