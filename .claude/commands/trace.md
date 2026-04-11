signal_id 또는 request_id로 전체 모듈 로그를 교차 추적합니다.

사용법:
- `/trace sig-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- `/trace req-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

인자: $ARGUMENTS

인자로 받은 ID를 사용하여 다음을 수행하세요:

1. 모든 서비스 로그에서 해당 ID 검색:
```bash
docker compose logs --tail=1000 api-orchestrator ai-engine telegram-bot websocket-listener 2>&1 | grep "$ARGUMENTS"
```

2. 결과를 타임스탬프(`ts` 필드) 순으로 정렬하여 신호가 어느 단계에서 처리됐는지 흐름을 보여주세요.

3. 흐름 중 빠진 단계가 있으면 어느 모듈에서 누락됐는지 진단하세요:
   - api-orchestrator에서만 보이고 ai-engine에 없음 → telegram_queue 미적재 또는 ai-engine 미실행
   - ai-engine에서만 보이고 telegram-bot에 없음 → ai_scored_queue 미적재 또는 action=CANCEL
   - telegram-bot에서 보이지 않음 → Telegram API 연결 문제

ID가 제공되지 않았으면 최근 ERROR 로그에서 signal_id를 추출해 보여주세요.
