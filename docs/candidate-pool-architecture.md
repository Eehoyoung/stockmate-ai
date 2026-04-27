# Candidate Pool Architecture

후보풀 관련 계획서, 흐름 문서, 전략별 추천 상세 메모를 하나의 기준 문서로 정리한다.

## Objective

- 전략별 후보풀 생성 기준을 명확히 하고, 공통 구조 안에서 확장 가능하게 유지한다.
- 후보풀 생성, 저장, 추천, 텔레그램 노출까지의 흐름을 한 문서에서 설명한다.

## Core Flow

1. Kiwoom API와 시장 데이터 소스에서 전략별 원재료를 수집한다.
2. 전략별 필터로 1차 후보군을 만든다.
3. 공통 점수화와 정렬 규칙으로 우선순위를 계산한다.
4. Redis/DB에 후보풀을 저장하고, ai-engine과 telegram-bot이 재사용한다.
5. 최종 추천 단계에서 전략 태그와 보조 설명을 붙인다.

## Per-Strategy View

- 단기 급등/거래량/예상체결 기반 전략은 실시간성 우선으로 운용한다.
- 기관/외국인/프로그램 수급 전략은 누적 흐름과 당일 지속성 판단을 함께 본다.
- 테마/후발주/돌파 전략은 섹터 맥락과 가격 위치를 같이 반영한다.

## Design Rules

- 후보풀은 전략별 독립성을 유지하되 저장 포맷은 통일한다.
- 추천 사유는 사람이 읽을 수 있는 짧은 문장과 기계가 처리할 수 있는 태그를 함께 유지한다.
- 전략별 상세 기준은 새 파일을 늘리기보다 이 문서의 하위 섹션으로 추가한다.

## Related Docs

- 후보 선정 결과 요약: [candidate_selection_report.md](./candidate_selection_report.md)
- 전략 통합 기준: [strategy-consolidation.md](./strategy-consolidation.md)
- TP/SL 계획: [tp_sl_per_strategy_plan.md](./tp_sl_per_strategy_plan.md)
