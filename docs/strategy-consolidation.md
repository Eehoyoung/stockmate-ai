# Strategy Consolidation

전략 감사, 통합 계획, 코드 정리 방향을 하나의 문서로 정리한다.

## Goal

- 전략 정의와 실제 구현의 차이를 줄인다.
- 전략별 후보 선정, 점수화, 신호 생성 흐름을 공통 구조로 수렴시킨다.
- 중복 로직과 전략별 예외 처리를 줄여 유지보수성을 높인다.

## Audit Summary

- 전략 설명 문서와 Python/Java 구현 간 용어와 조건이 완전히 일치하지 않는 구간이 있다.
- 일부 전략은 후보 선정과 엔트리 조건이 분리되지 않아 해석이 어렵다.
- 전략별 세부 문서가 많지만 기준 문서가 없어 중복 설명이 발생한다.

## Consolidation Rules

- 전략별 입력 데이터, 핵심 조건, 후보 선정 규칙, 진입/보류/제외 기준을 같은 구조로 문서화한다.
- 공통 지표 계산, 점수화, 신호 포맷은 shared util을 우선 사용한다.
- Telegram 표출용 설명은 전략 내부 로직과 분리해서 formatter 계층에서 관리한다.

## Implementation Direction

- 전략별 후보풀 생성은 공통 인터페이스 위에서 동작하게 정리한다.
- 점수 산식과 랭킹 계산은 전략별 튜닝 포인트만 남기고 공통 파이프라인으로 수렴시킨다.
- 전략 문서 변경 시 코드와 테스트를 함께 갱신하는 흐름을 유지한다.

## Active References

- 세부 전략 흐름: [all_strategies_flow.md](./all_strategies_flow.md)
- 전략 요약: [전략.md](./전략.md)
- 후보풀 구조: [candidate-pool-architecture.md](./candidate-pool-architecture.md)
