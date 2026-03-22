026-03-22T00:35:09.285+09:00  INFO 2480 --- [           main] o.i.a.ApiOrchestratorApplication         : Starting ApiOrchestratorApplication using Java 25.0.2 with PID 2480 (C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai\api-orchestrator\build\classes\java\main started by LeeHoYoung in C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai)
2026-03-22T00:35:09.289+09:00  INFO 2480 --- [           main] o.i.a.ApiOrchestratorApplication         : No active profile set, falling back to 1 default profile: "default"
2026-03-22T00:35:10.036+09:00  INFO 2480 --- [           main] .s.d.r.c.RepositoryConfigurationDelegate : Multiple Spring Data modules found, entering strict repository configuration mode
2026-03-22T00:35:10.036+09:00  INFO 2480 --- [           main] .s.d.r.c.RepositoryConfigurationDelegate : Bootstrapping Spring Data JPA repositories in DEFAULT mode.
2026-03-22T00:35:10.181+09:00  INFO 2480 --- [           main] .s.d.r.c.RepositoryConfigurationDelegate : Finished Spring Data repository scanning in 135 ms. Found 4 JPA repository interfaces.
2026-03-22T00:35:10.480+09:00  INFO 2480 --- [           main] .s.d.r.c.RepositoryConfigurationDelegate : Multiple Spring Data modules found, entering strict repository configuration mode
2026-03-22T00:35:10.481+09:00  INFO 2480 --- [           main] .s.d.r.c.RepositoryConfigurationDelegate : Bootstrapping Spring Data Redis repositories in DEFAULT mode.
2026-03-22T00:35:10.532+09:00  INFO 2480 --- [           main] .RepositoryConfigurationExtensionSupport : Spring Data Redis - Could not safely identify store assignment for repository candidate interface org.invest.apiorchestrator.repository.KiwoomTokenRepository; If you want this repository to be a Redis repository, consider annotating your entities with one of these annotations: org.springframework.data.redis.core.RedisHash (preferred), or consider extending one of the following types with your repository: org.springframework.data.keyvalue.repository.KeyValueRepository
2026-03-22T00:35:10.533+09:00  INFO 2480 --- [           main] .RepositoryConfigurationExtensionSupport : Spring Data Redis - Could not safely identify store assignment for repository candidate interface org.invest.apiorchestrator.repository.TradingSignalRepository; If you want this repository to be a Redis repository, consider annotating your entities with one of these annotations: org.springframework.data.redis.core.RedisHash (preferred), or consider extending one of the following types with your repository: org.springframework.data.keyvalue.repository.KeyValueRepository
2026-03-22T00:35:10.533+09:00  INFO 2480 --- [           main] .RepositoryConfigurationExtensionSupport : Spring Data Redis - Could not safely identify store assignment for repository candidate interface org.invest.apiorchestrator.repository.ViEventRepository; If you want this repository to be a Redis repository, consider annotating your entities with one of these annotations: org.springframework.data.redis.core.RedisHash (preferred), or consider extending one of the following types with your repository: org.springframework.data.keyvalue.repository.KeyValueRepository
2026-03-22T00:35:10.533+09:00  INFO 2480 --- [           main] .RepositoryConfigurationExtensionSupport : Spring Data Redis - Could not safely identify store assignment for repository candidate interface org.invest.apiorchestrator.repository.WsTickDataRepository; If you want this repository to be a Redis repository, consider annotating your entities with one of these annotations: org.springframework.data.redis.core.RedisHash (preferred), or consider extending one of the following types with your repository: org.springframework.data.keyvalue.repository.KeyValueRepository
2026-03-22T00:35:10.534+09:00  INFO 2480 --- [           main] .s.d.r.c.RepositoryConfigurationDelegate : Finished Spring Data repository scanning in 43 ms. Found 0 Redis repository interfaces.
2026-03-22T00:35:11.219+09:00  INFO 2480 --- [           main] o.s.boot.tomcat.TomcatWebServer          : Tomcat initialized with port 8080 (http)
2026-03-22T00:35:11.235+09:00  INFO 2480 --- [           main] o.apache.catalina.core.StandardService   : Starting service [Tomcat]
2026-03-22T00:35:11.235+09:00  INFO 2480 --- [           main] o.apache.catalina.core.StandardEngine    : Starting Servlet engine: [Apache Tomcat/11.0.18]
2026-03-22T00:35:11.338+09:00  INFO 2480 --- [           main] b.w.c.s.WebApplicationContextInitializer : Root WebApplicationContext: initialization completed in 2005 ms
2026-03-22T00:35:11.600+09:00  INFO 2480 --- [           main] org.hibernate.orm.jpa                    : HHH008540: Processing PersistenceUnitInfo [name: default]
2026-03-22T00:35:11.670+09:00  INFO 2480 --- [           main] org.hibernate.orm.core                   : HHH000001: Hibernate ORM core version 7.2.4.Final
2026-03-22T00:35:12.246+09:00  INFO 2480 --- [           main] o.s.o.j.p.SpringPersistenceUnitInfo      : No LoadTimeWeaver setup: ignoring JPA class transformer
2026-03-22T00:35:12.286+09:00  INFO 2480 --- [           main] com.zaxxer.hikari.HikariDataSource       : HikariPool-1 - Starting...
2026-03-22T00:35:12.482+09:00  INFO 2480 --- [           main] com.zaxxer.hikari.pool.HikariPool        : HikariPool-1 - Added connection org.postgresql.jdbc.PgConnection@108fd5d5
2026-03-22T00:35:12.483+09:00  INFO 2480 --- [           main] com.zaxxer.hikari.HikariDataSource       : HikariPool-1 - Start completed.
2026-03-22T00:35:12.555+09:00  INFO 2480 --- [           main] org.hibernate.orm.connections.pooling    : HHH10001005: Database info:
Database JDBC URL [jdbc:postgresql://localhost:5432/SMA]
Database driver: PostgreSQL JDBC Driver
Database dialect: PostgreSQLDialect
Database version: 18.3
Default catalog/schema: SMA/public
Autocommit mode: undefined/unknown
Isolation level: READ_COMMITTED [default READ_COMMITTED]
JDBC fetch size: none
Pool: DataSourceConnectionProvider
Minimum pool size: undefined/unknown
Maximum pool size: undefined/unknown
2026-03-22T00:35:13.699+09:00  INFO 2480 --- [           main] org.hibernate.orm.core                   : HHH000489: No JTA platform available (set 'hibernate.transaction.jta.platform' to enable JTA platform integration)
2026-03-22T00:35:13.801+09:00  INFO 2480 --- [           main] j.LocalContainerEntityManagerFactoryBean : Initialized JPA EntityManagerFactory for persistence unit 'default'
2026-03-22T00:35:14.043+09:00  INFO 2480 --- [           main] o.s.d.j.r.query.QueryEnhancerFactories   : Hibernate is in classpath; If applicable, HQL parser will be used.
2026-03-22T00:35:14.585+09:00  INFO 2480 --- [           main] o.i.apiorchestrator.config.RedisConfig   : Redis 연결 설정 - localhost:6379 (인증 사용)
2026-03-22T00:35:15.512+09:00  WARN 2480 --- [           main] JpaBaseConfiguration$JpaWebConfiguration : spring.jpa.open-in-view is enabled by default. Therefore, database queries may be performed during view rendering. Explicitly configure spring.jpa.open-in-view to disable this warning
2026-03-22T00:35:16.129+09:00  INFO 2480 --- [           main] o.s.b.a.e.web.EndpointLinksResolver      : Exposing 2 endpoints beneath base path '/actuator'
2026-03-22T00:35:16.201+09:00  INFO 2480 --- [           main] o.s.boot.tomcat.TomcatWebServer          : Tomcat started on port 8080 (http) with context path '/'
2026-03-22T00:35:16.216+09:00  INFO 2480 --- [           main] o.i.a.ApiOrchestratorApplication         : Started ApiOrchestratorApplication in 7.403 seconds (process running for 8.101)
2026-03-22T00:35:16.222+09:00  INFO 2480 --- [           main] o.s.b.b.a.JobLauncherApplicationRunner   : Running default command line with: []
2026-03-22T00:35:16.223+09:00  INFO 2480 --- [           main] o.i.a.ApplicationStartupRunner           : === 키움 트레이딩 시스템 시작 ===
2026-03-22T00:35:16.233+09:00  INFO 2480 --- [           main] o.i.a.service.TokenService               : 키움 액세스 토큰 발급 요청
2026-03-22T00:35:16.235+09:00  INFO 2480 --- [           main] o.i.a.service.TokenService               : MtHBp6EbCe9Lf3ERjnOEioVl38nWQMtl_EChu1eBUl4 / 8zvCtXRw4gZ8PhhDlu-nr0sRINm1BO-tPviGD72ia28
WARNING: A restricted method in java.lang.System has been called
WARNING: java.lang.System::loadLibrary has been called by io.netty.util.internal.NativeLibraryUtil in an unnamed module (file:/C:/gradle/caches/modules-2/files-2.1/io.netty/netty-common/4.2.10.Final/c55e97d9bd061a2d88418d2d831e1fa39cb975e7/netty-common-4.2.10.Final.jar)
WARNING: Use --enable-native-access=ALL-UNNAMED to avoid a warning for callers in this module
WARNING: Restricted methods will be blocked in a future release unless native access is enabled

2026-03-22T00:35:17.353+09:00  WARN 2480 --- [           main] o.i.a.service.TokenService               : Redis 토큰 캐싱 실패 (DB에는 저장됨): Unable to connect to Redis
2026-03-22T00:35:17.353+09:00  INFO 2480 --- [           main] o.i.a.service.TokenService               : 토큰 발급 완료 - 만료: 2026-03-22T23:47:47
2026-03-22T00:35:17.364+09:00  INFO 2480 --- [           main] o.i.a.ApplicationStartupRunner           : 초기 토큰 발급 완료
2026-03-22T00:35:17.365+09:00  INFO 2480 --- [           main] o.i.a.ApplicationStartupRunner           : 거래 시간 외 - WebSocket 대기 상태
2026-03-22T00:35:17.366+09:00  INFO 2480 --- [           main] o.i.a.ApplicationStartupRunner           : === 시스템 초기화 완료 ===
2026-03-22T00:35:17.881+09:00  INFO 2480 --- [192.168.219.111] o.a.c.c.C.[Tomcat].[localhost].[/]       : Initializing Spring DispatcherServlet 'dispatcherServlet'
2026-03-22T00:35:17.882+09:00  INFO 2480 --- [192.168.219.111] o.s.web.servlet.DispatcherServlet        : Initializing Servlet 'dispatcherServlet'
2026-03-22T00:35:17.884+09:00  INFO 2480 --- [192.168.219.111] o.s.web.servlet.DispatcherServlet        : Completed initialization in 2 ms
2026-03-22T00:35:17.916+09:00  WARN 2480 --- [oundedElastic-1] b.d.r.h.DataRedisReactiveHealthIndicator : Redis health check failed

org.springframework.data.redis.RedisConnectionFailureException: Unable to connect to Redis
Caused by: io.lettuce.core.RedisConnectionException: Unable to connect to localhost/<unresolved>:6379
Caused by: io.lettuce.core.RedisCommandExecutionException: ERR Client sent AUTH, but no password is set
