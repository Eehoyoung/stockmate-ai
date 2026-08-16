# 전략군 통합 완료 감사 및 실전 canary 인계

## 결론

코드 구현, 전체 회귀, V55 적용, Docker live 배포와 즉시 롤백 준비는 완료됐다. 최종 승인에는 실제 KRX 5거래일 결과가 필요하므로 WP-10과 WP-12의 최종 성과 판정은 아직 진행 중이다.

## 현재 배포

- 배포 브랜치: `codex/strategy-family-consolidation`
- 배포 코드 checkpoint: `915b9c4`
- DB: Flyway V56 (V55 family 계보 + V56 version/source 계보)
- live 환경: `ENABLE_STRATEGY_FAMILY_LINEAGE=true`, `ENABLE_STRATEGY_FAMILY_SHADOW_SCORING=true`, `ENABLE_STRATEGY_FAMILY_LIVE_ROUTING=true`
- 비교점수는 관측값이고 주문/신호 라우팅은 live다.
- API, AI, Telegram, WebSocket, PostgreSQL, Redis health: 모두 healthy

## WP별 증거

| WP | 상태 | 현재 증거 | 잔여 사항 |
|---|---|---|---|
| WP-00 | 완료 | Git 기준점, 배포 전 DB/Redis/env/image 백업, 20일 DB 스냅샷 | 없음 |
| WP-01 | 완료 | Python/Java 중앙 catalog, 16/16 단일 family 매핑, canonical RR 테스트 | 없음 |
| WP-02 | 완료 | V55/V56 additive schema, legacy `strategy` 유지, lineage 4,064건 backfill | 없음 |
| WP-03 | 완료 | Kiwoom realtime/execution 우선, Toss 보조 계약, freshness/fallback 회귀 | 실제 거래일 rate budget 관찰 계속 |
| WP-04 | 완료 | 기존 setup scanner 유지, additive family lineage/router | family는 setup 규칙을 혼합하지 않음 |
| WP-05 | 완료 | 35/20/15/10/20 정규화 scorer, 상관 할인, dual score | 5거래일 분포 비교 대기 |
| WP-06 | 완료 | canonical effective RR, 비용 반영, TP1→PARTIAL_TP→TP2 상태전이 테스트 | 실제 체결 표본 대기 |
| WP-07 | 완료 | setup prompt + family guard, strict schema validator, mismatch fail-closed | live AI 실패율 관찰 |
| WP-08 | 완료 | family key→stock key 원자 예약, Redis 장애 fail-closed, theme exposure guard | 실제 동시신호 표본 대기 |
| WP-09 | 완료 | DB dual-write, G family API, Telegram family 표시와 `/filter g01~g07` alias | 없음 |
| WP-10 | 진행 중 | predeploy test/replay, canary monitor | 5 KRX 거래일 결과·성과지표 필요 |
| WP-11 | 진행 중 | live 배포, 세 kill switch, pre-family 이미지 tag, DB/Redis 백업 | 실제 rollback 조건 감시 |
| WP-12 | 진행 중 | 계획서, JSON prompt, rollback runbook, 본 감사서 | 5일 최종 보고서 추가 |

## 전체 회귀

- AI engine: 1,117 passed
- API orchestrator: Gradle 전체 test 성공
- WebSocket listener: 99 passed
- Telegram: commands 21, formatter 36, rate limiter 22 passed
- live API: family summary HTTP 200, 잘못된 `G99` HTTP 400

## 신규 소비자 계약

- `GET /api/trading/signals/performance/family/{G01..G07}`: 당일 family 신호
- `GET /api/trading/signals/performance/summary/family`: 당일 family 성과 집계
- 기존 S별 성과 API는 변경하지 않는다.
- Telegram `/filter g06 s4`처럼 G alias와 S alias를 함께 입력할 수 있으며 setup 목록으로 중복 없이 저장한다.
- V56은 `setup_version`, `rule_score_version`, `prompt_version`, confirming family, source/timestamp/age/fallback 계보를 정규 컬럼으로 보존한다.
- `.\scripts\report_strategy_family_canary.ps1`은 family/setup별 net expectancy, 95% CI, PF, MFE/MAE, realized RR drawdown, 시장·장세, overlap과 안전 위반을 동일 산식으로 생성한다.

## 20일 기준선

조회 시점 2026-08-16 KST, `trading_signals.created_at >= now()-20 days` 기준이다.

| setup | 신호 수 | WIN | LOSS | 평균 실현손익 |
|---|---:|---:|---:|---:|
| S1 | 82 | 0 | 0 | 없음 |
| S2 | 7 | 0 | 0 | 없음 |
| S3 | 19 | 0 | 0 | 없음 |
| S5 | 43 | 0 | 0 | 없음 |
| S6 | 20 | 0 | 0 | 없음 |
| S7 | 36 | 0 | 0 | 없음 |
| S8 | 67 | 0 | 0 | 없음 |
| S9 | 13 | 0 | 0 | 없음 |
| S11 | 722 | 0 | 0 | 없음 |
| S15 | 276 | 0 | 0 | 없음 |
| S4/S10/S12/S13/S14/S16 | 0 | 0 | 0 | 없음 |

총 1,285건이며 V55 backfill 이후 family/setup 계보 결측은 0건이다. 같은 기간 `trade_outcomes`는 0건이므로 과거 데이터만으로 expectancy, PF, MDD, MFE/MAE를 승인할 수 없다. 이 항목은 5거래일 결과에서도 표본 부족이면 “판정 불가”로 보고하며 임의로 양호 판정을 만들지 않는다.

## 즉시 롤백 조건

- family/setup 계보 누락 1건
- 동일 종목 활성 포지션 중복 1건
- 필수 stale/missing 데이터 ENTER 1건
- family/setup/AI schema 불일치가 ENTER로 통과 1건
- Redis family/stock 예약 장애 중 ENTER 1건
- TP1/TP2 상태 또는 주문·ACK·fill 계보 불일치 1건

점검 명령은 `.\scripts\monitor_strategy_family_canary.ps1`이다. 위 조건이면 결과가 `ROLLBACK_NOW`와 종료코드 2를 반환한다.

## 잔여 위험

- 장외 배포라 실제 주문·체결 표본은 아직 없다.
- 과거 20일에 6개 setup 신호와 전체 trade outcome이 없어 전략별 기대값 비교가 불가능하다.
- AI strict schema 도입 직후이므로 첫 거래일 `AI_SCHEMA_INVALID` 비율을 별도 확인해야 한다.
- 키움·Telegram 인증정보는 앞선 진단 출력에 노출됐으므로 운영자가 회전해야 한다. 회전 전까지 해당 자격증명의 보안 위험은 남아 있다.
