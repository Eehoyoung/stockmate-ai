
:: Spring Boot ::                (v4.0.3)


{"ts":"2026-04-06T04:23:37.531+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApiOrchestratorApplication","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Starting ApiOrchestratorApplication v0.0.1-SNAPSHOT using Java 25.0.2 with PID 1 (/app/app.jar started by root in /app)","stack":""}

{"ts":"2026-04-06T04:23:37.535+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApiOrchestratorApplication","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"No active profile set, falling back to 1 default profile: "default"","stack":""}

{"ts":"2026-04-06T04:23:39.656+09:00","level":"INFO","service":"api-orchestrator","module":"o.apache.coyote.http11.Http11NioProtocol","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Initializing ProtocolHandler ["http-nio-8080"]","stack":""}

{"ts":"2026-04-06T04:23:39.659+09:00","level":"INFO","service":"api-orchestrator","module":"o.apache.catalina.core.StandardService","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Starting service [Tomcat]","stack":""}

{"ts":"2026-04-06T04:23:39.660+09:00","level":"INFO","service":"api-orchestrator","module":"org.apache.catalina.core.StandardEngine","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Starting Servlet engine: [Apache Tomcat/11.0.18]","stack":""}

{"ts":"2026-04-06T04:23:40.672+09:00","level":"INFO","service":"api-orchestrator","module":"com.zaxxer.hikari.HikariDataSource","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"HikariPool-1 - Starting...","stack":""}

{"ts":"2026-04-06T04:23:40.810+09:00","level":"INFO","service":"api-orchestrator","module":"com.zaxxer.hikari.pool.HikariPool","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"HikariPool-1 - Added connection org.postgresql.jdbc.PgConnection@3e8995cc","stack":""}

{"ts":"2026-04-06T04:23:40.811+09:00","level":"INFO","service":"api-orchestrator","module":"com.zaxxer.hikari.HikariDataSource","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"HikariPool-1 - Start completed.","stack":""}

{"ts":"2026-04-06T04:23:42.993+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.apiorchestrator.config.RedisConfig","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Redis 연결 설정 - redis:6379:cv93523827 (인증 사용)","stack":""}

{"ts":"2026-04-06T04:23:43.269+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.config.KiwoomRateLimiter","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"[RateLimiter] 키움 API Rate Limiter 시작 – 최대 3req/s (333ms 간격)","stack":""}

{"ts":"2026-04-06T04:23:44.200+09:00","level":"WARN","service":"api-orchestrator","module":"o.s.b.j.a.JpaBaseConfiguration$JpaWebConfiguration","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"spring.jpa.open-in-view is enabled by default. Therefore, database queries may be performed during view rendering. Explicitly configure spring.jpa.open-in-view to disable this warning","stack":""}

{"ts":"2026-04-06T04:23:44.854+09:00","level":"INFO","service":"api-orchestrator","module":"o.apache.coyote.http11.Http11NioProtocol","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Starting ProtocolHandler ["http-nio-8080"]","stack":""}

{"ts":"2026-04-06T04:23:44.886+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApiOrchestratorApplication","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"Started ApiOrchestratorApplication in 8.046 seconds (process running for 8.682)","stack":""}

{"ts":"2026-04-06T04:23:44.974+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApplicationStartupRunner","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"=== 키움 트레이딩 시스템 시작 ===","stack":""}

{"ts":"2026-04-06T04:23:44.983+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.apiorchestrator.service.TokenService","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"키움 액세스 토큰 발급 요청","stack":""}

{"ts":"2026-04-06T04:23:44.985+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.apiorchestrator.service.TokenService","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"yIsCIHF-XhMzSo1IeC6lLRFO-yDI7yWXbvVD6DhsXZY / lt3YJHrNgE2bid6shK3J1aaCZXa5UATbCILHATG09Sw","stack":""}

{"ts":"2026-04-06T04:23:46.102+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.apiorchestrator.service.TokenService","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"토큰 발급 완료 - 만료: 2026-04-07T03:13:48","stack":""}

{"ts":"2026-04-06T04:23:46.116+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApplicationStartupRunner","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"초기 토큰 발급 완료","stack":""}

{"ts":"2026-04-06T04:23:46.116+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApplicationStartupRunner","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"WebSocket: Python websocket-listener 단독 운영 중","stack":""}

{"ts":"2026-04-06T04:23:46.117+09:00","level":"INFO","service":"api-orchestrator","module":"o.i.a.ApplicationStartupRunner","thread":"main","request_id":"","signal_id":"","stk_cd":"","error_code":"","msg":"=== 시스템 초기화 완료 ===","stack":""}
websocket-listener

{"ts": "2026-04-06T04:24:36.462+09:00", "level": "INFO", "service": "websocket-listener", "module": "ws_client", "msg": "[WS] 장 종료 시간 외 (현재 KST 04:24) – 다음 개장 04/06 07:30 KST | 185분 남음 | 60초 대기"}

{"ts": "2026-04-06T04:25:36.516+09:00", "level": "INFO", "service": "websocket-listener", "module": "ws_client", "msg": "[WS] 장 종료 시간 외 (현재 KST 04:25) – 다음 개장 04/06 07:30 KST | 184분 남음 | 60초 대기"}
