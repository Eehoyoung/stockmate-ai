# 휴장일 자동 차단 운영 설계

## 결론

Toss 증권 Open API의 `GET /api/v1/market-calendar/KR` 응답을 국내 장 운영 여부의 기준으로 사용한다. 조회일의 `today.integrated.regularMarket`이 존재하면 `OPEN`, `integrated` 또는 `regularMarket`이 `null`이면 `CLOSED`로 판정한다. 주말만 확인하던 방식과 달리 대체공휴일과 임시휴장도 자동 반영된다.

## 호출 및 캐시 순서

1. `api-orchestrator`가 날짜별 결과를 Redis `market:kr:calendar:YYYY-MM-DD`에 `OPEN` 또는 `CLOSED`로 14일 보관한다.
2. 매일 20:50에는 남아 있는 Toss 토큰으로 다음 날을 미리 조회한다. 토큰이 없으면 이 사전 조회 때문에 새 토큰을 발급하지 않는다.
3. 시작 30초 후와 6시간 간격으로 오늘 결과가 없을 때만 조회한다. 캐시도 토큰도 없으면 정확한 휴장 판정을 위해 Toss 토큰 1회가 필요할 수 있다.
4. 07:00 Toss 토큰 작업은 `CLOSED` 또는 판정 불가 시 생략한다. 장이 열리는 날도 기존 유효 토큰을 재사용하고 무조건 재발급하지 않는다.
5. Toss 지수와 시장 수급 수집기는 `OPEN` 캐시가 있을 때만 외부 API를 호출한다.

## 뉴스와 AI 비용 차단

예약 뉴스 브리핑은 뉴스 수집 또는 AI 분석보다 먼저 Redis 휴장 상태를 확인한다.

- `OPEN`: 기존 브리핑 실행
- `CLOSED`: 뉴스 수집, AI 분석, 텔레그램 발송 모두 생략
- `UNKNOWN`: 비용 보호를 위해 동일하게 생략하고 `SKIPPED_MARKET_UNKNOWN` 기록

사용자가 직접 요청하는 실시간 `/news` 조회는 예약 작업과 구분해 유지한다. 명시적으로 요청한 조회까지 막지는 않는다.

## 운영 확인

`ops:scheduler:news_scheduler:last_status` 값이 `SKIPPED_MARKET_CLOSED`이면 정상적인 휴장 차단이다. `SKIPPED_MARKET_UNKNOWN`은 Redis 또는 Toss 캘린더 확인 실패이므로 연결 상태를 점검한다. Docker 컨테이너가 내려가 있으면 어떤 예약 작업도 실행되지 않는다.
