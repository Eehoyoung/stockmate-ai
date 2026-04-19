# Table Persistence Completion 2026-04-16

## 완전 적재 기준

- `CandidatePoolHistory`: 후보풀 스냅샷과 실제 신호 연결 여부가 함께 남아야 한다.
- `DailyIndicators`: 대상 종목 전체에 대해 같은 날짜 재수집 시에도 중복 오류 없이 최신 값으로 갱신되어야 한다.
- `DailyPnl`: 일별 총 신호, 손익, 시장 컨텍스트 요약이 함께 저장되어야 한다.
- `EconomicEvent`: 캘린더 수집 결과가 날짜 기준으로 저장되어야 한다.
- `KiwoomToken`: 현재 유효 토큰과 만료 시각이 저장되어야 한다.
- `MarketDailyContext`: 뉴스, 경제 일정, 지수/거래대금, 상승하락 폭, 수급, 일중 성과 요약이 한 행에 유지되어야 한다.
- `NewsAnalysis`: 뉴스 분석 결과와 통제 신호가 저장되어야 한다.
- `OpenPosition`: 진입 이후 활성 포지션 상태가 계속 갱신되어야 한다.
- `OvernightEvaluation`: 당일 평가 정보와 다음날 시가 검증 결과까지 저장되어야 한다.
- `PortfolioConfig`: 현재 리스크/자본 설정이 단일 기준행으로 유지되어야 한다.
- `RiskEvent`: 차단 및 제한 이벤트가 사유와 함께 저장되어야 한다.
- `SignalScoreComponents`: Python 점수 구성요소가 신호별로 저장되어야 한다.
- `StockMaster`: 활성 종목 마스터가 유지되어야 한다.
- `StrategyDailyStat`: 전략별 일일 성과와 임계값 기준 통계가 저장되어야 한다.
- `StrategyParamHistory`: 현재 운영 파라미터의 스냅샷과 변경 이력이 누적되어야 한다.
- `TradingSignal`: 신호 생성부터 청산 결과까지 저장되어야 한다.
- `ViEvent`: 모든 VI 실시간 이벤트가 이벤트 단위로 저장되어야 한다.
- `WsTickData`: `0B/0D/0H` 실시간 메시지가 이벤트 단위로 저장되어야 한다.

## 이번 수정

- `websocket-listener`가 Redis 저장과 동시에 PostgreSQL에 `ws_tick_data`, `vi_events`를 직접 기록하도록 변경했다.
- direct event writer가 살아 있는 동안 Java 분당 snapshot 저장은 자동으로 비활성화되도록 `ws:db_writer:event_mode` 플래그를 추가했다.
- `DailyIndicators`는 `(date, stk_cd)` 기준으로 안전하게 UPSERT 되도록 수정했다.
- `MarketDailyContext`는 KOSPI/KOSDAQ proxy 종목, breadth, 외국인/기관 순매수, VIX 상당값, 당일 성과 요약까지 함께 저장하도록 확장했다.
- `DailyPnl`, `StrategyDailyStat`는 시장 컨텍스트와 임계값 스냅샷, 추가 성과 지표를 함께 저장하도록 확장했다.
- `OvernightEvaluation`는 RSI, 정배열 여부, bid ratio, score components, Java overnight score를 저장하고 다음날 시가 검증 스케줄러를 추가했다.
- `StrategyParamHistory`는 부팅 시 1회 메타 기록에서 끝나지 않고 운영 파라미터 스냅샷을 정기 저장하도록 변경했다.
- `docker-compose.yml`에 `websocket-listener -> postgres` 연결 환경변수를 추가했다.

## 남는 운영 조건

- `WsTickData`, `ViEvent`의 완전 적재는 `websocket-listener`가 PostgreSQL에 연결 가능한 환경이어야 한다.
- `MarketDailyContext`의 breadth와 수급은 일부 Redis/REST proxy 데이터를 조합해 계산하므로, 장중 원천데이터 부재 시 일부 컬럼은 `null`일 수 있다.
- `DailyIndicators` 적재 범위는 관심종목, 활성종목, 당일 신호/포지션 종목 전체를 합친 집합 기준이다.

## 검증

- `python -m py_compile websocket-listener/main.py websocket-listener/db_writer.py websocket-listener/redis_writer.py websocket-listener/ws_client.py ai-engine/db_writer.py ai-engine/overnight_worker.py`
- `cd api-orchestrator && ./gradlew compileJava`
- `docker compose build`
