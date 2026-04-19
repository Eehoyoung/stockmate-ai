# Operations And Security

운영 안정화와 보안 강화 관련 메모를 하나의 기준 문서로 통합한다.

## Current Risk Summary

- 외부 API, Redis, Postgres, WebSocket listener 사이의 장애 전파 가능성이 크다.
- 스케줄러와 큐 소비 로직이 분산되어 있어 장애 원인 추적이 느려질 수 있다.
- 비밀정보, 토큰, 운영 권한 관리는 서비스별로 흩어져 있어 일관된 기준이 필요하다.

## Operations Priorities

- 장애 시 서비스별 상태를 한 번에 확인할 수 있는 헬스체크와 로그 기준을 유지한다.
- Redis 연결 복구, 큐 적체, 스케줄러 중복 실행을 우선 감시 대상으로 둔다.
- Telegram, ai-engine, api-orchestrator의 사용자 노출 메시지는 운영 상태와 분리해서 관리한다.

## Security Priorities

- `.env` 기반 비밀정보는 로컬 보관을 원칙으로 하고 저장소 반입을 금지한다.
- 토큰 재발급, 외부 API 키, Kiwoom 인증값은 로그에 남기지 않는다.
- 내부 제어용 엔드포인트는 운영자 전용으로 분리하고 호출 이력을 남긴다.

## Immediate Action Items

- 서비스별 헬스체크 항목을 문서화하고 `status` 응답과 맞춘다.
- 오류 로그 레벨, 민감정보 마스킹, 재시도 정책을 공통 규칙으로 맞춘다.
- Telegram/Java/ai-engine에 남아 있는 죽은 발송 경로와 사용하지 않는 큐를 계속 제거한다.

## Long-Term Direction

- 운영 문서는 개별 보고서 대신 이 문서에 계속 누적한다.
- 보안 점검 결과는 취약점, 영향도, 조치상태 형식으로만 추가한다.
