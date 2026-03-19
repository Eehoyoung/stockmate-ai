import asyncio
import json
import os
import websockets
import redis
from dotenv import load_dotenv

load_dotenv()

# Redis 연결 설정
r = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    password=os.getenv('REDIS_PASSWORD'),
    decode_responses=True
)

async def kiwoom_websocket_handler():
    # 1. Redis에서 Java 서비스가 저장한 토큰 획득 [cite: 256-261]
    token = r.get("kiwoom:access_token")
    if not token:
        print("Error: Access Token이 Redis에 없습니다. Java 서버를 먼저 기동하세요.")
        return

    uri = os.getenv('KIWOOM_WS_URL') # wss://api.kiwoom.com:10000 [cite: 78]

    async with websockets.connect(uri) as websocket:
        print(f"Connected to Kiwoom WebSocket: {uri}")

        # 2. ka10171 (목록 조회) 선행 호출 (가이드 필수 사항)
        # ※ 실제 구현 시 API 명세에 따른 JSON 포맷 전송 필요
        init_request = {
            "header": {"token": token, "tr_id": "ka10171"},
            "body": {"custtype": "P"}
        }
        await websocket.send(json.dumps(init_request))

        # 3. 실시간 구독 요청 (예: 고영 098460)
        subscribe_request = {
            "header": {"token": token, "tr_id": "ka10173"}, # 실시간 체결 구독
            "body": {
                "tr_key": "098460", # 종목코드
                "tr_type": "1"      # 등록
            }
        }
        await websocket.send(json.dumps(subscribe_request))

        # 4. 데이터 수신 및 Redis Pub/Sub 전송
        while True:
            data = await websocket.recv()
            message = json.loads(data)

            # AI 엔진이 구독할 수 있도록 Redis Channel에 발행
            # channel name: stock:tick:098460
            r.publish(f"stock:tick:{message.get('code', '098460')}", json.dumps(message))
            print(f"Tick Data Published: {message}")

if __name__ == "__main__":
    try:
        asyncio.run(kiwoom_websocket_handler())
    except KeyboardInterrupt:
        print("Listener stopped by user")
