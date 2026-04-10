키움 REST API
API 정보
메뉴 위치 국내주식 > 실시간시세 > 주식예상체결(0H)
API 명 주식예상체결
API ID 0H
기본정보
Method POST
운영 도메인 wss://api.kiwoom.com:10000
모의투자 도메인 wss://mockapi.kiwoom.com:10000(KRX만 지원가능)
URL /api/dostk/websocket
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
Body trnm 서비스명 String Y 10 REG : 등록 , REMOVE : 해지
Body grp_no 그룹번호 String Y 4
Body refresh 기존등록유지여부 String Y 1
등록(REG)시
0:기존유지안함 1:기존유지(Default)
0일경우 기존등록한 item/type은 해지, 1일경우 기존등록한
item/type 유지
해지(REMOVE)시 값 불필요
Body data 실시간 등록 리스트 LIST
Body - item 실시간 등록 요소 String N 100 거래소별 종목코드, 업종코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL)
Body - type 실시간 항목 String Y 2 TR 명(0A,0B....)
Response
구분 Element 한글명 Type Require
d
Length Description
Header api-id TR명 String Y 10
Header cont-yn 연속조회여부 String N 1 다음 데이터가 있을시 Y값 전달
Header next-key 연속조회키 String N 50 다음 데이터가 있을시 다음 키값 전달
Body return_code 결과코드 String N
통신결과에대한 코드
(등록,해지요청시에만 값 전송 0:정상,1:오류 , 데이터 실시간
수신시 미전송)
Body return_msg 결과메시지 String N 통신결과에대한메시지
Body trnm 서비스명 String N 등록,해지요청시 요청값 반환 , 실시간수신시 REAL 반환
501 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body data 실시간 등록리스트 LIST N
Body - type 실시간항목 String N TR 명(0A,0B....)
Body - name 실시간 항목명 String N
Body - item 실시간 등록 요소 String N 종목코드
Body - values 실시간 값 리스트 LIST N
Body - - 20 체결시간 String N
Body - - 10 현재가 String N
Body - - 11 전일대비 String N
Body - - 12 등락율 String N
Body - - 15 거래량 String N +는 매수체결, -는 매도체결
Body - - 13 누적거래량 String N
Body - - 25 전일대비기호 String N
Request Example
{
"trnm": "REG",
"grp_no": "1",
"refresh": "1",
"data": [
{
"item": [
"005930"
],
"type": [
"0H"
]
}
]
}
Response Example
#요청
{
'trnm': 'REG',
'return_code': 0,
'return_msg': ''
}
#실시간 수신
{
'data': [
{
'values': {
'20': '110206',
'10': '+60500',
'11': '+200',
'12': '+0.33',
'15': '-7805',
'13': '768293',
'25': '2'
},
'type': '0H',
'name': '주식예상체결',
'item': '005930'
}
],
'trnm': 'REAL'
}
