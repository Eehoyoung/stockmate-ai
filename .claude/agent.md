# StockMate AI – Sub-Agent Index

서브에이전트 파일은 `.claude/agents/` 에 위치합니다. Claude Code가 작업 성격에 따라 자동 라우팅합니다.

## 에이전트 목록

| 에이전트 | 파일 | 담당 영역 |
|---------|------|---------|
| `strategy-dev` | `agents/strategy-dev.md` | S1–S15 전략 파일 개발·수정, 후보 풀 패턴, scorer 연동 |
| `docker-ops` | `agents/docker-ops.md` | Docker Compose 기동·재빌드·로그, 컨테이너 진단 |
| `kiwoom-api` | `agents/kiwoom-api.md` | Kiwoom REST/WebSocket 통합, 토큰, API 오류 대응 |
| `db-migration` | `agents/db-migration.md` | Flyway 마이그레이션 작성, JPA 엔티티 동기화 |
| `signal-debugger` | `agents/signal-debugger.md` | 신호 흐름 추적, Redis 큐 상태, 장애 진단 |
| `ai-scorer` | `agents/ai-scorer.md` | scorer.py 임계값·케이스, confirm_worker 프롬프트 |
| `telegram-dev` | `agents/telegram-dev.md` | 봇 커맨드·포매터·signals 폴링 로직 개발 |

## 에이전트 선택 가이드

```
전략 파일(strategy_*.py) 수정        → strategy-dev
Docker / 컨테이너 운영               → docker-ops
Kiwoom API 연동 / 토큰               → kiwoom-api
DB 스키마 / SQL 마이그레이션         → db-migration
신호 미발생 / 장애 추적              → signal-debugger
scorer.py / Claude 프롬프트          → ai-scorer
telegram-bot 커맨드·메시지 포맷      → telegram-dev
```
