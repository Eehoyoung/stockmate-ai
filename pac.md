# StockMate AI - Project Agent Guide

This document is the current working guide for coding agents in this repository. It replaces the older `CLAUDE.md` assumptions with the repository state verified from source files, configuration, Dockerfiles, tests, and service entry points.

## Project Overview

StockMate AI is a Korean stock trading signal system built around Kiwoom REST/WebSocket data, Redis queues, PostgreSQL persistence, Claude-based analysis, and Telegram delivery.

Core data flow:

```text
Kiwoom WebSocket
      |
      v
websocket-listener (Python)
  - tick/expected/hoga data
  - VI events
  - optional direct Postgres event persistence
      |
      v
Redis
  - market data hashes
  - candidate pools
  - queue handoff
      ^
      |
api-orchestrator (Java/Spring)
  - Kiwoom REST API access and token refresh
  - strategy candidate publishing
  - schedulers, JPA domains, Flyway migrations
  - operational and trading-control APIs
      |
      v
telegram_queue
      |
      v
ai-engine (Python)
  - strategy scanner and candidate builder
  - rule scoring, TP/SL, RR checks
  - Claude analysis
  - news, monitoring, position reassessment, overnight workers
      |
      v
ai_scored_queue
      |
      v
telegram-bot (Node.js)
  - Telegram commands
  - signal/exit/status/news messages
  - human confirm actions
```

## Repository Layout

```text
stockmate-ai/
├── api-orchestrator/       Java 25 Spring Boot API, schedulers, JPA, Flyway
├── ai-engine/              Python async workers, strategies, scoring, Claude, tests
├── websocket-listener/     Python Kiwoom WebSocket listener, Redis/PG writers, tests
├── telegram-bot/           Node.js Telegraf bot, handlers, formatters, tests
├── docs/                   Design notes, API references, audits, operations reports
├── logs/                   Root-level logs; each service also has its own logs dir
├── docker-compose.yml      Full local/container stack
├── AGENTS.md               Repository coding guidelines
├── CLAUDE.md               Older guide retained for reference
└── pac.md                  This updated guide
```

Do not treat `websocket-listener/package.json` as the runnable listener. The listener is Python; that package file has no usable test script and appears unrelated to the active runtime.

## Common Commands

Start infrastructure only:

```bash
docker compose up -d redis postgres
```

Start the full stack:

```bash
docker compose up -d --build
```

Stop the full stack:

```bash
docker compose down
```

Java API:

```bash
cd api-orchestrator
./gradlew bootRun
./gradlew build
./gradlew test
./gradlew test --tests "ApiOrchestratorApplicationTests"
./gradlew test --tests "org.invest.apiorchestrator.util.StockCodeNormalizerTests"
```

Python AI engine:

```bash
cd ai-engine
pip install -r requirements.txt
python engine.py
python -m pytest tests -q
python -m pytest tests/test_queue_worker.py -q
```

Python WebSocket listener:

```bash
cd websocket-listener
pip install -r requirements.txt
python main.py
python -m pytest tests -q
```

Telegram bot:

```bash
cd telegram-bot
npm install
npm start
npm run dev
node tests/test_formatter.js
node tests/test_signals_rate_limiter.js
node tests/test_commands.js
npm run test:commands
```

`telegram-bot` has a default `npm test` script that intentionally exits with an error. Use the explicit Node test files above.

## Docker Stack

`docker-compose.yml` currently injects the root `.env` into every service. It does not use per-service `.env` files.

Services and health checks:

| Service | Runtime | Port | Health |
| --- | --- | ---: | --- |
| `redis` | Redis 7 Alpine | 6379 | `redis-cli -a $REDIS_PASSWORD ping` |
| `postgres` | PostgreSQL 16 Alpine | 5432 | `pg_isready` |
| `api-orchestrator` | Java 25 Spring Boot | 8080 | `/actuator/health` |
| `websocket-listener` | Python 3.11 | 8081 | `/health` |
| `ai-engine` | Python 3.11 | 8082 | `/health` |
| `telegram-bot` | Node 20 Alpine | exposes 3001 | `node src/healthcheck.js` |

Docker runtime notes:

- `api-orchestrator/Dockerfile` builds with `./gradlew bootJar -x test` and runs with `--enable-native-access=ALL-UNNAMED`.
- `ai-engine/Dockerfile` runs `python engine.py`.
- `websocket-listener/Dockerfile` runs `python main.py`.
- `telegram-bot/Dockerfile` runs `node src/index.js` and installs production dependencies with `npm ci --omit=dev`.
- Compose sets `TZ=Asia/Seoul`.
- Compose sets `API_ORCHESTRATOR_BASE_URL=http://api-orchestrator:8080` and `AI_ENGINE_URL=http://ai-engine:8082` for bot/AI communication.
- Compose pins `api.telegram.org` to `149.154.166.110` and sets `NODE_OPTIONS=--dns-result-order=ipv4first` for Telegram networking.

## Environment Configuration

Root `.env.example` is the active template. Important groups:

Kiwoom:

- `KIWOOM_APP_KEY`
- `KIWOOM_APP_SECRET`
- `KIWOOM_BASE_URL`
- `KIWOOM_WS_URL`
- `KIWOOM_MODE`
- `JAVA_WS_ENABLED`
- `KIWOOM_API_INTERVAL`

Claude:

- `CLAUDE_API_KEY`
- `CLAUDE_MODEL`
- `MAX_CLAUDE_CALLS_PER_DAY`
- `CLAUDE_ANALYST_TIMEOUT_SEC`
- `CLAUDE_ANALYST_MINUTE_SCOPE`

Telegram:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_DRY_RUN`
- `POLL_INTERVAL_MS`
- `MIN_AI_SCORE`

Redis/PostgreSQL:

- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `PG_WRITER_ENABLED`

AI engine feature flags and timings:

- `ENABLE_STRATEGY_SCANNER`
- `ENABLE_MONITOR`
- `ENABLE_STATUS_REPORT`
- `ENABLE_POSITION_MONITOR`
- `ENABLE_POSITION_REASSESSMENT`
- `ENABLE_OVERNIGHT_WORKER`
- `ENABLE_VI_WATCH_WORKER`
- `ENABLE_CANDIDATE_BUILDER`
- `ENABLE_CONFIRM_GATE`
- `STRATEGY_SCAN_INTERVAL_SEC`
- `MAX_CONCURRENT_STRATEGIES`
- `STRATEGY_TIMEOUT_SEC`
- `STRATEGY_TIMEOUT_S3_SEC`
- `STRATEGY_TIMEOUT_S11_SEC`
- `SLOW_STRATEGY_WARN_SEC`
- `CANDIDATE_BUILD_INTERVAL_SEC`
- `MONITOR_INTERVAL_SEC`
- `STATUS_REPORT_SLOTS`
- `POSITION_MONITOR_INTERVAL_SEC`
- `POSITION_REASSESS_INTERVAL_SEC`
- `OVERNIGHT_POLL_SEC`

Risk, scoring, and TP/SL:

- `AI_SCORE_THRESHOLD`
- `HOLD_TO_ENTER_MIN_AI_SCORE`
- `RR_HARD_CANCEL_THRESHOLD`
- `RR_CAUTION_THRESHOLD`
- `MIN_RR_RATIO`
- `TP_SL_STRATEGY_VERSION`
- `SLIP_FEE_KOSPI`
- `SLIP_FEE_KOSDAQ`
- `SWING_STRATEGIES`
- `SWING_SIGNAL_DEDUP_SEC`
- `INTRADAY_SIGNAL_DEDUP_SEC`
- `STATUS_SIGNAL_TTL_SEC`

News:

- `NEWS_ENABLED`
- `NEWS_INTERVAL_MIN`
- `NEWS_TRADING_CONTROL`
- `NEWS_SECTOR_FILTER`
- `NEWS_MAX_ITEMS`
- `MAX_NEWS_CLAUDE_CALLS`

## Redis Keys and Queues

Primary queues:

| Key | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `telegram_queue` | api-orchestrator, ai-engine strategy scanner | ai-engine `queue_worker` | Candidate signals for scoring/analysis |
| `ai_scored_queue` | ai-engine | telegram-bot | Final signal, cancel, sell, status, and report payloads |
| `vi_watch_queue` | websocket-listener | ai-engine `vi_watch_worker` and strategy scanner | S2 VI pullback watch items |
| `confirmed_queue` | telegram-bot | ai-engine confirm worker path | Human-approved analysis payloads |
| `human_confirm_queue` | ai-engine | telegram-bot confirm poller | Human confirmation requests |
| `error_queue` | ai-engine and related workers | ops/status views | Failed payloads and processing errors |

Candidate and market keys:

- `candidates:s{N}:{market}`: strategy-specific candidate pools, for example `candidates:s1:001`, `candidates:s8:101`.
- `candidates:001`, `candidates:101`: legacy/general candidate keys still referenced by some status and fallback paths.
- `kiwoom:token`: Kiwoom REST/WebSocket token written by the Java side and read by Python workers.
- `ws:tick:{stkCd}`: latest tick snapshot.
- `ws:hoga:{stkCd}`: latest order-book snapshot.
- `ws:heartbeat`: listener liveness signal.
- `ws:subscriptions:*`: WebSocket subscription tracking.
- `status:*`, `pipeline_daily:*`, `daily_summary:*`: status/reporting counters.
- `claude:daily_calls:{date}`, `claude:daily_tokens:{date}`: Claude usage counters.

## api-orchestrator

Path: `api-orchestrator/`

Stack:

- Java 25 toolchain
- Spring Boot 4.0.3
- Spring Batch
- Spring Data JPA
- Spring Data Redis
- Spring Web MVC and WebClient
- OkHttp 5.3.2
- PostgreSQL
- Flyway
- Lombok

Package root:

```text
org.invest.apiorchestrator
```

Important files:

- `src/main/java/org/invest/apiorchestrator/ApiOrchestratorApplication.java`
- `src/main/java/org/invest/apiorchestrator/ApplicationStartupRunner.java`
- `src/main/resources/application.yml`
- `src/main/resources/logback-spring.xml`
- `src/main/resources/db/migration/`
- `build.gradle`
- `Dockerfile`

Main package structure:

- `config/`: Redis, JPA, Flyway, WebClient, Kiwoom properties/rate limiter, async, object mapper.
- `controller/`: `TradingController`.
- `domain/`: JPA entities for signals, positions, score components, market context, news, risk, token, VI and WebSocket data.
- `dto/req`, `dto/res`: request/response DTOs.
- `exception/`: global exception handling and Kiwoom API exceptions.
- `repository/`: Spring Data repositories.
- `scheduler/`: trading, token, stock master, position, performance, news, data quality/persistence/cleanup, economic calendar, health, and confirmation cleanup schedulers.
- `service/`: Kiwoom API/stock services, strategy and signal services, candidate service, Redis market data service, operations health, news control, overnight scoring, price/volume services.
- `util/`: stock-code normalization, KST clock, market time helpers.

Key controller base path:

```text
/api/trading
```

Notable API routes include:

- `POST /token/refresh`
- `GET /signals/today`
- `GET /signals/stats`
- `GET /signals/performance`
- `GET /signals/performance/summary`
- `GET /signals/stock/{stkCd}`
- `GET /signals/strategy-analysis`
- `POST /strategy/s1/run`
- `POST /strategy/s2/run`
- `POST /strategy/s3/run`
- `POST /strategy/s4/run`
- `POST /strategy/s5/run`
- `POST /strategy/s6/run`
- `POST /strategy/s7/run`
- `POST /strategy/s10/run`
- `POST /strategy/s12/run`
- `GET /candidates`
- `GET /candidates/pool-status`
- `GET /score/{stkCd}`
- `GET /strategy-params/{strategy}`
- `POST /strategy-params`
- `GET /monitor/health`
- `GET /db/table-status`
- `POST /control/{mode}`
- `GET /calendar/week`
- `GET /calendar/today`
- `POST /calendar/event`
- `POST /ws/connect`, `/ws/start`, `/ws/disconnect`, `/ws/stop`
- `GET /health`

Scheduling is KST-based. Important schedulers include `TradingScheduler`, `TokenRefreshScheduler`, `StockMasterScheduler`, `PositionMonitorScheduler`, `SignalPerformanceScheduler`, `OvernightRiskScheduler`, `OvernightEvaluationVerificationScheduler`, `NewsAlertScheduler`, `EconomicCalendarScheduler`, `DataPersistenceScheduler`, `DataQualityScheduler`, `DataCleanupScheduler`, `CandidatePoolHistoryScheduler`, `StrategyParamSnapshotScheduler`, `HumanConfirmCleanupScheduler`, and `SystemHealthLogScheduler`.

Database:

- Active migrations are under `src/main/resources/db/migration/`.
- Verified migration range is `V1__baseline_existing_schema.sql` through `V36__add_market_cap_to_stock_master.sql`.
- There is also `src/main/migration/V1__.sql`; do not confuse it with the active Flyway location.
- `application.yml` currently uses `spring.jpa.hibernate.ddl-auto: validate`.
- `spring.flyway.validate-on-migrate: false` is intentionally set.
- Do not switch `ddl-auto` to `create`.

## ai-engine

Path: `ai-engine/`

Stack:

- Python async runtime
- `anthropic==0.96.0`
- `langchain==1.2.15`
- `langchain-anthropic==1.4.1`
- `redis==7.4.0`
- `httpx==0.28.1`
- `aiohttp==3.13.5`
- `asyncpg==0.31.0`
- `feedparser==6.0.12`
- `pytest==9.0.3`

Entry point:

```bash
python engine.py
```

`engine.py` starts Redis, optional PostgreSQL pool, health server, and feature-flagged workers:

- `queue_worker.run_worker`
- `health_server.run_health_server`
- `confirm_worker.run_confirm_worker` when confirm gate is enabled in the code path
- `strategy_runner.run_strategy_scanner`
- `news_scheduler.run_news_scheduler`
- `monitor_worker.run_monitor`
- `status_report_worker.run_status_report_worker`
- `position_monitor.run_position_monitor`
- `position_reassessment.run_position_reassessment`
- `overnight_worker.run_overnight_worker`
- `vi_watch_worker.run_vi_watch_worker`
- `candidates_builder.run_candidate_builder`

Core files:

- `config.py`: Redis, PostgreSQL, Kiwoom, Claude config.
- `queue_worker.py`: consumes `telegram_queue`, applies scoring/analysis path, promotes high-score Claude `HOLD` decisions when eligible, emits to `ai_scored_queue` or `error_queue`.
- `confirm_worker.py`: Claude confirmation worker, RR hard-cancel handling, and the same high-score `HOLD` promotion policy used by `queue_worker`.
- `confirm_gate_redis.py`: human-confirm queue helpers.
- `analyzer.py`: Claude/rule analysis helpers.
- `claude_analyst.py`: deeper stock analysis for commands and reassessment.
- `scorer.py`: rule scoring and Claude call budget logic.
- `stockScore.py`: multi-strategy stock scoring used by API/bot analysis paths.
- `tp_sl_engine.py`: TP/SL and RR policy.
- `price_utils.py`: stock-code and price helpers.
- `redis_reader.py`: Redis connection and queue helpers.
- `db_reader.py`, `db_writer.py`: PostgreSQL read/write helpers.
- `health_server.py`: AI health endpoint.
- `monitor_worker.py`: queue/system monitoring.
- `status_report_worker.py`: scheduled status reports.
- `position_lifecycle.py`, `position_monitor.py`, `position_reassessment.py`: open-position lifecycle and sell/reassessment logic.
- `overnight_worker.py`, `overnight_scorer.py`: overnight evaluation.
- `news_collector.py`, `news_analyzer.py`, `news_scheduler.py`: news ingestion/analysis/control.
- `candidates_builder.py`: strategy-specific candidate-pool builder.
- `strategy_runner.py`: timed Python strategy scanner.
- `vi_watch_worker.py`: VI watch processing for S2.
- `http_utils.py`: Kiwoom HTTP helpers, including response validation.
- `ma_utils.py`: moving-average and candle utilities.

Strategies:

| File | Strategy |
| --- | --- |
| `strategy_1_gap_opening.py` | `S1_GAP_OPEN` |
| `strategy_2_vi_pullback.py` | `S2_VI_PULLBACK` |
| `strategy_3_inst_foreign.py` | `S3_INST_FRGN` |
| `strategy_4_big_candle.py` | `S4_BIG_CANDLE` |
| `strategy_5_program_buy.py` | `S5_PROG_FRGN` |
| `strategy_6_theme.py` | `S6_THEME_LAGGARD` |
| `strategy_7_ichimoku_breakout.py` | `S7_ICHIMOKU_BREAKOUT` |
| `strategy_8_golden_cross.py` | `S8_GOLDEN_CROSS` |
| `strategy_9_pullback.py` | `S9_PULLBACK_SWING` |
| `strategy_10_new_high.py` | `S10_NEW_HIGH` |
| `strategy_11_frgn_cont.py` | `S11_FRGN_CONT` |
| `strategy_12_closing.py` | `S12_CLOSING` |
| `strategy_13_box_breakout.py` | `S13_BOX_BREAKOUT` |
| `strategy_14_oversold_bounce.py` | `S14_OVERSOLD_BOUNCE` |
| `strategy_15_momentum_align.py` | `S15_MOMENTUM_ALIGN` |

Indicator modules:

- `indicator_rsi.py`
- `indicator_macd.py`
- `indicator_bollinger.py`
- `indicator_stochastic.py`
- `indicator_atr.py`
- `indicator_volume.py`
- `indicator_ichimoku.py`

Strategy metadata:

- `strategy_meta.py` is the central source for swing/day classification and Claude thresholds.
- Day strategies: `S1_GAP_OPEN`, `S2_VI_PULLBACK`, `S4_BIG_CANDLE`, `S6_THEME_LAGGARD`.
- Default swing strategies: `S3_INST_FRGN`, `S5_PROG_FRGN`, `S7_ICHIMOKU_BREAKOUT`, `S8_GOLDEN_CROSS`, `S9_PULLBACK_SWING`, `S10_NEW_HIGH`, `S11_FRGN_CONT`, `S12_CLOSING`, `S13_BOX_BREAKOUT`, `S14_OVERSOLD_BOUNCE`, `S15_MOMENTUM_ALIGN`.

Claude action promotion:

- `queue_worker.py` and `confirm_worker.py` both apply the same final-action promotion rule.
- If Claude returns `action == "HOLD"` and `ai_score >= HOLD_TO_ENTER_MIN_AI_SCORE`, the final payload action is promoted to `ENTER`.
- The default `HOLD_TO_ENTER_MIN_AI_SCORE` is `80.0`.
- Promotion changes the final action before Telegram delivery; this is not just a formatter/notification override.
- When promoted, `cancel_reason` is cleared, confidence falls back to `HIGH` if missing, and the reason text is appended with `HOLD promoted to ENTER because ai_score ...`.
- Lower-score `HOLD` decisions remain `HOLD`.
- Queue-worker behavior is covered by `ai-engine/tests/test_queue_worker.py::TestProcessQueueItem::test_high_score_hold_is_promoted_to_enter`.

Scanner schedule in `strategy_runner.py`:

- S1: 08:30-09:10
- S2: 09:00-14:50
- S3: 09:30-14:30
- S4: 09:30-14:30
- S5: 10:00-14:00
- S6: 09:30-13:00
- S7: 10:00-14:30
- S8: 10:00-14:30
- S9: 09:30-13:00
- S10: 09:30-14:30
- S11: 09:30-14:30
- S12: 14:30-15:10
- S13: 09:30-14:00
- S14: 09:30-14:00
- S15: 10:00-14:30

Tests live in `ai-engine/tests/`, including coverage for scorer, queue worker, strategy runner, Redis connection helpers, HTTP utilities, analyzer paths, position reassessment, status reports, price utilities, TP/SL, and stock-code normalization.

## websocket-listener

Path: `websocket-listener/`

Stack:

- Python async runtime
- `websockets==16.0`
- `aiohttp==3.13.5`
- `redis==7.4.0`
- `asyncpg==0.30.0`
- `pytest==9.0.3`

Entry point:

```bash
python main.py
```

Core files:

- `main.py`: loads `.env`, sets logging, connects Redis, optionally creates PostgreSQL pool, starts WebSocket loop and health server.
- `ws_client.py`: Kiwoom WebSocket client, subscription phases, reconnect behavior, dynamic subscriptions.
- `redis_writer.py`: writes tick, expected, hoga, VI, heartbeat, and subscription state to Redis.
- `db_writer.py`: optional direct Postgres persistence for tick and VI events.
- `token_loader.py`: loads Kiwoom token from Redis.
- `health_server.py`: HTTP health endpoint.
- `logger.py`: JSON-style service logging helper.

Runtime details:

- Health defaults to `HEALTH_PORT=8081`.
- `PG_WRITER_ENABLED=true` enables direct event persistence.
- `BYPASS_MARKET_HOURS=true` allows running outside normal market hours for testing.
- `JAVA_WS_ENABLED=false` means the Python listener owns Kiwoom GRP 1-4.
- `JAVA_WS_ENABLED=true` shifts the Python listener away from the Java WebSocket group assignment to avoid group collisions.

Tests live in `websocket-listener/tests/`:

- `test_failure_reproduction.py`
- `test_mttr.py`
- `test_reconnect_scenarios.py`

## telegram-bot

Path: `telegram-bot/`

Stack:

- Node.js CommonJS
- Telegraf 4.x
- ioredis
- axios
- pg
- dotenv

Entry point:

```bash
node src/index.js
```

Core files:

- `src/index.js`: loads env, enforces allowed chats, registers commands/actions, starts signal polling and health server.
- `src/health.js`: in-process health server.
- `src/healthcheck.js`: Docker healthcheck for Redis/Postgres/API/AI connectivity.
- `src/handlers/commands.js`: Telegram command handlers.
- `src/handlers/signals.js`: polls `ai_scored_queue`, formats and sends messages, rate limits.
- `src/handlers/confirmGate.js`: human confirmation polling/sending.
- `src/services/redis.js`: ioredis client and helpers.
- `src/services/kiwoom.js`: API-orchestrator client calls.
- `src/services/confirmStore.js`: confirmation state persistence.
- `src/utils/formatter.js`: Telegram HTML message formatting.
- `src/utils/logger.js`: JSON logger.
- `src/utils/price.js`: price helpers.

Registered commands include:

- `/ping`
- `/health`, `/status`
- `/signals`
- `/perf`
- `/track`
- `/analysis`
- `/history`
- `/quote`
- `/score`
- `/claude`
- `/candidates`
- `/report`
- `/news`
- `/sector`
- `/events`
- `/settings`
- `/filter`
- `/watchAdd`
- `/watchRemove`
- `/confirmPending`
- `/reanalyze`
- `/pause`
- `/resume`
- `/errors`
- `/strategy`
- `/token`
- `/wsStart`
- `/wsStop`
- `/help`, `/start`

Callback actions include trading pause confirmation and human-confirm yes/no actions.

Tests:

- `tests/test_formatter.js`
- `tests/test_signals_rate_limiter.js`
- `tests/test_commands.js`

## Kiwoom API Handling

Kiwoom REST API can return application errors inside HTTP 200 responses. Do not rely only on HTTP status.

Valid response handling:

- Normal: `return_code == "0"`.
- API error: `return_code != "0"`.
- Server/internal style error body: payload contains an `error` key, for example `{"error":"INTERNAL_SERVER_ERROR","status":500,...}`.

Python strategy and candidate-builder code should call:

```python
validate_kiwoom_response(data, api_id, logger)
```

from `ai-engine/http_utils.py` before trusting Kiwoom payloads.

## Logging

The project is intended to use structured service loggers rather than raw output in production code.

Guidelines:

- Python services use `logging` or the service `logger.py` helper.
- Telegram bot uses `src/utils/logger.js`.
- Java uses Logback/Spring logging.
- Avoid adding `print()` or `console.log()` in runtime paths. Existing test scripts may use console output.
- Preserve `request_id` and `signal_id` fields when touching queue payloads.
- See `docs/logging_standards.md` for schema and level expectations.

Important correlation fields:

| Field | Origin | Expected propagation |
| --- | --- | --- |
| `request_id` | api-orchestrator REST/API path | api-orchestrator -> ai-engine -> telegram-bot |
| `signal_id` | signal creation/scoring path | ai-engine -> telegram-bot -> DB/Redis payloads |

## Persistence Model

PostgreSQL is used by both Java and Python components.

Key entity/table areas visible from source:

- Trading signals and signal score components
- Open positions and position state events
- Trade plans and trade outcomes
- Kiwoom tokens
- VI events and WebSocket tick data
- Stock master
- Candidate pool history
- Strategy parameter history and daily stats
- Market daily context and daily indicators
- Portfolio config and daily PnL
- Risk events
- News analysis and economic events
- Overnight evaluations
- Human confirm requests

The current schema has been actively migrated through V36. Before editing persistence code, inspect both the entity/repository and the relevant Flyway migration history.

## Coding Style

Follow local style per service:

- Python: 4-space indentation, `snake_case`, async-first patterns, existing logger/config helpers.
- Java: 4-space indentation, `PascalCase` classes, Spring service/repository/controller layering, Lombok where already used.
- JavaScript: CommonJS, semicolon style, `camelCase`, existing service/handler/utils layout.
- Strategy files should stay named `strategy_<n>_<name>.py`.
- Do not introduce a formatter churn pass across unrelated files.
- Keep changes scoped to the owning service and tests.

## Testing Guidance

Add tests beside the affected service:

- Python: `test_*.py` under the service `tests/`.
- Java: `*Tests.java` under `api-orchestrator/src/test/java`.
- Node: extend executable files under `telegram-bot/tests/`.

Prefer mocks/fakes for Redis, Kiwoom HTTP, Telegram, PostgreSQL, and Claude calls unless the task explicitly requires integration testing.

Java context-load tests can require live PostgreSQL and Redis. Use targeted tests when possible.

## Operational Notes

- The system is KST-oriented. Scheduling, logs, and DB session time zones are intended to use `Asia/Seoul`.
- `api-orchestrator` must refresh/store Kiwoom token before Python scanners can call Kiwoom APIs.
- `ENABLE_STRATEGY_SCANNER=false` disables the Python strategy scanner but does not disable queue processing.
- `ENABLE_CANDIDATE_BUILDER=true` lets ai-engine maintain candidate pools from Kiwoom REST APIs.
- S2 depends on VI events from the WebSocket listener and candidate pool supplementation.
- `CLAUDE_API_KEY` is required by `ai-engine`; `engine.py` exits if it is missing.
- `telegram-bot` exits if `TELEGRAM_BOT_TOKEN`, `API_ORCHESTRATOR_BASE_URL`, and an allowed chat id are missing.
- `MIN_AI_SCORE` in the bot controls message sending threshold; AI/scorer thresholds are separately controlled in Python.
- `strategy_meta.py` thresholds control when low rule scores skip Claude and become normal `CANCEL` decisions.
- `HOLD_TO_ENTER_MIN_AI_SCORE` controls final-action promotion for Claude `HOLD` results in both automatic queue processing and human-confirmed Claude processing. Default is `80.0`.
- S10 and other strategies may cancel below threshold as expected filter behavior, not necessarily an error.
- Queue payloads may include signal, cancel, sell recommendation, status, news, and report message types. Check `telegram-bot/src/handlers/signals.js` and `formatter.js` before changing payload shapes.

## Security

- Do not commit real `.env` secrets.
- Use `.env.example` as a template.
- Keep Kiwoom, Claude, Telegram, Redis, and PostgreSQL credentials local.
- Mention any new environment variable in docs and PR notes.
- Be careful with trading-control paths such as `/control/{mode}`, Telegram `/pause`, `/resume`, and human confirm callbacks.

## Documentation Map

Important docs currently present:

- `docs/README.md`
- `docs/logging_standards.md`
- `docs/operations-and-security.md`
- `docs/project-capabilities.md`
- `docs/project-process.md`
- `docs/project-review.md`
- `docs/project_deep_dive_report_2026-04-23.md`
- `docs/candidate-pool-architecture.md`
- `docs/candidate_selection_report.md`
- `docs/strategy_thresholds.md`
- `docs/all_strategies_flow.md`
- `docs/strategy-consolidation.md`
- `docs/tp_sl_plan.md`
- `docs/tp_sl_per_strategy_plan.md`
- `docs/tp_sl_rr_policy_by_strategy_2026-04-26.md`
- `docs/tp_sl_rr_policy_multi_agent_review_2026-04-26.md`
- `docs/crud_flow_audit_2026-04-25.md`
- `docs/crud_flow_audit_2026-04-26.md`
- `docs/docker_internal_communication_and_healthchecks_2026-04-25.md`
- `docs/kiwoom_api_reference.md`
- `docs/error_codes.md`
- `docs/api/`
- `docs/candidate/`
- `docs/rank_info/`

Several Korean Markdown reports also exist at the repository root. Treat them as project context, but verify against code before relying on older plans.

## Agent Workflow Rules

When working in this repository:

1. Inspect the owning service before editing.
2. Preserve existing user changes in the git worktree.
3. Do not revert unrelated dirty files.
4. Use `rg`/`rg --files` for discovery.
5. Use service-specific tests, not broad live integration tests, unless necessary.
6. Keep queue schemas backward-compatible unless all producers and consumers are updated together.
7. For Kiwoom response handling, validate HTTP 200 bodies.
8. For DB changes, add or update Flyway migrations and keep entities/repositories aligned.
9. For Telegram-facing text changes, update formatter or handler tests and include sample output in PR notes.
10. For strategy changes, consider candidate-pool keys, scanner schedule, dedup TTL, scoring threshold, TP/SL, and downstream Telegram formatting.
