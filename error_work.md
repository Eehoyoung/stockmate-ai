C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai\.venv\Scripts\python.exe C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/ai-engine/engine.py
2026-03-31 23:48:13,697 [INFO] engine – ==================================================
2026-03-31 23:48:13,697 [INFO] engine –   StockMate AI – AI Engine 시작
2026-03-31 23:48:13,697 [INFO] engine –   Claude 모델: claude-sonnet-4-20250514
2026-03-31 23:48:13,698 [INFO] engine – ==================================================
2026-03-31 23:48:13,707 [INFO] engine – [Redis] 연결 성공 → localhost:6379
2026-03-31 23:48:13,707 [INFO] engine – [Engine] AI Engine ready – telegram_queue 폴링 시작
2026-03-31 23:48:13,707 [INFO] engine – [Engine] Human Confirm Gate 활성화 (ENABLE_CONFIRM_GATE=true)
2026-03-31 23:48:13,707 [INFO] engine – [Engine] 전술 스캐너 활성화 (ENABLE_STRATEGY_SCANNER=true)
2026-03-31 23:48:13,707 [INFO] engine – [Engine] 뉴스 스케쥴러 활성화 (NEWS_ENABLED=true, 주기=30min)
2026-03-31 23:48:13,707 [INFO] engine – [Engine] 데이터 품질 모니터링 활성화 (ENABLE_MONITOR=true, 주기=60s)
2026-03-31 23:48:13,707 [INFO] engine – [Engine] 오버나잇 평가 워커 활성화 (ENABLE_OVERNIGHT_WORKER=true)
2026-03-31 23:48:13,707 [INFO] queue_worker – [Worker] 큐 워커 시작 (poll_interval=2.0s)
2026-03-31 23:48:13,708 [INFO] confirm_worker – [ConfirmWorker] 시작
2026-03-31 23:48:13,708 [INFO] strategy_runner – [Runner] 전술 스캐너 시작 (interval=60s)
2026-03-31 23:48:13,708 [INFO] strategy_runner – [Runner] Telegram 직접 알림 활성화 (dry_run=False)
2026-03-31 23:48:13,708 [INFO] news_scheduler – [NewsScheduler] 시작 – 주기=30분 허용시간=월~금 08:30~16:00
2026-03-31 23:48:13,709 [INFO] news_scheduler – [NewsScheduler] 장외 시간 – 시작 시 실행 건너뜀
2026-03-31 23:48:13,709 [INFO] monitor_worker – [Monitor] 데이터 품질 모니터링 시작 (interval=60s)
2026-03-31 23:48:13,709 [INFO] overnight_worker – [OvernightWorker] 시작 (poll=2.0s)
2026-03-31 23:48:13,710 [INFO] engine – [Health] AI Engine 헬스체크 서버 시작 → http://localhost:8082/health
2026-04-01 08:30:18,105 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:30:18,494 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:31:18,875 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:31:19,281 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:32:19,668 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:32:20,057 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:33:20,449 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:33:20,862 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:34:21,266 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:34:21,659 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:35:22,056 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:35:22,461 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:36:22,867 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:36:23,256 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:37:23,661 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:37:24,053 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:38:24,441 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:38:24,828 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:39:25,236 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:39:25,625 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:40:26,052 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:40:26,441 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:41:26,835 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:41:27,206 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:42:27,612 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:42:28,007 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:43:28,415 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:43:28,805 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:44:29,209 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:44:29,603 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:45:30,007 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:45:30,391 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:46:30,804 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:46:31,217 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:47:31,611 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:47:32,008 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:48:13,251 [INFO] news_scheduler – [NewsScheduler] 뉴스 수집 시작
2026-04-01 08:48:13,622 [WARNING] news_collector – [NewsCollector] 수집 실패 (naver_finance): [Errno 11001] getaddrinfo failed
2026-04-01 08:48:13,649 [INFO] httpx – HTTP Request: GET https://www.hankyung.com/feed/all-news "HTTP/1.1 200 OK"
2026-04-01 08:48:13,706 [INFO] httpx – HTTP Request: GET https://www.mk.co.kr/rss/30000001/ "HTTP/1.1 200 OK"
2026-04-01 08:48:13,731 [INFO] httpx – HTTP Request: GET https://www.yna.co.kr/rss/economy.xml "HTTP/1.1 200 OK"
2026-04-01 08:48:13,771 [INFO] news_collector – [NewsCollector] 수집 완료 – 전체=220건 신규=220건 반환=30건
2026-04-01 08:48:14,612 [INFO] httpx – HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 401 Unauthorized"
2026-04-01 08:48:14,613 [WARNING] news_analyzer – [NewsAnalyzer] Claude API 오류: Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}, 'request_id': 'req_011CZc3xWnazrRQmSv7mN56E'} – 폴백 반환
2026-04-01 08:48:14,614 [INFO] news_scheduler – [NewsScheduler] Redis 저장 완료 – control=CONTINUE sectors=[]
2026-04-01 08:48:14,614 [INFO] news_scheduler – [NewsScheduler] 완료 (1.4s) – news=30 control=CONTINUE sentiment=NEUTRAL
2026-04-01 08:48:32,400 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:48:32,790 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:49:33,193 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:49:33,580 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:50:33,975 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:50:34,368 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:51:34,765 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:51:35,166 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:52:35,565 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:52:35,948 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:53:36,361 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:53:36,758 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:54:37,158 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:54:37,558 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:55:37,966 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:55:38,372 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:56:38,775 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:56:39,197 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:57:39,621 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:57:40,034 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:58:40,447 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:58:40,848 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:59:41,257 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
2026-04-01 08:59:41,651 [INFO] httpx – HTTP Request: POST https://api.kiwoom.com/api/dostk/rkinfo "HTTP/1.1 200 OK"
