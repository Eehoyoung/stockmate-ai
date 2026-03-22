2026-03-23T02:39:52.319+09:00  INFO 44352 --- [           main] o.i.a.service.TokenService               : 토큰 발급 완료 - 만료: 2026-03-23T23:47:39
2026-03-23T02:39:52.330+09:00  INFO 44352 --- [           main] o.i.a.ApplicationStartupRunner           : 초기 토큰 발급 완료
2026-03-23T02:39:52.331+09:00  INFO 44352 --- [           main] o.i.a.ApplicationStartupRunner           : 거래 시간 외 - WebSocket 대기 상태
2026-03-23T02:39:52.331+09:00  INFO 44352 --- [           main] o.i.a.ApplicationStartupRunner           : === 시스템 초기화 완료 ===
2026-03-23T02:39:52.722+09:00  INFO 44352 --- [192.168.219.108] o.a.c.c.C.[Tomcat].[localhost].[/]       : Initializing Spring DispatcherServlet 'dispatcherServlet'
2026-03-23T02:39:52.722+09:00  INFO 44352 --- [192.168.219.108] o.s.web.servlet.DispatcherServlet        : Initializing Servlet 'dispatcherServlet'
2026-03-23T02:39:52.723+09:00  INFO 44352 --- [192.168.219.108] o.s.web.servlet.DispatcherServlet        : Completed initialization in 1 ms
2026-03-23T02:41:14.896+09:00  INFO 44352 --- [nio-8080-exec-3] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 시도: wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23T02:41:15.038+09:00  INFO 44352 --- [m.com:10000/...] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 성공
2026-03-23T02:41:17.063+09:00  INFO 44352 --- [nio-8080-exec-3] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=1 type=0B items=1개
2026-03-23T02:41:17.375+09:00  INFO 44352 --- [nio-8080-exec-3] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=2 type=0D items=1개
2026-03-23T02:41:17.680+09:00  INFO 44352 --- [nio-8080-exec-3] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=4 type=1h items=1개
2026-03-23T02:41:17.680+09:00  INFO 44352 --- [nio-8080-exec-3] o.i.a.w.WebSocketSubscriptionManager     : 정규장 구독 완료: 체결=1개, 호가=1개
2026-03-23T02:41:27.700+09:00  INFO 44352 --- [m.com:10000/...] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 종료 code=1000 reason=Bye
2026-03-23T02:41:47.106+09:00  INFO 44352 --- [nio-8080-exec-6] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 시도: wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23T02:41:47.214+09:00  INFO 44352 --- [m.com:10000/...] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 성공
2026-03-23T02:41:49.135+09:00  INFO 44352 --- [nio-8080-exec-6] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=1 type=0B items=1개
2026-03-23T02:41:49.436+09:00  INFO 44352 --- [nio-8080-exec-6] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=2 type=0D items=1개
2026-03-23T02:41:49.737+09:00  INFO 44352 --- [nio-8080-exec-6] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=4 type=1h items=1개
2026-03-23T02:41:49.737+09:00  INFO 44352 --- [nio-8080-exec-6] o.i.a.w.WebSocketSubscriptionManager     : 정규장 구독 완료: 체결=1개, 호가=1개
2026-03-23T02:41:51.069+09:00  WARN 44352 --- [   scheduling-1] o.i.a.scheduler.DataQualityScheduler     : [DataQuality] tick 데이터 누락 1/1 ({:.1f}%) → WS 재연결 시도
2026-03-23T02:41:51.086+09:00 ERROR 44352 --- [ctor-http-nio-5] o.i.a.service.KiwoomApiService           : 4xx 오류 [ka10029] status=429 body={"return_msg":"허용된 요청 개수를 초과하였습니다[1700:허용된 요청 개수를 초과하였습니다. API ID=ka10029]","return_code":5}
2026-03-23T02:41:51.086+09:00  WARN 44352 --- [ctor-http-nio-5] o.i.a.service.KiwoomApiService           : 1700 Rate Limit [ka10029] – 재시도 예정
2026-03-23T02:41:51.099+09:00  WARN 44352 --- [ctor-http-nio-5] o.i.a.service.KiwoomApiService           : API 재시도 [ka10029] attempt=1
2026-03-23T02:41:52.290+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=1 type=0B items=1개
2026-03-23T02:41:52.591+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=2 type=0D items=1개
2026-03-23T02:41:52.892+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=4 type=1h items=1개
2026-03-23T02:41:52.892+09:00  INFO 44352 --- [   scheduling-1] o.i.a.w.WebSocketSubscriptionManager     : 정규장 구독 완료: 체결=1개, 호가=1개
2026-03-23T02:41:52.897+09:00  INFO 44352 --- [   scheduling-1] o.i.a.scheduler.DataQualityScheduler     : [DataQuality] SYSTEM_ALERT 발행: 1건 경고
2026-03-23T02:42:02.906+09:00  INFO 44352 --- [m.com:10000/...] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 종료 code=1000 reason=Bye
2026-03-23T02:42:52.949+09:00  WARN 44352 --- [   scheduling-1] o.i.a.scheduler.DataQualityScheduler     : [DataQuality] tick 데이터 누락 1/1 ({:.1f}%) → WS 재연결 시도
2026-03-23T02:42:52.950+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 시도: wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23T02:42:53.027+09:00  INFO 44352 --- [m.com:10000/...] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 성공
2026-03-23T02:42:54.970+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=1 type=0B items=1개
2026-03-23T02:42:55.272+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=2 type=0D items=1개
2026-03-23T02:42:55.573+09:00  INFO 44352 --- [   scheduling-1] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 구독 등록 grp=4 type=1h items=1개
2026-03-23T02:42:55.573+09:00  INFO 44352 --- [   scheduling-1] o.i.a.w.WebSocketSubscriptionManager     : 정규장 구독 완료: 체결=1개, 호가=1개
2026-03-23T02:42:55.575+09:00  INFO 44352 --- [   scheduling-1] o.i.a.scheduler.DataQualityScheduler     : [DataQuality] SYSTEM_ALERT 발행: 1건 경고
2026-03-23T02:43:05.589+09:00  INFO 44352 --- [m.com:10000/...] o.i.a.websocket.KiwoomWebSocketClient    : WebSocket 연결 종료 code=1000 reason=Bye
2026-03-23T02:43:13.592+09:00  INFO 44352 --- [ionShutdownHook] o.s.boot.tomcat.GracefulShutdown         : Commencing graceful shutdown. Waiting for active requests to complete
2026-03-23T02:43:13.600+09:00  INFO 44352 --- [tomcat-shutdown] o.s.boot.tomcat.GracefulShutdown         : Graceful shutdown complete
2026-03-23T02:43:13.722+09:00  INFO 44352 --- [ionShutdownHook] j.LocalContainerEntityManagerFactoryBean : Closing JPA EntityManagerFactory for persistence unit 'default'
2026-03-23T02:43:13.726+09:00  INFO 44352 --- [ionShutdownHook] com.zaxxer.hikari.HikariDataSource       : HikariPool-1 - Shutdown initiated...
2026-03-23T02:43:13.730+09:00  INFO 44352 --- [ionShutdownHook] com.zaxxer.hikari.HikariDataSource       : HikariPool-1 - Shutdown completed.

위 콘솔 로그는 [api-orchestrator](api-orchestrator) 입니다.

C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai\.venv\Scripts\python.exe C:/Users/LeeHoYoung/IdeaProjects/t/stockmate-ai/websocket-listener/main.py
2026-03-23 02:40:29,935 [INFO] main – ==================================================
2026-03-23 02:40:29,935 [INFO] main –   StockMate AI – WebSocket Listener 시작
2026-03-23 02:40:29,935 [INFO] main – ==================================================
2026-03-23 02:40:29,945 [INFO] main – [Redis] 연결 성공 → localhost:6379
2026-03-23 02:40:29,946 [INFO] health_server – [Health] 헬스체크 서버 시작 → http://0.0.0.0:8081/health
2026-03-23 02:40:29,946 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:40:29,946 [INFO] ws_client – [WS] 연결 시도 #1 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:40:30,081 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:40:30,082 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:40:40,092 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:40:43,103 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:40:43,103 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:40:43,223 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:40:43,224 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:40:53,234 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:40:56,248 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:40:56,248 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:40:56,382 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:40:56,383 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:41:06,391 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:41:09,392 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:41:09,392 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:41:09,521 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:41:09,522 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:41:19,533 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:41:22,547 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:41:22,547 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:41:22,651 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:41:22,653 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:41:22,963 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:41:23,269 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:41:23,585 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:41:33,594 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:41:36,604 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:41:36,604 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:41:36,715 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:41:36,716 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:41:37,031 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:41:37,335 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:41:37,643 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:41:47,652 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:41:50,653 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:41:50,654 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:41:50,792 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:41:50,793 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:41:51,094 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:41:51,400 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:41:51,706 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:42:01,717 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:42:04,725 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:42:04,725 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:42:04,826 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:42:04,827 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:42:05,136 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:42:05,440 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:42:05,746 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:42:15,755 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:42:18,762 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:42:18,762 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:42:18,901 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:42:18,902 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:42:19,216 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:42:19,521 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:42:19,828 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:42:29,837 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:42:32,839 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:42:32,839 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:42:32,967 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:42:32,968 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:42:33,279 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:42:33,586 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:42:33,890 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:42:44,120 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:42:47,122 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:42:47,122 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:42:47,235 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:42:47,236 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:42:47,548 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:42:47,854 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:42:48,165 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:42:58,173 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:43:01,184 [INFO] token_loader – [Token] Redis 토큰 로드 성공 (시도 1회)
2026-03-23 02:43:01,185 [INFO] ws_client – [WS] 연결 시도 #2 → wss://mockapi.kiwoom.com:10000/api/dostk/websocket
2026-03-23 02:43:01,303 [INFO] ws_client – [WS] 연결 성공
2026-03-23 02:43:01,304 [INFO] ws_client – [WS] 구독 grp=5 type=0B 1개
2026-03-23 02:43:01,609 [INFO] ws_client – [WS] 구독 grp=6 type=0H 1개
2026-03-23 02:43:01,915 [INFO] ws_client – [WS] 구독 grp=7 type=1h 1개
2026-03-23 02:43:02,220 [INFO] ws_client – [WS] 구독 grp=8 type=0D 1개
2026-03-23 02:43:12,229 [INFO] ws_client – [WS] 3.0초 후 재연결 (1번째)
2026-03-23 02:43:13,578 [INFO] main – [Main] 종료 시그널 수신 (2)
2026-03-23 02:43:13,579 [INFO] main – [Main] 종료 완료

이것은 [websocket-listener](websocket-listener) 콘솔 로그입니다.,

[2026-03-23 오전 2:41] 이 호영: /status
[2026-03-23 오전 2:41] SMA: 🟢 System Status
Java API: UP | kiwoom-trading

📡 WebSocket
Python WS: ❌ Offline (TTL expired)
Java WS:   ❌ Disconnected

📊 Claude AI Today
Calls: 0 / 100
Tokens: 0
[2026-03-23 오전 2:41] 이 호영: /wsStart
[2026-03-23 오전 2:41] SMA: 📡 WebSocket 구독 시작 완료
[2026-03-23 오전 2:41] 이 호영: /status
[2026-03-23 오전 2:41] SMA: 🟢 System Status
Java API: UP | kiwoom-trading

📡 WebSocket
Python WS: ❌ Offline (TTL expired)
Java WS:   ❌ Disconnected

📊 Claude AI Today
Calls: 0 / 100
Tokens: 0
[2026-03-23 오전 2:41] 이 호영: /wsStart
[2026-03-23 오전 2:41] SMA: 📡 WebSocket 구독 시작 완료
[2026-03-23 오전 2:42] 이 호영: /status
[2026-03-23 오전 2:42] SMA: 🟢 System Status
Java API: UP | kiwoom-trading

📡 WebSocket
Python WS: ❌ Offline (TTL expired)
Java WS:   ❌ Disconnected

📊 Claude AI Today
Calls: 0 / 100
Tokens: 0

텔레그램 메시지 내역 입니다.
