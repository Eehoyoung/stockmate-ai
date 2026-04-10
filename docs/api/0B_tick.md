키움 REST API
API 정보
메뉴 위치 국내주식 > 실시간시세 > 주식체결(0B)
API 명 주식체결
API ID 0B
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
477 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body data 실시간 등록리스트 LIST N
Body - type 실시간항목 String N TR 명(0B,0B....)
Body - name 실시간 항목명 String N
Body - item 실시간 등록 요소 String N 종목코드
Body - values 실시간 값 리스트 LIST N
Body - - 20 체결시간 String N
Body - - 10 현재가 String N
Body - - 11 전일대비 String N
Body - - 12 등락율 String N
Body - - 27 (최우선)매도호가 String N
Body - - 28 (최우선)매수호가 String N
Body - - 15 거래량 String N +는 매수체결,-는 매도체결
Body - - 13 누적거래량 String N
Body - - 14 누적거래대금 String N
Body - - 16 시가 String N
Body - - 17 고가 String N
Body - - 18 저가 String N
Body - - 25 전일대비기호 String N
Body - - 26 전일거래량대비(계약
,주) String N
Body - - 29 거래대금증감 String N
Body - - 30 전일거래량대비(비율
)
String N
Body - - 31 거래회전율 String N
Body - - 32 거래비용 String N
Body - - 228 체결강도 String N
Body - - 311 시가총액(억) String N
Body - - 290 장구분 String N 1: 장전 시간외 , 2: 장중 , 3: 장후 시간외
Body - - 691 K.O 접근도 String N
Body - - 567 상한가발생시간 String N
Body - - 568 하한가발생시간 String N
Body - - 851 전일 동시간 거래량
비율 String N
Body - - 1890 시가시간 String N
Body - - 1891 고가시간 String N
Body - - 1892 저가시간 String N
Body - - 1030 매도체결량 String N
Body - - 1031 매수체결량 String N
478 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body - - 1032 매수비율 String N
Body - - 1071 매도체결건수 String N
Body - - 1072 매수체결건수 String N
Body - - 1313 순간거래대금 String N
Body - - 1315 매도체결량_단건 String N
Body - - 1316 매수체결량_단건 String N
Body - - 1314 순매수체결량 String N
Body - - 1497 CFD증거금 String N
Body - - 1498 유지증거금 String N
Body - - 620 당일거래평균가 String N
Body - - 732 CFD거래비용 String N
Body - - 852 대주거래비용 String N
Body - - 9081 거래소구분 String N
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
"0B"
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
'trnm': 'REAL',
'data': [
{
'type': '0B',
'name': '주식체결',
'item': '005930',
'values': {
'20': '165208',
'10': '-20800',
'11': '-50',
'12': '-0.24',
'27': '-20800',
'28': '-20700',
'15': '+82',
'13': '30379732',
'14': '632640',
'16': '20850',
'17': '+21150',
'18': '-20450',
'25': '5',
479 / 528
Response Example
'26': '-1057122',
'29': '-22041267850',
'30': '-96.64',
'31': '36.67',
'32': '44',
'228': '98.92',
'311': '17230',
'290': '2',
'691': '0',
'567': '000000',
'568': '000000',
'851': '',
'1890': '',
'1891': '',
'1892': '',
'1030': '',
'1031': '',
'1032': '',
'1071': '',
'1072': '',
'1313': '',
'1315': '',
'1316': '',
'1314': '',
'1497': '',
'1498': '',
'620': '',
'732': '',
'852': '',
'9081': '1'
}
}
]
}
