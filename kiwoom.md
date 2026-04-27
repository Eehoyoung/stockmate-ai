```
import asyncio
import websockets
import json

SOCKET_URL = 'wss://mockapi.kiwoom.com:10000/api/dostk/websocket'  # 모의투자 WebSocket URL
ACCESS_TOKEN = '발급받은_접근_토큰'  # 실제 발급받은 토큰으로 교체

async def connect_and_login():
    async with websockets.connect(SOCKET_URL) as websocket:
        # 로그인 패킷 전송
        login_packet = {
            'trnm': 'LOGIN',
            'token': ACCESS_TOKEN
        }
        await websocket.send(json.dumps(login_packet))
        print("로그인 패킷 전송 완료")

        # 로그인 응답 수신
        response = await websocket.recv()
        print("서버 응답:", response)

asyncio.run(connect_and_login())
```

📘 설명
WebSocket 접속 후 바로 실시간 데이터 요청이 불가능하며, 먼저 로그인 패킷을 보내야 합니다.
로그인 패킷은 JSON 객체로, 반드시 'trnm'에 'LOGIN', 'token'에 발급받은 접근 토큰을 포함해야 합니다.
로그인 성공 시 서버에서 return_code가 0인 응답을 받으며, 이후 실시간 데이터 등록 요청을 할 수 있습니다.
따라서 URL 접속만으로는 부족하며, 초기 바디값(로그인 패킷)이 반드시 필요합니다.

