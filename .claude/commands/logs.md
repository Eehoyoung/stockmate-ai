Docker Compose 서비스 로그를 스트리밍합니다.

서비스명을 지정하면 해당 서비스만, 생략하면 전체(api-orchestrator, ai-engine, telegram-bot, websocket-listener) 로그를 출력합니다.

사용법:
- `/logs` — 전체 서비스 최근 100줄 + 스트림
- `/logs api-orchestrator` — api-orchestrator만
- `/logs ai-engine` — ai-engine만

인자: $ARGUMENTS

다음 명령을 실행하세요:

인자가 없으면:
```
docker compose logs --tail=100 -f api-orchestrator ai-engine telegram-bot websocket-listener
```

인자에 서비스명이 있으면:
```
docker compose logs --tail=100 -f <서비스명>
```

ERROR/CRITICAL만 보고 싶으면 출력에 grep을 붙이세요:
```
docker compose logs --tail=200 api-orchestrator ai-engine | grep -E '"level":"(ERROR|CRITICAL)"'
```
