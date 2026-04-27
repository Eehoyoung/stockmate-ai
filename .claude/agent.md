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
| `trader-advisor` | `agents/trader-advisor.md` | TP/SL 설정, R:R 검토, 진입·청산 전략, 리스크 파라미터 |
| `pm-planner` | `agents/pm-planner.md` | 기능 우선순위, 미완료 작업 정리, 로드맵 수립 |
| `perf-optimizer` | `agents/perf-optimizer.md` | Redis/asyncio 병목, API 레이턴시, DB 쿼리 최적화 |
| `code-reviewer` | `agents/code-reviewer.md` | PR 리뷰, 보안 점검, 컨벤션 검토, 테스트 커버리지 |

## 에이전트 선택 가이드

```
전략 파일(strategy_*.py) 수정        → strategy-dev
Docker / 컨테이너 운영               → docker-ops
Kiwoom API 연동 / 토큰               → kiwoom-api
DB 스키마 / SQL 마이그레이션         → db-migration
신호 미발생 / 장애 추적              → signal-debugger
scorer.py / Claude 프롬프트          → ai-scorer
telegram-bot 커맨드·메시지 포맷      → telegram-dev
TP/SL · R:R · 리스크 관리           → trader-advisor
기능 우선순위 · 미완료 작업 정리     → pm-planner
성능 병목 · 레이턴시 최적화          → perf-optimizer
코드 품질 · 보안 · PR 리뷰           → code-reviewer
```

## 에이전트 사용 방법

### 1. 자동 라우팅 (권장)
Claude Code가 작업 내용을 보고 적합한 에이전트를 자동으로 선택합니다.
그냥 평소처럼 요청하면 됩니다.

```
"S9 전략 RSI 조건 강화해줘"      → strategy-dev 자동 선택
"ai-engine 컨테이너 로그 봐줘"   → docker-ops 자동 선택
```

### 2. 명시적 지정
특정 에이전트를 직접 지정하려면 요청 앞에 에이전트명을 언급합니다.

```
"trader-advisor로 S14 TP/SL 검토해줘"
"pm-planner한테 이번 스프린트 우선순위 정리 부탁해"
"code-reviewer로 오늘 변경분 리뷰해줘"
```

### 3. Claude Code CLI에서 직접 실행
```bash
# 대화 중 에이전트 명시 호출
claude "trader-advisor: 현재 R:R 설정 검토해줘"

# 또는 슬래시 커맨드
/strategy-audit strategy_14_oversold_bounce.py
```

### 4. 병렬 실행
독립적인 작업을 여러 에이전트에게 동시에 맡길 수 있습니다.

```
"strategy-dev로 S14 수정하면서 동시에 
 perf-optimizer로 queue_worker 병목도 확인해줘"
```
