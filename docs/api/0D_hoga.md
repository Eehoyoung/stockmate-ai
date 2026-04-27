키움 REST API
API 정보
메뉴 위치 국내주식 > 실시간시세 > 주식호가잔량(0D)
API 명 주식호가잔량
API ID 0D
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
483 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body data 실시간 등록리스트 LIST N
Body - type 실시간항목 String N TR 명(0A,0B....)
Body - name 실시간 항목명 String N
Body - item 실시간 등록 요소 String N 종목코드
Body - values 실시간 값 리스트 LIST N
Body - - 21 호가시간 String N
Body - - 41 매도호가1 String N
Body - - 61 매도호가수량1 String N
Body - - 81 매도호가직전대비1 String N
Body - - 51 매수호가1 String N
Body - - 71 매수호가수량1 String N
Body - - 91 매수호가직전대비1 String N
Body - - 42 매도호가2 String N
Body - - 62 매도호가수량2 String N
Body - - 82 매도호가직전대비2 String N
Body - - 52 매수호가2 String N
Body - - 72 매수호가수량2 String N
Body - - 92 매수호가직전대비2 String N
Body - - 43 매도호가3 String N
Body - - 63 매도호가수량3 String N
Body - - 83 매도호가직전대비3 String N
Body - - 53 매수호가3 String N
Body - - 73 매수호가수량3 String N
Body - - 93 매수호가직전대비3 String N
Body - - 44 매도호가4 String N
Body - - 64 매도호가수량4 String N
Body - - 84 매도호가직전대비4 String N
Body - - 54 매수호가4 String N
Body - - 74 매수호가수량4 String N
Body - - 94 매수호가직전대비4 String N
Body - - 45 매도호가5 String N
Body - - 65 매도호가수량5 String N
Body - - 85 매도호가직전대비5 String N
Body - - 55 매수호가5 String N
Body - - 75 매수호가수량5 String N
Body - - 95 매수호가직전대비5 String N
Body - - 46 매도호가6 String N
484 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body - - 66 매도호가수량6 String N
Body - - 86 매도호가직전대비6 String N
Body - - 56 매수호가6 String N
Body - - 76 매수호가수량6 String N
Body - - 96 매수호가직전대비6 String N
Body - - 47 매도호가7 String N
Body - - 67 매도호가수량7 String N
Body - - 87 매도호가직전대비7 String N
Body - - 57 매수호가7 String N
Body - - 77 매수호가수량7 String N
Body - - 97 매수호가직전대비7 String N
Body - - 48 매도호가8 String N
Body - - 68 매도호가수량8 String N
Body - - 88 매도호가직전대비8 String N
Body - - 58 매수호가8 String N
Body - - 78 매수호가수량8 String N
Body - - 98 매수호가직전대비8 String N
Body - - 49 매도호가9 String N
Body - - 69 매도호가수량9 String N
Body - - 89 매도호가직전대비9 String N
Body - - 59 매수호가9 String N
Body - - 79 매수호가수량9 String N
Body - - 99 매수호가직전대비9 String N
Body - - 50 매도호가10 String N
Body - - 70 매도호가수량10 String N
Body - - 60 매수호가10 String N
Body - - 90 매도호가직전대비10 String N
Body - - 80 매수호가수량10 String N
Body - - 100 매수호가직전대비10 String N
Body - - 121 매도호가총잔량 String N
Body - - 122 매도호가총잔량직전
대비 String N
Body - - 125 매수호가총잔량 String N
Body - - 126 매수호가총잔량직전
대비 String N
Body - - 23 예상체결가 String N
Body - - 24 예상체결수량 String N
Body - - 128 순매수잔량 String N
485 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body - - 129 매수비율 String N
Body - - 138 순매도잔량 String N
Body - - 139 매도비율 String N
Body - - 200 예상체결가전일종가
대비 String N
Body - - 201 예상체결가전일종가
대비등락율 String N
Body - - 238 예상체결가전일종가
대비기호 String N
Body - - 291 예상체결가 String N 예상체결 시간동안에만 유효한 값
Body - - 292 예상체결량 String N
Body - - 293 예상체결가전일대비
기호 String N
Body - - 294 예상체결가전일대비 String N
Body - - 295 예상체결가전일대비
등락율 String N
Body - - 621 LP매도호가수량1 String N
Body - - 631 LP매수호가수량1 String N
Body - - 622 LP매도호가수량2 String N
Body - - 632 LP매수호가수량2 String N
Body - - 623 LP매도호가수량3 String N
Body - - 633 LP매수호가수량3 String N
Body - - 624 LP매도호가수량4 String N
Body - - 634 LP매수호가수량4 String N
Body - - 625 LP매도호가수량5 String N
Body - - 635 LP매수호가수량5 String N
Body - - 626 LP매도호가수량6 String N
Body - - 636 LP매수호가수량6 String N
Body - - 627 LP매도호가수량7 String N
Body - - 637 LP매수호가수량7 String N
Body - - 628 LP매도호가수량8 String N
Body - - 638 LP매수호가수량8 String N
Body - - 629 LP매도호가수량9 String N
Body - - 639 LP매수호가수량9 String N
Body - - 630 LP매도호가수량10 String N
Body - - 640 LP매수호가수량10 String N
Body - - 13 누적거래량 String N
Body - - 299 전일거래량대비예상
체결율 String N
Body - - 215 장운영구분 String N
486 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body - - 216 투자자별ticker String N
Body - - 6044 KRX 매도호가잔량1 String N
Body - - 6045 KRX 매도호가잔량2 String N
Body - - 6046 KRX 매도호가잔량3 String N
Body - - 6047 KRX 매도호가잔량4 String N
Body - - 6048 KRX 매도호가잔량5 String N
Body - - 6049 KRX 매도호가잔량6 String N
Body - - 6050 KRX 매도호가잔량7 String N
Body - - 6051 KRX 매도호가잔량8 String N
Body - - 6052 KRX 매도호가잔량9 String N
Body - - 6053 KRX 매도호가잔량10 String N
Body - - 6054 KRX 매수호가잔량1 String N
Body - - 6055 KRX 매수호가잔량2 String N
Body - - 6056 KRX 매수호가잔량3 String N
Body - - 6057 KRX 매수호가잔량4 String N
Body - - 6058 KRX 매수호가잔량5 String N
Body - - 6059 KRX 매수호가잔량6 String N
Body - - 6060 KRX 매수호가잔량7 String N
Body - - 6061 KRX 매수호가잔량8 String N
Body - - 6062 KRX 매수호가잔량9 String N
Body - - 6063 KRX 매수호가잔량10 String N
Body - - 6064 KRX 매도호가총잔량 String N
Body - - 6065 KRX 매수호가총잔량 String N
Body - - 6066 NXT 매도호가잔량1 String N
Body - - 6067 NXT 매도호가잔량2 String N
Body - - 6068 NXT 매도호가잔량3 String N
Body - - 6069 NXT 매도호가잔량4 String N
Body - - 6070 NXT 매도호가잔량5 String N
Body - - 6071 NXT 매도호가잔량6 String N
Body - - 6072 NXT 매도호가잔량7 String N
Body - - 6073 NXT 매도호가잔량8 String N
Body - - 6074 NXT 매도호가잔량9 String N
Body - - 6075 NXT 매도호가잔량10 String N
Body - - 6076 NXT 매수호가잔량1 String N
Body - - 6077 NXT 매수호가잔량2 String N
Body - - 6078 NXT 매수호가잔량3 String N
Body - - 6079 NXT 매수호가잔량4 String N
487 / 528
Response
구분 Element 한글명 Type Require
d
Length Description
Body - - 6080 NXT 매수호가잔량5 String N
Body - - 6081 NXT 매수호가잔량6 String N
Body - - 6082 NXT 매수호가잔량7 String N
Body - - 6083 NXT 매수호가잔량8 String N
Body - - 6084 NXT 매수호가잔량9 String N
Body - - 6085 NXT 매수호가잔량10 String N
Body - - 6086 NXT 매도호가총잔량 String N
Body - - 6087 NXT 매수호가총잔량 String N
Body - - 6100 KRX 중간가 매도
총잔량 증감 String N
Body - - 6101 KRX 중간가 매도
총잔량 String N
Body - - 6102 KRX 중간가 String N
Body - - 6103 KRX 중간가 매수
총잔량 String N
Body - - 6104 KRX 중간가 매수
총잔량 증감 String N
Body - - 6105 NXT중간가 매도
총잔량 증감 String N
Body - - 6106 NXT중간가 매도
총잔량 String N
Body - - 6107 NXT중간가 String N
Body - - 6108 NXT중간가 매수
총잔량 String N
Body - - 6109 NXT중간가 매수
총잔량 증감 String N
Body - - 6110 KRX중간가대비 String N 기준가대비
Body - - 6111 KRX중간가대비 기호 String N 기준가대비
Body - - 6112 KRX중간가대비등락
율
String N 기준가대비
Body - - 6113 NXT중간가대비 String N 기준가대비
Body - - 6114 NXT중간가대비 기호 String N 기준가대비
Body - - 6115 NXT중간가대비등락
율
String N 기준가대비
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
"0D"
]
}
]
488 / 528
Request Example
}
Response Example
#요청 {
'trnm': 'REG',
'return_code': 0,
'return_msg': '' }
#실시간 수신 {
'trnm': 'REAL',
'data': [
{
'type': '0D',
'name': '주식호가잔량',
'item': '005930',
'values': {
'21': '165207',
'41': '-20800',
'61': '82',
'81': '0',
'51': '-20700',
'71': '23847',
'91': '0',
'42': '+20900',
'62': '393',
'82': '0',
'52': '-20650',
'72': '834748',
'92': '0',
'43': '+21000',
'63': '674739',
'83': '0',
'53': '-20600',
'73': '2145799',
'93': '0',
'44': '+21050',
'64': '2055055',
'84': '0',
'54': '-20550',
'74': '2134689',
'94': '0',
'45': '+21100',
'65': '1998461',
'85': '0',
'55': '-20500',
'75': '1982298',
'95': '0',
'46': '+21150',
'66': '1932347',
'86': '0',
'56': '-20450',
'76': '1853788',
'96': '0',
'47': '+21200',
'67': '1723333',
'87': '0',
'57': '-20400',
'77': '1687992',
'97': '0',
'48': '+21250',
'68': '1621835',
'88': '0',
'58': '-20350',
'78': '1467869',
'98': '0',
'49': '+21300',
'69': '1373291',
'89': '0',
'59': '-20300',
'79': '1259995',
'99': '0',
'50': '+21350',
'70': '1242991',
'90': '0',
'60': '-20250',
489 / 528
Response Example
'80': '1062405',
'100': '0',
'121': '12622527',
'122': '-1036021',
'125': '14453430',
'126': '+1062126',
'23': '20850',
'24': '332941',
'128': '+1830903',
'129': '114.51',
'138': '-1830903',
'139': '87.33',
'200': '0',
'201': '0.00',
'238': '3',
'291': '0',
'292': '0',
'293': '3',
'294': '0',
'295': '0.00',
'621': '0',
'631': '0',
'622': '0',
'632': '0',
'623': '0',
'633': '0',
'624': '0',
'634': '0',
'625': '0',
'635': '0',
'626': '0',
'636': '0',
'627': '0',
'637': '0',
'628': '0',
'638': '0',
'629': '0',
'639': '0',
'630': '0',
'640': '0',
'13': '30379650',
'299': '-1.06',
'215': '',
'216': '',
'6044':'0',
'6045':'0',
'6046':'0',
'6047':'0',
'6048':'0',
'6049':'0',
'6050':'0',
'6051':'0',
'6052':'0',
'6053':'0',
'6054':'0',
'6055':'0',
'6056':'0',
'6057':'0',
'6058':'0',
'6059':'0',
'6060':'0',
'6061':'0',
'6062':'0',
'6063':'0',
'6064':'0',
'6065':'0',
'6066':'0',
'6067':'0',
'6068':'0',
'6069':'0',
'6070':'0',
'6071':'0',
'6072':'0',
'6073':'0',
'6074':'0',
'6075':'0',
'6076':'0',
'6077':'0',
'6078':'0',
490 / 528
Response Example
'6079':'0',
'6080':'0',
'6081':'0',
'6082':'0',
'6083':'0',
'6084':'0',
'6085':'0',
'6086':'0',
'6087':'0',
'6100':'0',
'6101':'0',
'6102':'0',
'6103':'0',
'6104':'0',
'6105':'0',
'6106':'0',
'6107':'0',
'6108':'0',
'6109':'0',
'6110':'0',
'6111':'0',
'6112':'0',
'6113':'0',
'6114':'0',
'6115':'0'
}
}
]
}
