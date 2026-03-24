# StockMate AI – 공통 오류코드 사전

> 장애 추적 시 `error_code` 필드 기준으로 4개 모듈 로그를 상관 조회합니다.  
> 모든 오류코드는 JSON 로그의 `error_code` 필드에 기록됩니다.

---

## 1. 키움 REST API 오류코드 (출처: kiwoom_error_code.md)

| No | error_code | 메시지 | 장애 레벨 | 권고 대응 |
|----|-----------|--------|-----------|-----------|
| 1  | KIWOOM_1501 | API ID가 Null이거나 값이 없습니다 | ERROR | 요청 파라미터 검증 |
| 2  | KIWOOM_1504 | 해당 URI에서는 지원하는 API ID가 아닙니다 | ERROR | API ID/URI 확인 |
| 3  | KIWOOM_1505 | 해당 API ID는 존재하지 않습니다 | ERROR | API ID 확인 |
| 4  | KIWOOM_1511 | 필수 입력 값에 값이 존재하지 않습니다 | ERROR | 필수 파라미터 점검 |
| 5  | KIWOOM_1512 | Http header 값이 설정되지 않았거나 읽을 수 없습니다 | ERROR | 헤더 설정 확인 |
| 6  | KIWOOM_1513 | Http Header에 authorization 필드가 없습니다 | ERROR | 토큰 헤더 추가 |
| 7  | KIWOOM_1514 | authorization 필드 형식이 맞지 않습니다 | ERROR | Bearer 형식 확인 |
| 8  | KIWOOM_1515 | Grant Type 형식 오류 | ERROR | grant_type 확인 |
| 9  | KIWOOM_1516 | Token이 정의되어 있지 않습니다 | ERROR | 토큰 값 확인 |
| 10 | KIWOOM_1517 | 입력 값 형식이 올바르지 않습니다 | ERROR | 파라미터 타입/범위 확인 |
| 11 | KIWOOM_1687 | 재귀 호출 발생 – API 호출 제한 | WARN | 호출 구조 검토 |
| 12 | KIWOOM_1700 | 허용 요청 개수 초과 (Rate Limit) | WARN | Rate Limiter 조정 (1초 대기 후 재시도) |
| 13 | KIWOOM_1901 | 시장 코드값이 존재하지 않습니다 | ERROR | 종목코드/시장코드 확인 |
| 14 | KIWOOM_1902 | 종목 정보가 없습니다 | WARN | 종목코드 유효성 확인 |
| 15 | KIWOOM_1999 | 예기치 못한 서버 에러 | ERROR | 키움 서버 장애 여부 확인, 재시도 |
| 16 | KIWOOM_8001 | App Key/Secret Key 검증 실패 | CRITICAL | 자격증명 교체 |
| 17 | KIWOOM_8002 | App Key/Secret Key 검증 실패 (사유 포함) | CRITICAL | 자격증명 교체 |
| 18 | KIWOOM_8003 | Access Token 조회 실패 | ERROR | 토큰 갱신 재시도 |
| 19 | KIWOOM_8005 | Token이 유효하지 않습니다 | ERROR | 즉시 토큰 재발급 |
| 20 | KIWOOM_8006 | Access Token 생성 실패 | ERROR | 토큰 갱신 재시도 |
| 21 | KIWOOM_8009 | Access Token 발급 실패 | ERROR | 토큰 갱신 재시도 |
| 22 | KIWOOM_8010 | Token 발급 IP와 서비스 요청 IP 불일치 | CRITICAL | 서버 IP 화이트리스트 확인 |
| 23 | KIWOOM_8011 | grant_type 누락 | ERROR | 요청 파라미터 확인 |
| 24 | KIWOOM_8012 | grant_type 값 오류 | ERROR | grant_type 값 확인 |
| 25 | KIWOOM_8015 | Access Token 폐기 실패 | WARN | 재시도 또는 무시 |
| 26 | KIWOOM_8016 | Token 폐기 시 Token 누락 | ERROR | 요청 파라미터 확인 |
| 27 | KIWOOM_8020 | appkey/secretkey 누락 | CRITICAL | 환경변수 확인 |
| 28 | KIWOOM_8030 | 투자구분(실전/모의) 불일치 – Appkey | CRITICAL | KIWOOM_MODE 환경변수 확인 |
| 29 | KIWOOM_8031 | 투자구분(실전/모의) 불일치 – Token | CRITICAL | KIWOOM_MODE 환경변수 확인 |
| 30 | KIWOOM_8040 | 단말기 인증 실패 | CRITICAL | 단말기 등록 확인 |
| 31 | KIWOOM_8050 | 지정단말기 인증 실패 | CRITICAL | 지정단말기 등록 확인 |
| 32 | KIWOOM_8103 | 토큰/단말기 인증 실패 | CRITICAL | 자격증명 및 단말기 종합 확인 |

---

## 2. WebSocket 연결 오류코드 (websocket-listener 내부)

| error_code | 원인 | 장애 레벨 | 권고 대응 |
|-----------|------|-----------|-----------|
| `WS_LOGIN_FAIL:{return_code}` | LOGIN 패킷 return_code ≠ 0 | ERROR | 토큰 유효성 확인 후 재연결 |
| `WS_LOGIN_TIMEOUT` | LOGIN 응답 10초 내 미수신 | ERROR | 네트워크 지연 확인 |
| `WS_LOGIN_JSON_ERROR` | LOGIN 응답 JSON 파싱 실패 | ERROR | 키움 프로토콜 변경 여부 확인 |
| `ConnectionClosed:{code}` | 서버가 WS 연결 종료 (RFC 6455 Close Code) | WARN | 코드별 대응 (하단 참조) |
| `OSError:{ExceptionType}` | 네트워크 소켓 오류 | ERROR | 네트워크 상태 확인 후 재연결 |
| `Exception:{ExceptionType}` | 예상치 못한 예외 | ERROR | 스택트레이스 확인 |

### WebSocket Close Code 상세

| Close Code | 의미 | 권고 대응 |
|-----------|------|-----------|
| 1000 | Normal Closure (Bye) | 정상 종료, 장 시간 확인 후 재연결 |
| 1001 | Going Away | 서버 점검 또는 재시작, 재연결 대기 |
| 1006 | Abnormal Closure (네트워크 단절) | 즉시 재연결 시도 |
| 1008 | Policy Violation (토큰 만료 등) | 토큰 갱신 후 재연결 |
| 1011 | Internal Server Error | 키움 서버 장애, 대기 후 재연결 |

---

## 3. Redis / 큐 오류코드 (내부)

| error_code | 원인 | 장애 레벨 | 권고 대응 |
|-----------|------|-----------|-----------|
| `REDIS_CONN_FAIL` | Redis 초기 연결 실패 | CRITICAL | Redis 서버 상태 확인 |
| `REDIS_PING_FAIL` | Redis ping 실패 (헬스체크 중) | ERROR | Redis 재연결 확인 |
| `REDIS_WRITE_FAIL` | Redis 데이터 쓰기 실패 | ERROR | 연결 상태 및 메모리 확인 |
| `REDIS_READ_FAIL` | Redis 데이터 읽기 실패 | ERROR | 연결 상태 확인 |
| `QUEUE_LAG_HIGH` | 큐 적체 임계치 초과 (기본 100건) | WARN | ai-engine/telegram-bot 처리 속도 확인 |

---

## 4. AI 엔진 오류코드 (ai-engine 내부)

| error_code | 원인 | 장애 레벨 | 권고 대응 |
|-----------|------|-----------|-----------|
| `AI_SCORE_FAIL` | Claude API 점수화 실패 | ERROR | API 키/한도 확인 |
| `AI_PARSE_FAIL` | Claude 응답 JSON 파싱 실패 | WARN | 프롬프트/모델 확인 |
| `AI_TIMEOUT` | Claude API 응답 타임아웃 | WARN | 재시도 후 기본값 사용 |
| `STRATEGY_FAIL:{name}` | 전략 실행 중 예외 | ERROR | 전략 코드 및 입력 데이터 확인 |
| `SIGNAL_INVALID` | 신호 스키마 검증 실패 | WARN | 신호 생성 로직 확인 |

---

## 5. 텔레그램 봇 오류코드 (telegram-bot 내부)

| error_code | 원인 | 장애 레벨 | 권고 대응 |
|-----------|------|-----------|-----------|
| `TG_SEND_FAIL` | 텔레그램 메시지 전송 실패 | ERROR | 봇 토큰/채팅 ID 확인 |
| `TG_RATE_LIMIT` | 텔레그램 API Rate Limit | WARN | 전송 간격 조정 |
| `TG_UNAUTHORIZED` | 허가되지 않은 사용자 접근 | WARN | 허용 chat_id 목록 확인 |
| `TG_QUEUE_EMPTY` | 처리할 신호 없음 (정보성) | DEBUG | 정상 상태 |
| `TG_BOT_TOKEN_MISSING` | TELEGRAM_BOT_TOKEN 미설정 | CRITICAL | 환경변수 설정 |

---

## 6. 오류코드 상관 조회 예시 (jq)

```bash
# 특정 request_id 로 4개 모듈 로그 상관 조회
REQUEST_ID="abc-123"
jq -r ". | select(.request_id == \"$REQUEST_ID\")" \
  logs/websocket-listener.log \
  logs/api-orchestrator.log \
  logs/ai-engine.log \
  logs/telegram-bot.log | jq -s 'sort_by(.ts)'

# 최근 1시간 CRITICAL/ERROR 집계
jq -r 'select(.level == "ERROR" or .level == "CRITICAL") | [.ts, .service, .error_code, .msg] | @tsv' \
  logs/*.log | sort
```

---

*최종 수정: 2026-03-24 | 관리: Phase A1-3*
