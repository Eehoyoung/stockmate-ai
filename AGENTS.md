# Repository Guidelines

## Project Structure & Module Organization
This repository is a multi-service trading system. `api-orchestrator/` contains the Spring Boot API, schedulers, JPA domains, and Flyway migrations under `src/main/resources/db/migration/`. `ai-engine/` holds Python scoring, candidate selection, queue workers, and pytest suites in `ai-engine/tests/`. `websocket-listener/` is a Python market-data listener with its own tests in `websocket-listener/tests/`. `telegram-bot/` contains the Node.js Telegram integration under `src/handlers/`, `src/services/`, and `src/utils/`. Use `docs/` for design notes, operational reports, and API references; keep generated logs in each service’s `logs/` directory.

## Build, Test, and Development Commands
Run infrastructure from the repo root with `docker compose up -d redis postgres`.
For Java:
`cd api-orchestrator && ./gradlew bootRun`
`cd api-orchestrator && ./gradlew test`
For Python:
`cd ai-engine && pip install -r requirements.txt && python -m pytest tests -q`
`cd websocket-listener && pip install -r requirements.txt && python -m pytest tests -q`
For Node:
`cd telegram-bot && npm install && npm run dev`
`cd telegram-bot && node tests/test_formatter.js`
`cd telegram-bot && node tests/test_signals_rate_limiter.js`
`websocket-listener/package.json` does not define a usable `npm test`; treat its executable tests as the Python pytest suite.

## Coding Style & Naming Conventions
Follow existing style per module: 4-space indentation in Python and Java, semicolon-based CommonJS in Node. Use `snake_case` for Python files and helpers, `PascalCase` for Java classes, and `camelCase` for JavaScript functions. Keep strategy modules named `strategy_<n>_<name>.py`. Favor small service-layer functions and reuse the shared logger/config utilities already present in each module. No formatter or linter is enforced in the repo today, so match surrounding code closely.

## Testing Guidelines
Add tests beside the owning service, using `test_*.py` for pytest and `*Tests.java` for Spring/JUnit. Prefer mocked Redis, HTTP, and AI clients over live integrations. For Telegram bot changes, extend the existing executable Node test files in `telegram-bot/tests/`.

## Commit & Pull Request Guidelines
Recent history uses short imperative subjects, usually with prefixes like `fix:` and `feat:`. Keep commits focused, for example `fix: guard empty Redis payload in scorer`. PRs should summarize affected services, list config or schema changes, link the issue or task, and include screenshots or sample bot output when user-facing messages change.

## Security & Configuration Tips
Do not commit real secrets from `.env`. Start from `.env.example`, keep Kiwoom, Redis, and Postgres credentials local, and call out new environment variables in both the PR and the relevant service docs.
