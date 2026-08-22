# 전략군 통합 완료 감사 및 실전 canary 인계

## 결론

코드 구현, 전체 회귀와 Docker 배포는 완료됐다. 2026-08-22 감사에서 과거 ENTER 2건의 source timestamp 계보 누락을 확인해 승인 규칙대로 live family 라우팅을 즉시 차단했고, 원인 수정·전체 회귀·재배포 후 새 관찰창으로 재승격했다. 최종 승인에는 새 관찰창의 실제 KRX 5거래일 결과가 필요하므로 WP-10~WP-12는 진행 중이다.

## 현재 배포

- 배포 브랜치: `codex/strategy-family-consolidation`
- 배포 코드 checkpoint: `bf9ebe1`
- DB: Flyway V56 (V55 family 계보 + V56 version/source 계보)
- 현재 환경: `ENABLE_STRATEGY_FAMILY_LINEAGE=true`, `ENABLE_STRATEGY_FAMILY_SHADOW_SCORING=true`, `ENABLE_STRATEGY_FAMILY_LIVE_ROUTING=false`
- 2026-08-22 ENTER 사후분석에서 family hard gate 우회를 추가 확인해 새 canary를 중단했다.
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
| WP-10 | 진행 중 | predeploy test/replay, canary monitor, 4개 개장일 관찰 | 계보 수정 후 새 5 KRX 거래일 결과·성과지표 필요 |
| WP-11 | 진행 중 | live 배포, 계보 위반 감지 후 논리 롤백 실행, pre-family 이미지 tag, DB/Redis 백업 | 새 canary 재승격 전 gate 재검증 |
| WP-12 | 진행 중 | 계획서, JSON prompt, rollback runbook, 본 감사서 | 새 5일 최종 보고서 추가 |

## 전체 회귀

- AI engine: 1,117 passed
- API orchestrator: Gradle 전체 test 성공
- WebSocket listener: 99 passed
- Telegram: commands 21, formatter 36, rate limiter 22 passed
- live API: family summary HTTP 200, 잘못된 `G99` HTTP 400

## 실행 프롬프트 필수 테스트 추적

| 필수 계약 | 직접 증거 | 판정 |
|---|---|---|
| 16 setup이 정확히 한 family에 매핑 | `test_strategy_catalog.py::test_catalog_maps_all_16_setups_exactly_once` | 충족 |
| 알 수 없는 family/setup fail closed | `test_strategy_catalog.py::test_unknown_setup_and_number_fail_closed`, family API G99 test | 충족 |
| S2 event 경로 유지 | `test_strategy_runner.py::test_s2_not_scheduled_in_strategy_runner`, `test_vi_watch_worker.py` | 충족 |
| S12 overnight가 S1/S2에 전파되지 않음 | session별 catalog/policy·runner tests | 충족 |
| 동일 종목 복수 setup 주문계획 1개 | `test_queue_worker.py::test_second_strategy_for_same_stock_is_blocked` 및 family reservation tests | 충족 |
| ACTIVE/PARTIAL_TP/OVERNIGHT 신규주문 차단 | `TradingSignalRepositoryPositionGuardTests::everyLivePositionStateBlocksAnotherEntry` | 충족 |
| stale Kiwoom ENTER 금지 | `test_signal_readiness_gate.py`, `test_rest_enter_guard.py`, source lineage guard test | 충족 |
| Toss 부재가 사실을 만들지 않음 | `test_family_scoring.py::test_optional_toss_absence_is_degraded_without_blocking` | 충족 |
| Kiwoom HTTP 200 오류본문 실패 | `test_http_utils.py`, `KiwoomResponseContractTests` | 충족 |
| Kiwoom/Toss candle 부분병합 금지 | `test_ma_utils.py::test_fallback_replaces_when_toss_has_more_candles` | 충족 |
| rule component clamp | `test_family_scoring.py::test_component_caps_sum_to_100` | 충족 |
| 상관 확증 할인 | `test_family_scoring.py::test_independent_confirmation_is_larger_but_total_is_capped` | 충족 |
| AI HOLD는 WATCH | queue worker와 scoring pipeline HOLD tests | 충족 |
| AI hard gate/RR 우회 금지 | queue worker Claude RR·geometry tests | 충족 |
| TP1 partial 상태전이 | `test_position_monitor.py::test_tp1_with_second_target_transitions_to_partial_tp` | 충족 |
| queue→DB→API→Telegram 계보 | 공통 `test-fixtures/strategy_family_lineage.json`을 Python queue/DB, Java API 직렬화, Telegram formatter가 함께 검증 | 충족 |
| legacy S와 G query 동시 제공 | `TradingControllerPythonStrategyProxyTests::familySummaryUsesFamilyAggregationWithoutChangingLegacySummary` | 충족 |
| rollback이 데이터 손실 없이 legacy 판정 복구 | TP/SL·RR kill-switch tests와 additive migration test | 충족 |

18개 필수 계약의 직접 테스트 증거가 모두 존재한다. 이는 구조·전달 계약의 증거이며, WP-10의 실제 5거래일 성과·안전 관찰을 대체하지 않는다.

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

## 2026-08-22 롤백 사건

- 최초 관찰창(2026-08-16 23:37 KST 이후)에서 392개 신호를 확인했다. family/setup 계보 결측, 중복 활성 종목, stale ENTER는 0건이었다.
- ENTER 2건(`trading_signals.id` 4379, 4424)은 `data_source`와 `source_age_ms`가 있었지만 `source_timestamp`가 비어 있었다. 두 건 모두 S11/G02이며 현재 활성 포지션은 없다.
- 원인은 REST/신호 fallback freshness가 `updated_at_ms`를 만들지 않아 downstream timestamp 변환이 빈 객체가 된 것이었다.
- `bf9ebe1`에서 fallback 계보 생성기를 공통 보완하고, live family ENTER에 tick/hoga/strength source·timestamp·age가 모두 없으면 `SOURCE_LINEAGE_GUARD`로 차단하도록 수정했다.
- AI 전체 1,149 tests와 Java 전체 tests를 통과하고 API/AI 이미지를 재빌드했다. 2026-08-17은 `CLOSED`, 2026-08-18은 `OPEN`으로 historical calendar API가 판정한다.
- 과거 위반 행을 삭제하거나 소급 보정하지 않는다. 최초 관찰창 monitor는 계속 `ROLLBACK_NOW`를 반환한다.
- 2026-08-22 17:11:22 KST부터 새 canary를 시작했다. 재승격 직후 신호·위반은 모두 0, monitor 종료코드는 0이며 5거래일을 다시 채운다.

## 2026-08-22 ENTER 사후분석 추가 롤백

- 8월 18~21일 350개 신호 중 ENTER는 2건이며 모두 S11/G02 동일고무벨트였다.
- 두 ENTER의 `blocking_reasons`에 `REQUIRED_MARKET_DATA_UNUSABLE`이 있었지만 진입 판정으로 통과했다. 현재 family scorer도 이 사유를 shadow로만 기록하고 실전 진입 차단에 연결하지 않는다.
- 두 건은 실제 포지션·체결·성과가 없으며 EXPIRED 상태다. Kiwoom 가격 재생상으로는 두 계획 모두 1차 목표가 미도달 후 다음 거래일 손절가를 하회했다.
- 승인된 hard gate 우회 즉시 롤백 조건에 따라 family live routing을 다시 OFF로 전환하고 API·AI를 재생성했다. DB 자료는 보존됐고 모든 컨테이너 healthy다.
- 상세 분석과 재현 쿼리는 `analysis_enter_signals_2026-08-18_to_2026-08-21.md/.sql`에 기록했다.
