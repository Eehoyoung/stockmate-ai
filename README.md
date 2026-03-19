# 키움 REST API 데이트레이딩 시스템 - Java 백엔드

## 개요
키움증권 REST API 기반 7가지 데이트레이딩 전술 자동 종목 선별 시스템입니다.

## 기술 스택
- **Java 21** / Spring Boot 3.2
- **PostgreSQL** - 신호 이력, 토큰, VI 이벤트 영구 저장
- **Redis** - WebSocket 실시간 시세 캐시, 신호 중복 제거, 텔레그램 큐
- **OkHttp** - 키움 WebSocket 클라이언트
- **WebFlux (WebClient)** - 키움 REST API 비동기 호출

## 프로젝트 구조

```
src/main/java/com/trading/kiwoom/
├── config/
│   ├── KiwoomProperties.java     # application.yml 바인딩
│   ├── RedisConfig.java          # Redis 설정
│   ├── WebClientConfig.java      # HTTP 클라이언트
│   ├── JpaConfig.java            # JPA/Auditing
│   ├── AsyncConfig.java          # 스레드풀 설정
│   └── ObjectMapperConfig.java   # Jackson 설정
│
├── domain/
│   ├── TradingSignal.java        # 거래 신호 엔티티
│   ├── KiwoomToken.java          # 액세스 토큰 엔티티
│   ├── ViEvent.java              # VI 이벤트 엔티티
│   └── WsTickData.java           # WebSocket 틱 데이터 엔티티
│
├── dto/
│   ├── request/
│   │   ├── KiwoomApiRequest.java # 공통 요청 기반
│   │   ├── TokenRequest.java     # 토큰 발급 요청
│   │   └── StrategyRequests.java # 전술별 API 요청 DTO 모음
│   └── response/
│       ├── TokenResponse.java        # 토큰 응답
│       ├── KiwoomApiResponses.java   # 전술별 API 응답 DTO 모음
│       ├── TradingSignalDto.java     # 신호 전달 DTO
│       └── WsMarketData.java         # WebSocket 실시간 데이터 DTO
│
├── repository/
│   ├── TradingSignalRepository.java
│   ├── KiwoomTokenRepository.java
│   ├── ViEventRepository.java
│   └── WsTickDataRepository.java
│
├── service/
│   ├── TokenService.java            # 토큰 발급/갱신/캐싱
│   ├── KiwoomApiService.java        # REST API 공통 호출
│   ├── RedisMarketDataService.java  # Redis 실시간 데이터 R/W
│   ├── SignalService.java           # 신호 저장/발행
│   ├── StrategyService.java         # 7가지 전술 핵심 로직
│   ├── ViWatchService.java          # VI 눌림목 감시 워커
│   └── CandidateService.java        # 후보 종목 조회/캐싱
│
├── websocket/
│   ├── KiwoomWebSocketClient.java          # OkHttp WS 클라이언트
│   └── WebSocketSubscriptionManager.java  # 구독 종목 관리
│
├── scheduler/
│   ├── TradingScheduler.java        # 전술별 시간 스케줄러 (메인)
│   ├── TokenRefreshScheduler.java   # 토큰 자동 갱신
│   ├── ForceCloseScheduler.java     # 14:50 강제 청산 알림
│   └── DataCleanupScheduler.java    # 오래된 데이터 정리
│
├── controller/
│   └── TradingController.java       # REST API 컨트롤러
│
├── exception/
│   ├── KiwoomApiException.java
│   └── GlobalExceptionHandler.java
│
├── util/
│   ├── MarketTimeUtil.java          # 장시간 유틸
│   └── NumberParseUtil.java         # 숫자 파싱 유틸
│
├── ApplicationStartupRunner.java    # 앱 시작 초기화
└── KiwoomTradingApplication.java    # 메인 클래스
```

## 7가지 전술별 스케줄

| 전술 | 설명 | 실행 시간 | 주기 |
|------|------|----------|------|
| S1 | 갭상승 + 체결강도 시초가 | 09:00~09:10 | 2분 |
| S2 | VI 발동 후 눌림목 | 09:00~15:20 | 5초 (이벤트 기반) |
| S3 | 외인+기관 동시 순매수 | 09:30~14:30 | 5분 |
| S4 | 장대양봉 + 거래량 급증 | 09:30~14:30 | 3분 |
| S5 | 프로그램+외인 상위 | 10:00~14:00 | 10분 |
| S6 | 테마 후발주 | 09:30~13:00 | 10분 |
| S7 | 장전 동시호가 | 08:30~09:00 | 2분 |

## WebSocket 그룹별 구독

| 그룹 | 타입 | 설명 |
|------|------|------|
| GRP 1 | 0B | 주식체결 - 상위 200종목 |
| GRP 2 | 0D | 호가잔량 - 상위 100종목 |
| GRP 3 | 0H | 예상체결 - 장전용 상위 100종목 |
| GRP 4 | 1h | VI발동/해제 - 전체 |

## 환경 변수

```bash
KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
DB_USERNAME=trading
DB_PASSWORD=your_password
REDIS_HOST=localhost
REDIS_PORT=6379
```

## 실행 방법

```bash
# 로컬 개발
./gradlew bootRun --args='--spring.profiles.active=local'

# 운영
./gradlew bootJar
java -jar build/libs/kiwoom-trading-1.0.0.jar \
  --spring.profiles.active=prod \
  --KIWOOM_APP_KEY=xxx \
  --KIWOOM_SECRET_KEY=xxx
```

## Redis 키 규약

| 키 패턴 | TTL | 설명 |
|---------|-----|------|
| `kiwoom:token` | 23시간 | 액세스 토큰 |
| `ws:tick:{stkCd}` | 30초 | 실시간 체결 |
| `ws:expected:{stkCd}` | 60초 | 예상체결 |
| `ws:hoga:{stkCd}` | 10초 | 호가잔량 |
| `ws:strength:{stkCd}` | 5분 | 체결강도 리스트 |
| `vi:{stkCd}` | 1시간 | VI 이벤트 상태 |
| `vi_watch_queue` | 2시간 | VI 눌림목 감시 큐 |
| `signal:{stkCd}:{strategy}` | 1시간 | 중복 신호 방지 |
| `telegram_queue` | 12시간 | 텔레그램 발송 큐 |
| `candidates:{market}` | 3분 | 후보 종목 캐시 |

## 타 서비스 연동

- **Python**: `telegram_queue` → Redis 큐 폴링하여 전술 로직 분석/스코어링
- **Node.js 텔레그램 봇**: `telegram_queue` → 폴링하여 메시지 발송
- **PostgreSQL**: 신호 이력, VI 이벤트 영구 저장 (백테스트 데이터)
