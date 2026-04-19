# Docs Guide

이 디렉터리는 현재 운영과 개발에 직접 필요한 문서만 남기고, 일회성 보고서와 중복 계획서는 정리한 상태를 기준으로 유지한다.

## Core

- [project-capabilities.md](./project-capabilities.md): 시스템 기능 개요
- [project-process.md](./project-process.md): 서비스 흐름과 운영 프로세스
- [project-review.md](./project-review.md): 전체 구조 리뷰
- [all_strategies_flow.md](./all_strategies_flow.md): 전략 전체 흐름
- [전략.md](./전략.md): 전략 요약

## Operations

- [operations-and-security.md](./operations-and-security.md): 운영 안정화, 장애 대응, 보안 강화 통합 문서
- [logging_standards.md](./logging_standards.md): 로깅 기준
- [redis_recovery.md](./redis_recovery.md): Redis 복구 절차
- [ws_solver.md](./ws_solver.md): WebSocket 이슈 해결 메모

## Strategy And Candidate

- [strategy-consolidation.md](./strategy-consolidation.md): 전략 통합 계획, 감사 결과, 코드 정리 방향
- [candidate-pool-architecture.md](./candidate-pool-architecture.md): 후보풀 구조, 전략별 운용, 추천 기준 통합 문서
- [candidate_selection_report.md](./candidate_selection_report.md): 후보 선정 결과 요약
- [table_persistence_completion_2026-04-16.md](./table_persistence_completion_2026-04-16.md): 테이블 영속화 작업 결과
- [tp_sl_plan.md](./tp_sl_plan.md): TP/SL 공통 계획
- [tp_sl_per_strategy_plan.md](./tp_sl_per_strategy_plan.md): 전략별 TP/SL 계획

## Telegram And AI

- [telegram_signal.md](./telegram_signal.md): 텔레그램 신호/브리핑 규격
- [telegram_dead_code_plan.md](./telegram_dead_code_plan.md): 텔레그램 정리 계획
- [scorer_telegram_upgrade_plan.md](./scorer_telegram_upgrade_plan.md): scorer-telegram 연계 개선안
- [scorer_upgrade_plan_20260404.md](./scorer_upgrade_plan_20260404.md): scorer 고도화 계획

## API Reference

- [kiwoom_api_reference.md](./kiwoom_api_reference.md): Kiwoom API 상위 레퍼런스
- [kiwoom_error_code.md](./kiwoom_error_code.md): Kiwoom 오류코드
- [error_codes.md](./error_codes.md): 공통 오류 메모
- [api/](./api): 주요 API 세부 레퍼런스
- [candidate/](./candidate): 후보풀 관련 API 메모
- [rank_info/](./rank_info): 랭킹/순위 조회 API 메모

## Historical But Retained

- [db_schema_upgrade_plan_20260406.md](./db_schema_upgrade_plan_20260406.md): DB 스키마 변경 계획
- [value_up_dev_plan.md](./value_up_dev_plan.md): Value-up 관련 기획
- [SMA_사용설명서.md](./SMA_%EC%82%AC%EC%9A%A9%EC%84%A4%EB%AA%85%EC%84%9C.md): SMA 사용 가이드
- [SMA_완성도_평가.md](./SMA_%EC%99%84%EC%84%B1%EB%8F%84_%ED%8F%89%EA%B0%80.md): SMA 평가 메모

## Cleanup Rule

- 날짜가 붙은 일회성 보고서나 동일 주제의 중복 계획서는 새 통합 문서가 있으면 삭제한다.
- API 문서는 상위 요약 1개와 세부 레퍼런스 디렉터리 1세트만 유지한다.
- 신규 문서는 가능하면 기존 통합 문서에 추가하고, 별도 파일 생성은 범위가 명확히 독립적일 때만 허용한다.
