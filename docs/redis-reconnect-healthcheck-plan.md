# Redis Reconnect / Healthcheck Stabilization Plan

## Objective

`ai-engine`의 Redis 의존 경로를 운영 중단 없이 복구 가능한 구조로 정리한다.

이번 작업의 목표는 전략 성능 향상이 아니라 운영 안정성 확보다.
특히 아래 경로의 단절 시 자동 복구와 명시적 오류 노출을 보장해야 한다.

- `telegram_queue` 소비
- `ws:tick`, `ws:hoga`, `ws:strength` 실시간 조회
- `position_monitor` 포지션 감시
- `position_reassessment` 재평가 캐시
- `ai_scored_queue` 재발행

## Why This Matters

Redis 장애나 순간 단절이 발생했을 때 재연결 계층이 약하면 다음 문제가 발생한다.

- 신호 큐 소비 중단
- 실시간 시세 공백으로 인한 잘못된 진입/청산 판단
- SL/TP/트레일링 감시 누락
- 장애 후 수동 재시작 전까지 서비스 정지
- 장애가 나도 `HOLD` 또는 무응답처럼 보여 원인 파악이 늦어짐

즉, 이 작업은 수익률 개선보다 먼저 필요한 운영 신뢰성 작업이다.

## Scope

대상 파일:

- `ai-engine/redis_reader.py`
- 필요 시 `ai-engine/engine.py`
- 필요 시 Redis 사용하는 워커의 초기화/복구 연결부
- `ai-engine/tests/test_redis_connection.py`

이번 범위에 포함:

- Redis 연결 관리자 계층 정비
- ping 기반 헬스체크
- 자동 재연결
- 지수 백오프
- 기존 클라이언트 정리
- 테스트 완주 확인

이번 범위에 미포함:

- Redis Sentinel/Cluster 도입
- 멀티 Redis failover 아키텍처 변경
- 외부 모니터링 시스템 도입

## Target Behavior

`RedisConnectionManager`는 다음 계약을 만족해야 한다.

### 1. connect()

- 새 Redis 클라이언트를 생성한다.
- `ping()` 성공 시에만 `_client`에 저장한다.
- 실패 시 생성한 클라이언트를 닫고 예외를 올린다.

### 2. reconnect()

- 기존 `_client`가 있으면 먼저 닫는다.
- 재연결 실패 시 `1, 2, 4, 8 ...` 초 지수 백오프를 사용한다.
- 최대 대기 시간은 `60초`로 제한한다.
- 성공 시 새 `_client`를 반환한다.

### 3. get_or_reconnect()

- `_client`가 없으면 `connect()` 호출
- `_client`가 있으면 `ping()` 확인
- `ping()` 실패 시 `reconnect()` 호출

### 4. close()

- `_client`가 있으면 `aclose()` 호출
- 예외가 나도 `_client = None` 상태는 보장
- 이중 호출에도 안전

### 5. _make_client()

- 연결 생성 파라미터가 일관돼야 한다.
- `retry_on_timeout=True` 유지
- `decode_responses=True` 유지

## Operational Rules

- 연결 실패는 삼키지 않는다. 로그와 예외 경로를 명확히 유지한다.
- 재연결 루프는 무한 대기 가능하되, 로그는 남겨야 한다.
- Redis 읽기 헬퍼 함수는 기존 호출부와 호환성을 유지한다.
- 기존 워커 코드가 전면 수정 없이 연결 관리자를 사용할 수 있어야 한다.

## Implementation Steps

1. `redis_reader.py`의 `RedisConnectionManager` 계약을 테스트 기준과 맞춘다.
2. `connect/reconnect/get_or_reconnect/close/_make_client` 동작을 정리한다.
3. 재연결 시 기존 client close 보장을 넣는다.
4. 백오프 상한 `60초`를 명시적으로 보장한다.
5. 예외 메시지와 경고 로그를 운영 추적 가능하게 정리한다.
6. `tests/test_redis_connection.py`를 전부 통과시킨다.
7. Redis 헬퍼 함수와의 호환성에 문제 없는지 최소 회귀 검증한다.

## Test Plan

필수:

- `python -m pytest ai-engine/tests/test_redis_connection.py -q`

권장:

- `python -m pytest ai-engine/tests/test_queue_worker.py -q`
- `python -m pytest ai-engine/tests/test_strategy_runner.py -q`
- `python -m pytest ai-engine/tests/test_integration.py -q`

검증 포인트:

- 초기화 기본값
- `connect()` 성공/실패
- `reconnect()` 2회차 성공
- 지수 백오프 증가
- 최대 백오프 cap
- reconnect 전 기존 client close
- ping 실패 시 reconnect 진입
- close 안전성
- `_make_client()` 인자 일치

## Risks

- 재연결 루프가 테스트 환경에서 hang처럼 보일 수 있다.
- 테스트가 mock 기반이라 실제 Redis 런타임 장애와 완전히 동일하지 않을 수 있다.
- 연결 관리자 도입 후 일부 호출부가 직접 client를 기대하면 호환성 이슈가 생길 수 있다.

## Completion Criteria

아래가 모두 만족되면 완료로 본다.

- `test_redis_connection.py` 전체 통과
- 기존 Redis helper 호출부와 호환
- 재연결/헬스체크 계약이 코드와 테스트에서 일치
- 장애 시 침묵 실패 대신 명시적 복구 경로가 존재
